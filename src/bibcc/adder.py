"""
Add papers to a staging .bib file from a DOI, arXiv ID/URL, paper page URL, or title.

For each identifier the paper is located (see :mod:`bibcc.sources`; arXiv
papers are replaced by their published version when one is found) and its
official BibTeX is downloaded from the publisher or proceedings site (see
:mod:`bibcc.official`).  The entry is that BibTeX, polished to the survey's
style: Title Case with technical terms brace-protected, ``--`` page ranges,
month macros, abstracts and keywords dropped, venue fields the entry lacks
added from the venue library (differences are reported, never overwritten),
and a ``METHOD_AUTHOR_VENUEYEAR`` key.

When the official BibTeX cannot be downloaded (AAAI, ACM, and Elsevier
block it; ECCV papers not on SpringerLink yet), an *empty* entry is written
under the suggested key, with a comment giving the title, DOI, the reason,
and where to get the BibTeX by hand.  For CVPR, ICCV, and WACV papers not in
IEEE Xplore yet the CVF Open Access BibTeX is used, and for NeurIPS, ICLR,
and ICML papers not in the proceedings yet the OpenReview BibTeX; ``bibcc
upgrade`` replaces these interim entries once the proceedings are out.

Papers already present in the ``--against`` bibliography or the staging
file (same DOI, arXiv ID, or title, including empty entries) are skipped.
Venues missing from the library are proposed in
``.bibcc/<output>.missing_venues.yaml`` (merged on every run).

New entries are appended to the staging file only; move them into the
topic files yourself after reviewing them.

Usage:
    bibcc add 10.1109/TPAMI.2024.3429383 2501.13198 --against bib/
    bibcc add --from new_papers.txt --against bib/ --output added.bib
"""

from __future__ import annotations

import argparse
import re
import sys
import time
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional, Set, Tuple

import bibtexparser

from bibcc.bibedit import BibEditError, month_macro, read_bib, scan, write_bib
from bibcc.checkers.citation_keys import abbreviate_venue
from bibcc.checkers.smart_protection import find_unprotected_terms, protect_terms
from bibcc.completer import EntryCompletion, complete_entry
from bibcc.crosscheck import venue_fields_from_crossref
from bibcc.helptext import ENV_S2, ENV_VENUES, VENUES_HELP, HelpFormatter, epilog
from bibcc.logging_utils import SEPARATOR_THIN, SEPARATOR_WIDTH, Logger, get_output_dir
from bibcc.missing_venues import JOURNAL_FIELDS, PROCEEDINGS_FIELDS, MissingVenue, write_missing_venues
from bibcc.official import (
    Official,
    OfficialLookup,
    family_of,
    find_official,
    interim_source_of,
    official_fields,
    official_from_url,
    record_from_official,
)
from bibcc.sources import (
    Record,
    clean_title_for_search,
    entry_arxiv_id,
    is_arxiv_doi,
    normalize_doi,
    normalize_for_comparison,
    parse_identifier,
    resolve,
)
from bibcc.titlecases import APA_STOPWORDS, suggest_title_case
from bibcc.venues import JOURNAL, PROCEEDINGS, VenueLibrary, load_library, normalize_venue

DEFAULT_OUTPUT = "added.bib"

FIELD_ORDER = [
    "title",
    "author",
    "journal",
    "booktitle",
    "year",
    "month",
    "day",
    "volume",
    "number",
    "pages",
    "publisher",
    "series",
    "editor",
    "address",
    "venue",
    "isbn",
    "issn",
    "doi",
    "eprint",
    "archiveprefix",
    "primaryclass",
    "url",
]

_NAME_PARTICLES = {"van", "von", "de", "der", "den", "di", "da", "del", "della", "du", "dos", "la", "le", "ter", "ten"}
# Official BibTeX fields that may hold a bare & % # _ or a unicode dash.
_TEXT_FIELDS = ("title", "journal", "booktitle", "publisher", "series", "venue")
# Header of the comment written above an empty entry; BibIndex reads the lines after it.
EMPTY_ENTRY_MARK = "% BibCC: no official BibTeX"


# ------------------------------------------------------------- formatting


