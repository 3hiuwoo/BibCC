"""
Field-level sanity checks for BibTeX entries.

Reports problems BibTeX itself stays silent about:

- **unknown fields**: names that are not standard BibTeX/biblatex fields or
  commonly exported ones, usually typos (``volumn`` → ``volume``), which
  BibTeX ignores without a warning;
- **suspicious values**: empty values, years that are not four digits,
  single-hyphen page ranges, DOIs written as URLs or malformed, months that
  are not macros, malformed ISSNs, URLs without a scheme;
- **interim fields**: fields that only an interim or preprint version gives
  (a CVF Open Access, OpenReview, or arXiv ``url``; ``eprint``,
  ``archiveprefix``, ``primaryclass``; an arXiv ``note``) on an entry whose
  BibTeX comes from somewhere else, such as IEEE Xplore BibTeX with the CVF
  page as its ``url``.  ``trim_fields`` deletes them, and the empty values;
- **conference articles**: ``@article`` entries whose ``journal`` names
  conference proceedings, as AAAI's export does; ``bibcc complete`` makes
  them ``@inproceedings``;
- **duplicates**: the same paper (same DOI, arXiv ID, or title) or the same
  citation key appearing twice in the file or in the ``against`` files.

Raw values are read with :func:`bibcc.bibedit.scan` rather than bibtexparser,
which expands month macros and would hide whether ``month = jun`` was used.

Usage:
    rows = check_field_issues("refs.bib", against=["bib/"])
"""

from __future__ import annotations

import difflib
import re
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional, Sequence, Set, Tuple

import bibtexparser

from bibcc.bibedit import (
    BibEditError,
    month_macro,
    page_range,
    read_bib,
    remove_fields,
    scan,
    unwrap,
    value_tokens,
    write_bib,
)
from bibcc.logging_utils import SEPARATOR_LIGHT, SEPARATOR_WIDTH
from bibcc.venues import is_conference_journal

# Standard BibTeX fields, biblatex fields, and fields that CrossRef, DBLP,
# ACM, IEEE, Zotero, and BibCC itself commonly write.
KNOWN_FIELDS: Set[str] = {
    # BibTeX
    "address", "annote", "author", "booktitle", "chapter", "crossref", "edition",
    "editor", "howpublished", "institution", "journal", "key", "month", "note",
    "number", "organization", "pages", "publisher", "school", "series", "title",
    "type", "volume", "year",
    # biblatex
    "addendum", "booksubtitle", "booktitleaddon", "date", "day", "eid", "eprint",
    "eprintclass", "eprinttype", "eventdate", "eventtitle", "issue", "issuetitle",
    "journaltitle", "journalsubtitle", "langid", "language", "location", "maintitle",
    "origdate", "pagetotal", "part", "pubstate", "shortjournal", "shorttitle",
    "subtitle", "titleaddon", "urldate", "venue", "version", "volumes",
    # identifiers and links
    "archiveprefix", "doi", "isbn", "issn", "pmid", "primaryclass", "url",
    # exporters (ACM, IEEE, DBLP, Zotero, Mendeley, Google Scholar)
    "abstract", "articleno", "bibsource", "biburl", "copyright", "file",
    "issue_date", "keywords", "mendeley-groups", "numpages", "pdf", "publisher-place",
    "timestamp",
    # BibCC (scholar cite)
    "citation",
}

_ISSN = re.compile(r"^\d{4}-\d{3}[\dXx]$")
_DOI = re.compile(r"^10\.\d{4,9}/\S+$")
_DOI_PREFIX = re.compile(r"^(https?://(dx\.)?doi\.org/|doi:\s*)", re.IGNORECASE)

Issue = Tuple[str, str, str]  # (entry_id, issue_type, detail)

INTERIM_FIELD = "interim_field"
CONFERENCE_ARTICLE = "conference_article"
_ARXIV_FIELDS = ("eprint", "archiveprefix", "primaryclass", "eprinttype", "eprintclass")
_PREPRINT_VENUE = re.compile(r"\b(arxiv|corr|preprint)\b", re.IGNORECASE)
# Entry types that stand for a preprint, where arXiv fields belong.
_PREPRINT_TYPES = {"misc", "unpublished", "online", "techreport"}


def suggest_field(name: str, known: Iterable[str] = KNOWN_FIELDS) -> Optional[str]:
    """Closest known field name, e.g. ``volume`` for ``volumn``."""
    matches = difflib.get_close_matches(name, sorted(known), n=1, cutoff=0.75)
    return matches[0] if matches else None


