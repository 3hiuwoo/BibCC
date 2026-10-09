"""
Field-level sanity checks for BibTeX entries.

Reports problems BibTeX itself stays silent about:

- **unknown fields**: names that are not standard BibTeX/biblatex fields or
  commonly exported ones, usually typos (``volumn`` → ``volume``), which
  BibTeX ignores without a warning;
- **suspicious values**: empty values, years that are not four digits,
  single-hyphen page ranges, DOIs written as URLs or malformed, months that
  are not macros, malformed ISSNs, URLs without a scheme;
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
from typing import Callable, Iterable, List, Optional, Sequence, Set, Tuple

import bibtexparser

from bibcc.bibedit import BibEditError, month_macro, page_range, read_bib, scan, unwrap, value_tokens
from bibcc.logging_utils import SEPARATOR_LIGHT, SEPARATOR_WIDTH

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
    parser = bibtexparser.bparser.BibTexParser(common_strings=True)
    entries = bibtexparser.loads(text, parser=parser).entries
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
    else:
        log(f"✅ No field issues in {len(entries)} entries.")
    return issues