def latex_escape(text: str) -> str:
    """Escape ``& % # _`` outside ``$...$`` math, leaving existing escapes alone."""
    parts = re.split(r"(?<!\\)(\$[^$]*\$)", text)
    return "".join(
        part if part.startswith("$") and part.endswith("$") and len(part) > 1
        else re.sub(r"(?<!\\)([&%#_])", r"\\\1", part)
        for part in parts
    )


def _texify(value: str) -> str:
    return latex_escape(value.replace("—", "---").replace("–", "--"))


def format_entry(entry_type: str, key: str, fields: Dict[str, str]) -> str:
    """Format an entry in the survey's style: aligned ``=``, months as macros."""
    names = [n for n in FIELD_ORDER if fields.get(n)]
    names += [n for n in fields if n not in FIELD_ORDER and fields[n]]
    width = max((len(n) for n in names), default=0)
    lines = [f"@{entry_type}{{{key},"]
    for i, name in enumerate(names):
        macro = month_macro(fields[name]) if name == "month" else None
        value = macro or f"{{{fields[name]}}}"
        comma = "," if i < len(names) - 1 else ""
        lines.append(f"  {name.ljust(width)} = {value}{comma}")
    lines.append("}")
    return "\n".join(lines)


# ------------------------------------------------------------------- keys


def _ascii_name(text: str) -> str:
    text = re.sub(r"\\[a-zA-Z]+|\\.", "", text)
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^A-Za-z'\-]", "", text)


def first_author_surname(author: str) -> str:
    """Surname of the first author, ASCII-folded, particles joined (``vandeVen``)."""
    first = re.split(r"\s+and\s+", author.strip())[0]
    if "," in first:
        surname = first.split(",")[0]
    else:
        tokens = first.split()
        if not tokens:
            return ""
        parts = [tokens[-1]]
        i = len(tokens) - 2
        while i >= 1 and tokens[i].lower() in _NAME_PARTICLES:
            parts.insert(0, tokens[i])
            i -= 1
        surname = "".join(parts)
    return _ascii_name(surname.replace(" ", "").replace("{", "").replace("}", ""))


def suggest_method(title: str) -> str:
    """Method name from a ``Name: ...`` title prefix, else the first two content words."""
    plain = clean_title_for_search(title)
    m = re.match(r"^\s*([^\s:]{2,30})\s*:", plain)
    if m:
        token = re.sub(r"[^A-Za-z0-9+\-]", "", m.group(1))
        if token:
            return token
    words = [w for w in re.findall(r"[A-Za-z0-9]+", plain) if w.lower() not in APA_STOPWORDS]
    return "".join(w[:1].upper() + w[1:] for w in words[:2]) or "Paper"


def suggest_key(entry_type: str, fields: Dict[str, str], taken: Set[str]) -> str:
    """``METHOD_AUTHOR_VENUEYEAR``, made unique against *taken* (lower-cased keys)."""
    method = suggest_method(fields.get("title", ""))
    author = first_author_surname(fields.get("author", "")) or "Anon"
    if entry_type == "misc" and fields.get("archiveprefix", "").lower() == "arxiv":
        venue = "arXiv"
    else:
        venue = abbreviate_venue(fields.get("journal") or fields.get("booktitle")) or "Venue"
    year = fields.get("year", "")
    key = f"{method}_{author}_{venue}{year}"
    n = 2
    while key.lower() in taken:
        key = f"{method}{n}_{author}_{venue}{year}"
        n += 1
    return key


# ------------------------------------------------------------ duplicates


@dataclass
class Duplicate:
    """An existing entry that is the same paper."""

    key: str
    where: str
    reason: str


def _title_key(title: str) -> str:
    return normalize_for_comparison(clean_title_for_search(title))


def _empty_entry_info(text: str, start: int) -> Dict[str, str]:
    """``title``/``doi``/``arxiv`` from the BibCC comment just above an empty entry."""
    lines = text[:start].rstrip("\n").splitlines()
    block: List[str] = []
    while lines and lines[-1].lstrip().startswith("%"):
        block.insert(0, lines.pop())
    if not block or not block[0].startswith(EMPTY_ENTRY_MARK):
        return {}
    info = {}
    for line in block[1:]:
        m = re.match(r"^%\s+(title|doi|arxiv):\s*(.+?)\s*$", line)
        if m:
            info[m.group(1)] = m.group(2)
    return info