def value_issues(name: str, raw: str) -> List[Tuple[str, str]]:
    """``(issue_type, detail)`` problems with one raw field value."""
    issues: List[Tuple[str, str]] = []
    if len(value_tokens(raw)) > 1:
        return issues
    value = unwrap(raw).strip()
    bare = not raw.strip().startswith(("{", '"'))

    if not value:
        return [("empty_value", f"{name} is empty")]
    if name == "year" and not re.fullmatch(r"\d{4}", value):
        issues.append(("bad_year", f"year '{value}' is not four digits"))
    elif name == "pages":
        fixed = page_range(value)
        if fixed != value:
            issues.append(("page_range", f"'{value}' → '{fixed}'"))
    elif name == "doi":
        if _DOI_PREFIX.match(value):
            issues.append(("doi_format", f"write the bare DOI: '{_DOI_PREFIX.sub('', value)}'"))
        elif not _DOI.match(value):
            issues.append(("doi_format", f"'{value}' does not look like a DOI (10.xxxx/...)"))
    elif name == "month":
        macro = month_macro(value)
        if macro is None:
            issues.append(("month_format", f"'{value}' is not a month"))
        elif not bare:
            issues.append(("month_format", f"'{raw.strip()}' → {macro}"))
    elif name == "issn":
        bad = [v.strip() for v in re.split(r"[,;]", value) if not _ISSN.match(v.strip())]
        if bad:
            issues.append(("issn_format", f"'{bad[0]}' is not NNNN-NNNC"))
    elif name == "url" and not re.match(r"^(https?|ftp)://", value, re.IGNORECASE):
        issues.append(("url_format", f"'{value}' has no http(s):// scheme"))
    return issues


def interim_leftovers(entry: Dict[str, str]) -> List[Tuple[str, str]]:
    """``(field, detail)`` for the interim or preprint fields of a parsed entry that isn't that version.

    A CVF Open Access ``url`` belongs only to an entry with the CVF booktitle,
    an OpenReview one only to an OpenReview booktitle (or a journal, such as
    TMLR, published there), and arXiv fields only to preprint entries.  On
    any other entry they're left over from the version it replaced, because
    the official export (IEEE Xplore's, for example) doesn't have them.
    """
    # Imported here: bibcc.official and bibcc.sources import this package.
    from bibcc.official import ICLR_PROCEEDINGS_SINCE, INTERIM_CVF, INTERIM_OPENREVIEW, interim_source_of
    from bibcc.sources import normalize_arxiv_id

    entry_type = entry.get("ENTRYTYPE", "").lower()
    venue = entry.get("booktitle") or entry.get("journal") or ""
    if entry_type in _PREPRINT_TYPES or not venue.strip() or _PREPRINT_VENUE.search(venue):
        return []
    # Without the year, every OpenReview-style name counts, ICLR before 2024 included.
    named = interim_source_of(venue)
    year = entry.get("year", "").strip()
    old_iclr = "learning representations" in venue.lower() and year.isdigit() and int(year) < ICLR_PROCEEDINGS_SINCE
    found: List[Tuple[str, str]] = []
    url = entry.get("url", "")
    if "openaccess.thecvf.com" in url.lower():
        if named != INTERIM_CVF:
            found.append(("url", "CVF Open Access URL on an entry that isn't the CVF Open Access BibTeX"))
    elif "openreview.net" in url.lower():
        if entry_type == "inproceedings" and named != INTERIM_OPENREVIEW and not old_iclr:
            found.append(("url", "OpenReview URL on an entry that isn't the OpenReview BibTeX"))
    elif normalize_arxiv_id(url):
        found.append(("url", "arXiv URL on an entry that isn't a preprint"))
    archive = (entry.get("archiveprefix", "") + entry.get("eprinttype", "")).lower()
    if "arxiv" in archive or normalize_arxiv_id(entry.get("eprint", "")):
        found += [(n, "arXiv field on an entry that isn't a preprint") for n in _ARXIV_FIELDS if n in entry]
    if _PREPRINT_VENUE.search(entry.get("note", "")):
        found.append(("note", "arXiv note on an entry that isn't a preprint"))
    return found


def _parsed(text: str) -> List[Dict[str, str]]:
    parser = bibtexparser.bparser.BibTexParser(common_strings=True)
    return bibtexparser.loads(text, parser=parser).entries


def _empty_fields(text: str) -> Dict[str, List[str]]:
    """``{key: [field, ...]}`` of the fields whose value is empty (``volume = {}``)."""
    found: Dict[str, List[str]] = {}
    for entry in scan(text):
        names = [
            name for name, span in entry.fields.items()
            if ("empty_value", f"{name} is empty") in value_issues(name, text[span.value_start : span.value_end])
        ]
        if names:
            found[entry.key] = names
    return found


def trim_fields(input_path: str, log: Optional[Callable[[str], None]] = None) -> List[Tuple[str, str]]:
    """Remove the interim fields (:func:`interim_leftovers`) and the empty fields of *input_path*.

    Only those fields change, and the edit is verified before the file is
    written.  An entry whose every field is empty is left alone.  Returns
    ``(entry_id, field)`` for each field removed; nothing is written if the
    edit cannot be verified.
    """
    log = log or print
    log(f"🧹 Removing interim and empty fields from the entries of {input_path}...\n")
    text = read_bib(input_path)
    try:
        fields_of = {e.key: set(e.fields) for e in scan(text)}
    except BibEditError as e:
        log(f"❌ Cannot read {input_path}: {e}")
        return []
    removals: Dict[str, List[str]] = {}
    for entry in _parsed(text):
        for name, _ in interim_leftovers(entry):
            removals.setdefault(entry["ID"], []).append(name)
    for key, names in _empty_fields(text).items():
        removals.setdefault(key, []).extend(n for n in names if n not in removals.get(key, []))
    removals = {k: v for k, v in removals.items() if set(v) != fields_of.get(k)}
    if not removals:
        log("✅ No entry has interim or empty fields.")
        return []
    try:
        new_text, applied = remove_fields(text, removals)
    except BibEditError as e:
        log(f"❌ Could not remove the fields safely: {e}")
        log("   Nothing was written.")
        return []
    write_bib(input_path, new_text)
    for edit in applied:
        log(f"{edit.key:<45} | {edit.field:<13} | {unwrap(edit.old or '')}")
    log(SEPARATOR_LIGHT * SEPARATOR_WIDTH)
    log(f"✏️  Removed {len(applied)} fields from {len(removals)} entries of {input_path}.\n")
    return [(edit.key, edit.field) for edit in applied]