class BibIndex:
    """DOI / arXiv ID / title index of existing entries, for duplicate checks."""

    def __init__(self) -> None:
        self._doi: Dict[str, Tuple[str, str]] = {}
        self._arxiv: Dict[str, Tuple[str, str]] = {}
        self._title: Dict[str, Tuple[str, str]] = {}
        self.keys: Set[str] = set()
        self.key_where: Dict[str, str] = {}
        self.files = 0

    def add(self, entry: Dict[str, str], where: str) -> None:
        key = entry.get("ID", "")
        self.keys.add(key.lower())
        self.key_where.setdefault(key.lower(), where)
        loc = (key, where)
        doi = normalize_doi(entry.get("doi", "")).lower()
        if doi and not is_arxiv_doi(doi):
            self._doi.setdefault(doi, loc)
        arxiv_id = entry_arxiv_id(entry)
        if arxiv_id:
            self._arxiv.setdefault(arxiv_id, loc)
        title = _title_key(entry.get("title", ""))
        if title:
            self._title.setdefault(title, loc)

    def add_text(self, text: str, where: str) -> int:
        """Index the entries of a .bib text, including BibCC's empty entries; returns the count."""
        parser = bibtexparser.bparser.BibTexParser(common_strings=True)
        entries = bibtexparser.loads(text, parser=parser).entries
        for entry in entries:
            self.add(entry, where)
        parsed = {e["ID"] for e in entries}
        try:
            spans = scan(text)
        except BibEditError:
            spans = []
        empty = 0
        for span in spans:
            if span.key in parsed or span.fields:
                continue
            info = _empty_entry_info(text, span.start)
            self.add({"ID": span.key, "title": info.get("title", ""), "doi": info.get("doi", ""),
                      "eprint": info.get("arxiv", "")}, where)
            empty += 1
        return len(entries) + empty

    def add_paths(
        self, paths: Iterable[str | Path], exclude: Optional[Path], log: Callable[[str], None]
    ) -> int:
        """Index .bib files and directories (recursively); returns the entry count."""
        excluded = exclude.resolve() if exclude else None
        count = 0
        for raw in paths:
            path = Path(raw)
            if path.is_dir():
                files = sorted(
                    p for p in path.rglob("*.bib")
                    if not any(part.startswith(".") for part in p.relative_to(path).parts)
                )
            elif path.exists():
                files = [path]
            else:
                log(f"⚠️  --against path not found: {path}")
                continue
            for file in files:
                if excluded and file.resolve() == excluded:
                    continue
                try:
                    count += self.add_text(read_bib(file), str(file))
                    self.files += 1
                except Exception as e:  # noqa: BLE001 - a broken file should not stop the run
                    log(f"⚠️  Could not read {file}: {e}")
        return count

    def find(self, doi: str = "", arxiv_id: str = "", title: str = "") -> Optional[Duplicate]:
        doi = normalize_doi(doi).lower()
        if doi and doi in self._doi:
            return Duplicate(*self._doi[doi], reason=f"same DOI {doi}")
        if arxiv_id and arxiv_id in self._arxiv:
            return Duplicate(*self._arxiv[arxiv_id], reason=f"same arXiv ID {arxiv_id}")
        title_key = _title_key(title)
        if title_key and title_key in self._title:
            return Duplicate(*self._title[title_key], reason="same title")
        return None


# ------------------------------------------------------------- building


_PARTLY_BRACED = re.compile(r"^(?:[^\s{}\\]*\{[^\s{}\\]+\})+[^\s{}\\]*$")
_FULLY_BRACED = re.compile(r"^\{[^{}]*\}$")


def _merge_word_braces(title: str) -> str:
    """``{SD}-Lo{RA}:`` → ``{SD-LoRA}:``: one brace group per partly braced word."""
    words = []
    for word in title.split(" "):
        core = word.rstrip(":,;.!?")
        if _PARTLY_BRACED.match(core) and not _FULLY_BRACED.match(core):
            word = "{" + core.replace("{", "").replace("}", "") + "}" + word[len(core):]
        words.append(word)
    return " ".join(words)


def polish_fields(fields: Dict[str, str], keep_title: bool = False) -> Dict[str, str]:
    """Official BibTeX values in the survey's style (Title Case, protected terms, escapes)."""
    out = {k: _texify(v) if k in _TEXT_FIELDS else v for k, v in fields.items() if v}
    title = _merge_word_braces(out.get("title", "").rstrip("."))
    if title:
        if not keep_title:
            title = suggest_title_case(title)
        words = [w for w, _ in find_unprotected_terms(title, out.get("author", ""))]
        out["title"] = protect_terms(title, words)
    for name in ("journal", "booktitle"):
        if out.get(name):
            words = [
                w for w, reason in find_unprotected_terms(out[name], vocab_terms=[])
                if reason in ("Acronym", "Mixed Case")
            ]
            out[name] = protect_terms(out[name], words)
    return out


@dataclass
class BuiltEntry:
    """An entry made from official BibTeX, ready to format."""

    entry_type: str
    fields: Dict[str, str]
    notes: List[str] = field(default_factory=list)
    # The library match, and the venue name and year as in the official BibTeX.
    completion: Optional[EntryCompletion] = None
    venue_name: str = ""
    year: str = ""


def build_entry(official: Official, library: VenueLibrary, keep_title: bool = False, doi: str = "") -> BuiltEntry:
    """Turn downloaded official BibTeX into entry fields completed from the library.

    Like ``bibcc complete``: fields the entry lacks come from the library,
    differing ones are reported and the official value kept, and an interim
    booktitle of a library record only gets the event fields.  *doi*, the
    DOI the paper was located by, is added when the official BibTeX has none
    (Springer's export never does).
    """
    entry_type, raw = official_fields(official.text)
    doi = normalize_doi(doi)
    if doi and not is_arxiv_doi(doi) and not raw.get("doi"):
        raw["doi"] = doi
    fields = polish_fields(raw, keep_title=keep_title)
    venue_name = raw.get("booktitle") or raw.get("journal") or ""
    built = BuiltEntry(entry_type, fields, venue_name=venue_name, year=raw.get("year", ""))
    done = complete_entry({"ID": "", "ENTRYTYPE": entry_type, **raw}, library)
    built.completion = done
    if done.status == "matched" and done.venue is not None:
        for name, value in done.patch.items():
            fields.setdefault(name, value)
        for name, existing, value in done.conflicts:
            built.notes.append(f"{name}: official '{existing}' kept; the venue library has '{value}'")
        if done.interim_source and not official.interim:
            built.notes.append(
                f"'{venue_name}' is the {done.interim_source} name of '{done.venue.name}', which is out; "
                "`bibcc upgrade` may find the published version"
            )
    elif done.status == "ambiguous":
        labels = ", ".join(v.label for v in done.ambiguous)
        built.notes.append(f"venue matches several library records ({labels}); fields not filled")
    elif done.status == "missing":
        year = f" {built.year}" if done.kind == PROCEEDINGS else ""
        built.notes.append(f"venue '{venue_name}'{year} is not in the venue library; see the missing-venues YAML")
    if official.interim and done.interim_source and done.venue is not None:
        built.notes.append(
            f"interim BibTeX from {official.provider}: the paper was not found in '{done.venue.name}' "
            "(the published proceedings); `bibcc upgrade` can try again later"
        )
    elif official.interim:
        built.notes.append(
            f"interim BibTeX from {official.provider}: the proceedings are not out yet; "
            "`bibcc upgrade` replaces it once they are"
        )
    return built


def _interim_placeholders(library: VenueLibrary, name: str, year: str) -> Dict[str, List[str]]:
    """Library records of the same conference and year still named by an interim booktitle."""
    family = family_of(name, year)
    found: Dict[str, List[str]] = {}
    if not family:
        return found
    for venue in library.proceedings:
        if str(venue.year).strip() != year or normalize_venue(venue.name) == normalize_venue(name):
            continue
        source = interim_source_of(venue.name, year=year)
        if source and family_of(venue.name, year) == family:
            found.setdefault(source, []).append(venue.name)
    return found