def _duplicates(
    text: str,
    input_path: str,
    against: Sequence[str | Path],
    log: Callable[[str], None],
) -> List[Issue]:
    # Imported here: bibcc.adder and bibcc.sources import this package, so
    # module-level imports would be circular.
    from bibcc.adder import BibIndex
    from bibcc.sources import entry_arxiv_id

    index = BibIndex()
    if against:
        index.add_paths(against, exclude=Path(input_path), log=log)
    entries = _parsed(text)
    issues: List[Issue] = []
    for entry in entries:
        key = entry["ID"]
        if key.lower() in index.keys:
            where = index.key_where[key.lower()]
            where = "this file" if where == input_path else where
            issues.append((key, "duplicate_key", f"citation key is already used ({where})"))
        dup = index.find(
            doi=entry.get("doi", ""),
            arxiv_id=entry_arxiv_id(entry) or "",
            title=entry.get("title", ""),
        )
        if dup and dup.key != key:
            where = "this file" if dup.where == input_path else dup.where
            issues.append((key, "duplicate_paper", f"{dup.reason} as {dup.key} ({where})"))
        index.add(entry, input_path)
    return issues


def check_field_issues(
    input_path: str,
    against: Sequence[str | Path] = (),
    extra_fields: Iterable[str] = (),
    log: Optional[Callable[[str], None]] = None,
) -> List[Issue]:
    """Check field names, field values, and duplicates in *input_path*.

    Args:
        input_path: Path to the BibTeX file.
        against: Other ``.bib`` files or directories to look for duplicates in.
        extra_fields: Field names to accept in addition to :data:`KNOWN_FIELDS`.
        log: Optional logging callback; falls back to ``print``.

    Returns:
        ``(entry_id, issue_type, detail)`` tuples.
    """
    log = log or print
    log(f"🧾 Checking field names, values, and duplicates in {input_path}...\n")
    known = KNOWN_FIELDS | {f.lower() for f in extra_fields}

    try:
        text = read_bib(input_path)
        entries = scan(text)
    except FileNotFoundError:
        log(f"❌ Error: File '{input_path}' not found.")
        return []
    except BibEditError as e:
        log(f"❌ Cannot read {input_path}: {e}")
        return [("(file)", "syntax", str(e))]

    issues: List[Issue] = []
    for entry in entries:
        for name, span in entry.fields.items():
            if name not in known:
                hint = suggest_field(name, known)
                detail = f"'{span.name}'" + (f" → did you mean '{hint}'?" if hint else " is not a known field")
                issues.append((entry.key, "unknown_field", detail))
            raw = text[span.value_start : span.value_end]
            issues.extend((entry.key, kind, detail) for kind, detail in value_issues(name, raw))

    for parsed in _parsed(text):
        issues.extend((parsed["ID"], INTERIM_FIELD, f"{name}: {detail}") for name, detail in interim_leftovers(parsed))
        if parsed.get("ENTRYTYPE") == "article" and is_conference_journal(parsed.get("journal")):
            issues.append((parsed["ID"], CONFERENCE_ARTICLE,
                           f"@article for conference proceedings '{parsed['journal']}'; "
                           "'bibcc complete' makes it @inproceedings with this booktitle"))

    issues.extend(_duplicates(text, str(input_path), against, log))

    log(f"{'ID':<45} | {'Issue':<16} | Detail")
    log(SEPARATOR_LIGHT * SEPARATOR_WIDTH)
    for entry_id, kind, detail in issues:
        log(f"{entry_id:<45} | {kind:<16} | {detail}")
    log(SEPARATOR_LIGHT * SEPARATOR_WIDTH)
    if issues:
        counts: dict = {}
        for _, kind, _ in issues:
            counts[kind] = counts.get(kind, 0) + 1
        breakdown = "; ".join(f"{k}: {n}" for k, n in sorted(counts.items()))
        log(f"⚠️  Found {len(issues)} issues in {len(entries)} entries. Breakdown -> {breakdown}")
        trimmed = [kind for kind in (INTERIM_FIELD, "empty_value") if kind in counts]
        if trimmed:
            log(f"   To remove the {' and '.join(trimmed)} fields, run 'bibcc check fields {input_path} --apply'.")
    else:
        log(f"✅ No field issues in {len(entries)} entries.")
    return issues