def venue_proposals(
    built: BuiltEntry,
    official: Official,
    library: VenueLibrary,
    key: str,
    record: Optional[Record] = None,
) -> List[MissingVenue]:
    """Missing-venue records suggested by one new entry (empty if the library has its venue)."""
    done = built.completion
    if done is None or done.status != "missing" or not built.venue_name:
        return []
    names = JOURNAL_FIELDS if done.kind == JOURNAL else PROCEEDINGS_FIELDS
    _, raw = official_fields(official.text)
    proposal = MissingVenue(
        done.kind,
        built.venue_name,
        built.year,
        collected={n: raw[n] for n in names if raw.get(n)},
        collected_label="from official BibTeX",
    )
    if record is not None and record.source.startswith("CrossRef"):
        proposal.crossref = venue_fields_from_crossref(record, done.kind)
    if official.interim:
        proposal.notes.append(
            f"{official.provider} booktitle (seen in {key}); the proceedings are not out yet, "
            "so this is the venue's name until they are"
        )
    elif done.kind == PROCEEDINGS:
        proposal.interim = _interim_placeholders(library, built.venue_name, built.year)
        for source, names_ in proposal.interim.items():
            for old in names_:
                proposal.notes.append(
                    f"merging renames the library record '{old}' ({source} booktitle) to this name: "
                    f"{key} is in these published proceedings"
                )
    return [proposal]


def empty_entry(entry_type: str, key: str, record: Record, lookup: OfficialLookup) -> str:
    """An entry with no fields, under a comment saying what to paste and where to get it."""

    def safe(text: str) -> str:
        # '@' in a comment line would start an entry for some parsers.
        return " ".join(text.replace("@", "(at)").split())

    f = record.fields
    venue = f.get("journal") or f.get("booktitle") or ""
    lines = [f"{EMPTY_ENTRY_MARK} could be downloaded; paste it into the entry below, keeping the key."]
    lines.append(f"%   title:  {safe(f.get('title', ''))}")
    if venue:
        lines.append(f"%   venue:  {safe(venue)} ({f.get('year', '')})")
    doi = normalize_doi(record.doi or f.get("doi", ""))
    if doi and not is_arxiv_doi(doi):
        lines.append(f"%   doi:    {doi}")
    if record.arxiv_id:
        lines.append(f"%   arxiv:  {record.arxiv_id}")
    lines.append(f"%   reason: {safe(lookup.reason or 'no official BibTeX source is known for this paper')}")
    if lookup.manual_url:
        lines.append(f"%   get it: {lookup.manual_url}")
    lines.append(format_entry(entry_type, key, {}))
    return "\n".join(lines)


# ------------------------------------------------------------------ main


def read_identifiers(path: str | Path) -> List[str]:
    """One identifier per line; blank lines and ``#`` comments are ignored."""
    lines = Path(path).read_text(encoding="utf-8").splitlines()
    return [line.strip() for line in lines if line.strip() and not line.lstrip().startswith("#")]


def _check_entry(text: str, key: str) -> None:
    spans = scan(text)
    if [e.key for e in spans] != [key]:
        raise BibEditError(f"generated entry '{key}' does not parse back")
    if spans[0].fields:
        parser = bibtexparser.bparser.BibTexParser(common_strings=True)
        entries = bibtexparser.loads(text, parser=parser).entries
        if [e["ID"] for e in entries] != [key]:
            raise BibEditError(f"generated entry '{key}' does not parse back")


def _locate(
    identifier: str, library: VenueLibrary, prefer_published: bool, log: Callable[[str], None]
) -> Tuple[Optional[Record], Optional[OfficialLookup], Optional[str]]:
    """``(record, official lookup, error)`` for one identifier."""
    kind, value = parse_identifier(identifier)
    if kind == "url":
        lookup = official_from_url(value)
        if lookup.official is None:
            return None, None, lookup.error or lookup.reason or "no official BibTeX at this URL"
        record = record_from_official(lookup.official)
        if record is None:
            return None, None, f"{lookup.official.provider} returned BibTeX that does not parse"
        return record, lookup, None
    result = resolve(identifier, library, prefer_published=prefer_published, log=log)
    if result.record is None:
        return None, None, result.error or "not found"
    log(f"   📍 {result.record.source}; looking for the official BibTeX...")
    return result.record, find_official(result.record), None


def add_papers(
    identifiers: List[str],
    output: str | Path,
    library: VenueLibrary,
    against: Optional[List[str]] = None,
    prefer_published: bool = True,
    keep_title: bool = False,
    dry_run: bool = False,
    delay: float = 1.0,
    log: Optional[Callable[[str], None]] = None,
    report_dir: Optional[Path] = None,
) -> Dict[str, list]:
    """Locate *identifiers*, download their official BibTeX, and append entries to *output*.

    Returns ``{"added": [(identifier, key)], "empty": [(identifier, key,
    reason)], "duplicates": [(identifier, Duplicate)], "failed":
    [(identifier, error)]}``.  Empty entries are also listed in ``added``.
    """
    log = log or print
    output = Path(output)
    index = BibIndex()
    if against:
        count = index.add_paths(against, exclude=output, log=log)
        log(f"📚 Checking duplicates against {count} entries in {index.files} files.")
    else:
        log("⚠️  No --against bibliography given: duplicates are only checked against the output.")

    old_text = read_bib(output) if output.exists() else ""
    if old_text:
        index.add_text(old_text, str(output))

    added: List[Tuple[str, str]] = []
    empty: List[Tuple[str, str, str]] = []
    duplicates: List[Tuple[str, Duplicate]] = []
    failed: List[Tuple[str, str]] = []
    proposals: List[MissingVenue] = []
    chunks: List[str] = []

    def duplicate_of(record: Record, identifier: str, title: str = "") -> bool:
        dup = index.find(doi=record.doi, arxiv_id=record.arxiv_id, title=title or record.fields.get("title", ""))
        if dup is None:
            return False
        hint = ""
        if record.entry_type != "misc" and dup.reason.startswith("same arXiv"):
            hint = " (the bibliography has the preprint; `bibcc upgrade` can replace it)"
        log(f"   ⏭️  Already present as {dup.key} ({dup.where}): {dup.reason}{hint}")
        duplicates.append((identifier, dup))
        return True

    for n, identifier in enumerate(identifiers):
        if n and delay:
            time.sleep(delay)
        log(f"\n🔎 {identifier}")
        kind, value = parse_identifier(identifier)
        dup = index.find(doi=value if kind == "doi" else "", arxiv_id=value if kind == "arxiv" else "")
        if dup:
            log(f"   ⏭️  Already present as {dup.key} ({dup.where}): {dup.reason}")
            duplicates.append((identifier, dup))
            continue

        record, lookup, error = _locate(identifier, library, prefer_published, log)
        if record is None or lookup is None:
            log(f"   ❌ {error}")
            failed.append((identifier, error or "not found"))
            continue
        if duplicate_of(record, identifier):
            continue
        notes = [note for note in record.notes if not note.startswith("booktitle ")]

        if lookup.official is None:
            if lookup.error:
                log(f"   ❌ could not get the official BibTeX: {lookup.error} (nothing written; try again later)")
                failed.append((identifier, lookup.error))
                continue
            key = suggest_key(record.entry_type, record.fields, index.keys)
            entry_text = empty_entry(record.entry_type, key, record, lookup)
            log(f"   📭 no official BibTeX ({lookup.reason}); empty entry {key} to fill in by hand")
            if lookup.manual_url:
                log(f"      get it from {lookup.manual_url}")
            empty.append((identifier, key, lookup.reason))
            index.add({"ID": key, "title": record.fields.get("title", ""), "doi": record.doi,
                       "eprint": record.arxiv_id}, str(output))
        else:
            official = lookup.official
            built = build_entry(official, library, keep_title=keep_title, doi=record.doi)
            other = record_from_official(official)
            if other and (other.doi != record.doi or other.fields.get("title") != record.fields.get("title")):
                if duplicate_of(other, identifier):
                    continue
            key = suggest_key(built.entry_type, built.fields, index.keys)
            entry_text = format_entry(built.entry_type, key, built.fields)
            log(f"   ✅ official BibTeX from {official.provider}: {key}")
            if lookup.reason:
                notes.append(lookup.reason)
            notes.extend(built.notes)
            proposals.extend(venue_proposals(built, official, library, key, record))
            index.add({"ID": key, **built.fields, "eprint": record.arxiv_id}, str(output))
        try:
            _check_entry(entry_text, key)
        except BibEditError as e:
            log(f"   ❌ {e}")
            failed.append((identifier, str(e)))
            continue
        for note in notes:
            log(f"   ℹ️  {note}")
        log("\n".join("   " + line for line in entry_text.splitlines()))
        added.append((identifier, key))
        chunks.append(entry_text)

    if chunks and not dry_run:
        new_text = old_text.rstrip()
        new_text = (new_text + "\n\n" if new_text else "") + "\n\n".join(chunks) + "\n"
        old_keys = [e.key for e in scan(old_text)] if old_text else []
        if [e.key for e in scan(new_text)] != old_keys + [k for _, k in added]:
            raise BibEditError("appending changed the existing entries of the output file")
        output.parent.mkdir(parents=True, exist_ok=True)
        write_bib(output, new_text)

    yaml_path = get_output_dir(output, report_dir) / f"{output.name}.missing_venues.yaml"
    if proposals and not dry_run:
        rerun = f"bibcc complete {output} --in-place --update-venues"
        counts = write_missing_venues(yaml_path, proposals, library, rerun)
        log(f"\n📝 {counts['new']} venues missing from the library proposed in {yaml_path}")

    log(f"\n{SEPARATOR_THIN * SEPARATOR_WIDTH}")
    target = "(dry run, nothing written)" if dry_run else f"to {output}"
    log(
        f"Added {len(added)} {target} ({len(empty)} empty, to fill in by hand); "
        f"{len(duplicates)} already present; {len(failed)} failed."
    )
    if added and not dry_run:
        log("💡 Review the keys (METHOD is a guess), then run:")
        if empty:
            log(f"   fill in the {len(empty)} empty entries (each has a comment saying where to get its BibTeX)")
        log(f"   bibcc check {output} --check-keys --title-case --quote")
        log(f"   bibcc complete {output}")
    return {"added": added, "empty": empty, "duplicates": duplicates, "failed": failed}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=f"""\
Fetch papers by DOI, arXiv ID or URL, paper page URL, or title, and append
their official BibTeX to a staging file ({DEFAULT_OUTPUT} by default). Review
the entries there, then move them into your topic files.

The paper is located through CrossRef (DOIs), arXiv (arXiv IDs), and, for
titles, Semantic Scholar, OpenReview, CrossRef, and arXiv; a title only
counts as found when it matches exactly (ignoring case and punctuation). For
arXiv papers the published version is used when one exists (pass --preprint
to keep the arXiv entry). The entry itself is the official BibTeX of the
publisher or proceedings site:

  IEEE Xplore      CVPR, ICCV, WACV and their workshops, IEEE journals
  Springer         ECCV, Springer and Nature journals
  PMLR             ICML, CoLLAs, and other PMLR volumes
  proceedings      NeurIPS (proceedings.neurips.cc), ICLR from 2024 (proceedings.iclr.cc)
  OpenReview       ICLR up to 2023
  ACL Anthology, IJCAI, arXiv (preprints)

CVPR, ICCV, and WACV papers not in IEEE Xplore yet get the CVF Open Access
BibTeX, and NeurIPS, ICLR, and ICML papers not in the proceedings yet the
OpenReview BibTeX; 'bibcc upgrade' replaces these later. When no official
BibTeX can be downloaded (AAAI, ACM, and Elsevier block it; ECCV papers not
on SpringerLink yet), an empty entry is written with a comment giving the
title, DOI, reason, and where to get the BibTeX by hand.

Each entry is formatted like the rest of the bibliography: Title Case,
{{braces}} around acronyms and technical terms, -- page ranges, month macros,
no abstract or keywords, venue fields the official BibTeX lacks added from
the venue library (differences are reported, never overwritten), and a
suggested METHOD_AUTHOR_VENUEYEAR key (check the METHOD part). Venues missing
from the library are proposed in a fill-in YAML. Papers already in the
--against files or in the staging file (same DOI, arXiv ID, or title,
including empty entries) are skipped.""",
        epilog=epilog(
            examples=[
                ("a DOI and an arXiv ID, skipping papers already in bib/",
                 "bibcc add 10.1109/TPAMI.2024.3429383 2501.13198 --against bib/"),
                ("a paper by its title (quote it)",
                 'bibcc add "SD-LoRA: Scalable Decoupled Low-Rank Adaptation for Class '
                 'Incremental Learning"'),
                ("a paper page (IEEE Xplore, CVF, PMLR, NeurIPS, ICLR, ACL, IJCAI)",
                 "bibcc add https://proceedings.mlr.press/v235/abad-rocamora24a.html"),
                ("many papers from a file, one identifier per line",
                 "bibcc add --from new_papers.txt --against bib/ --output new.bib"),
                ("print the entries without writing anything", "bibcc add 2501.13198 --dry-run"),
            ],
            outputs=[
                ("<output>", f"staging file the new entries are appended to (default: {DEFAULT_OUTPUT})"),
                (".bibcc/<output>.missing_venues.yaml", "fill-in records for venues not in the library"),
                (".bibcc/logs/<output>.adder.log", "everything printed to the terminal"),
            ],
            exit_status="0 if every paper was added (possibly as an empty entry) or skipped as a\n"
            "duplicate, 1 if any lookup or download failed (try again later) or the staging\n"
            "file could not be written safely, 2 on usage errors.",
            env=[ENV_S2, ENV_VENUES],
        ),
        formatter_class=HelpFormatter,
    )
    parser.add_argument(
        "identifiers",
        nargs="*",
        metavar="IDENTIFIER",
        help="A DOI (10.xxxx/...), an arXiv ID or URL (2501.13198, arxiv.org/abs/...), "
        "a paper page URL, or a quoted title.",
    )
    parser.add_argument(
        "--from",
        dest="from_file",
        default="",
        metavar="FILE",
        help="Read more identifiers from FILE, one per line ('#' starts a comment).",
    )
    parser.add_argument(
        "--against",
        action="append",
        default=[],
        metavar="PATH",
        help="Existing .bib file or directory (searched recursively) to check for "
        "duplicates. Repeatable.",
    )
    parser.add_argument(
        "--output",
        default=DEFAULT_OUTPUT,
        metavar="FILE",
        help=f"Staging .bib file new entries are appended to (default: {DEFAULT_OUTPUT}).",
    )
    parser.add_argument(
        "--venues",
        default="",
        metavar="FILE",
        help=VENUES_HELP,
    )
    parser.add_argument(
        "--preprint",
        action="store_true",
        help="Keep arXiv papers as preprints (arXiv's BibTeX) instead of looking for a "
        "published version.",
    )
    parser.add_argument(
        "--keep-title",
        action="store_true",
        help="Do not title-case official titles (term protection still applies).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the entries without writing the staging file or the missing-venues YAML.",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=1.0,
        metavar="SECONDS",
        help="Seconds to wait between papers, to respect API rate limits (default: 1).",
    )
    parser.add_argument(
        "--log-dir",
        default="",
        metavar="DIR",
        help="Directory for the log and the missing-venues YAML (default: .bibcc/ next to "
        "the staging file).",
    )
    return parser


def run(args: argparse.Namespace) -> None:
    identifiers = list(args.identifiers)
    if args.from_file:
        identifiers += read_identifiers(args.from_file)
    if not identifiers:
        build_parser().error("give at least one identifier or --from FILE")

    log_dir = Path(args.log_dir) if args.log_dir else None
    with Logger("adder", input_file=args.output, log_dir=log_dir) as logger:
        library = load_library(args.venues or None, start=args.output)
        logger.log(f"📦 Venue library: {library.describe()}")
        try:
            summary = add_papers(
                identifiers,
                args.output,
                library,
                against=args.against,
                prefer_published=not args.preprint,
                keep_title=args.keep_title,
                dry_run=args.dry_run,
                delay=args.delay,
                log=logger.log,
                report_dir=log_dir,
            )
        except BibEditError as e:
            logger.log(f"❌ Could not write {args.output} safely: {e}")
            sys.exit(1)
    if summary["failed"]:
        sys.exit(1)


if __name__ == "__main__":
    run(build_parser().parse_args())
