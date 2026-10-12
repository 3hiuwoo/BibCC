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

``--fallback`` builds the entry from the metadata the paper was located by
instead (``missing``: when no official BibTeX can be had; ``all``: also when
the official site cannot be reached).  Such entries carry a comment that
``bibcc upgrade`` looks for, to replace them with the official BibTeX later.
Each identifier's outcome goes to ``.bibcc/<output>/add.txt`` (its ``next``
column says what to do next), and the papers left to do are listed at the end
of the log, grouped by that column.

Papers already present in the ``--against`` bibliography or the staging
file (same DOI, arXiv ID, or title, including empty entries) are skipped.
Venues missing from the library are proposed in
``.bibcc/<output>/missing_venues.yaml`` (merged on every run).

New entries are appended to the staging file only; move them into the
topic files yourself after reviewing them.

Usage:
    bibcc add 10.1109/TPAMI.2024.3429383 2501.13198 --against bib/
    bibcc add --from new_papers.txt --against bib/ --output added.bib
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional, Set, Tuple

import bibtexparser

from bibcc.bibedit import BibEditError, month_macro, page_range, read_bib, scan, write_bib
from bibcc.checkers.citation_keys import abbreviate_venue, first_author_surname
from bibcc.checkers.smart_protection import (
    MIN_TERM_LENGTH,
    _classify_word,
    find_unprotected_terms,
    protect_terms,
)
from bibcc.completer import EntryCompletion, complete_entry
from bibcc.crosscheck import venue_fields_from_crossref
from bibcc.helptext import ENV_S2, ENV_VENUES, VENUES_HELP, HelpFormatter, epilog
from bibcc.logging_utils import SEPARATOR_THIN, SEPARATOR_WIDTH, Logger, write_report
from bibcc.logging_utils import report_dir as reports_for
from bibcc.missing_venues import JOURNAL_FIELDS, PROCEEDINGS_FIELDS, MissingVenue, update_command, write_missing_venues
from bibcc.official import (
    NEXT_BY_HAND,
    NEXT_CHECK,
    NEXT_RETRY,
    NEXT_WAIT,
    Official,
    OfficialLookup,
    family_of,
    find_official,
    interim_source_of,
    next_for_error,
    next_step,
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

# Official BibTeX fields that may hold a bare & % # _ or a unicode dash.
_TEXT_FIELDS = ("title", "journal", "booktitle", "publisher", "series", "venue")
# Header of the comment written above an empty entry; BibIndex reads the lines after it.
EMPTY_ENTRY_MARK = "% BibCC: no official BibTeX"
# Header of the comment written above an entry built from metadata; `bibcc upgrade` looks for it.
METADATA_MARK = "% BibCC: not the official BibTeX"

# --fallback levels, each covering more than the one before.
FALLBACK_NONE = "none"  # official BibTeX only: empty entries and failures
FALLBACK_MISSING = "missing"  # metadata entries when no official BibTeX can be had
FALLBACK_ALL = "all"  # ... and when the official site cannot be reached
FALLBACK_LEVELS = (FALLBACK_NONE, FALLBACK_MISSING, FALLBACK_ALL)


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


def suggest_key(
    entry_type: str,
    fields: Dict[str, str],
    taken: Set[str],
    method: str = "",
    venue: str = "",
    year: str = "",
) -> str:
    """``METHOD_AUTHOR_VENUEYEAR``, made unique against *taken* (lower-cased keys).

    *method*, *venue*, and *year* (from a manifest) replace the guessed parts;
    *year* is the edition year, which may differ from the entry's ``year``.
    """
    method = re.sub(r"[^A-Za-z0-9+\-]", "", method) or suggest_method(fields.get("title", ""))
    author = first_author_surname(fields.get("author", "")) or "Anon"
    venue = re.sub(r"[^A-Za-z0-9\-]", "", re.sub(r"[\s_'-]*(?:19|20)\d{2}$", "", venue.strip()))
    if not venue and entry_type == "misc" and fields.get("archiveprefix", "").lower() == "arxiv":
        venue = "arXiv"
    elif not venue:
        venue = abbreviate_venue(fields.get("journal") or fields.get("booktitle")) or "Venue"
    year = year.strip() or fields.get("year", "")
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


def _mark_offset(text: str, start: int, mark: str = EMPTY_ENTRY_MARK) -> Optional[int]:
    """Offset of the *mark* line in the comment block above the entry at *start*.

    Other comment lines (a ``% TODO`` note, say) may come before it.
    """
    block_start, _ = _comment_above(text, start)
    region = text[block_start:start]
    i = region.find(mark)
    if i < 0:
        return None
    return block_start + region.rfind("\n", 0, i) + 1


def _empty_entry_info(text: str, start: int) -> Dict[str, str]:
    """``title``/``doi``/``arxiv`` from the BibCC comment above an empty entry."""
    mark = _mark_offset(text, start)
    if mark is None:
        return {}
    info = {}
    for line in text[mark:start].splitlines()[1:]:
        m = re.match(r"^\s*%\s+(title|doi|arxiv):\s*(.+?)\s*$", line)
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
        # Lower-cased keys of BibCC's empty entries, and the file each is in.
        self.empty: Dict[str, str] = {}
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
            self.empty[span.key.lower()] = where
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


def _normalize_word_braces(title: str) -> str:
    """Normalize braces inside words: one group per word or per protected part.

    A hyphenated or slashed compound whose parts all need protection gets a
    single group, so ``{SD}-Lo{RA}`` becomes ``{SD-LoRA}``.  When only some
    parts need it, those parts keep their own groups, so ``{CIP}-Net`` stays
    as is and ``{SD}-Lo{RA}-Net`` becomes ``{SD-LoRA}-Net``.  Words without a
    separator get one group (``{GPT}s`` → ``{GPTs}``).  Fully braced words and
    words with LaTeX commands are left alone.
    """
    words = []
    for word in title.split(" "):
        core = word.rstrip(":,;.!?")
        tail = word[len(core):]
        if (
            not _PARTLY_BRACED.match(core)
            or _FULLY_BRACED.match(core)
        ):
            words.append(word)
            continue
        if "-" not in core and "/" not in core:
            words.append("{" + core.replace("{", "").replace("}", "") + "}" + tail)
            continue
        orig_tokens = re.split(r"([-/])", core)
        plain_tokens = [t.replace("{", "").replace("}", "") for t in orig_tokens]
        needs = [
            "{" in o or "}" in o or bool(_classify_word(p, MIN_TERM_LENGTH))
            for o, p in zip(orig_tokens, plain_tokens)
        ]
        parts = [i for i, t in enumerate(plain_tokens) if t not in ("-", "/")]
        if all(needs[i] for i in parts):
            words.append("{" + "".join(plain_tokens) + "}" + tail)
            continue
        out, i, n = [], 0, len(plain_tokens)
        while i < n:
            if needs[i] and plain_tokens[i] not in ("-", "/"):
                j = i
                while j + 2 < n and needs[j + 2]:
                    j += 2
                out.append("{" + "".join(plain_tokens[i : j + 1]) + "}")
                i = j + 1
            else:
                out.append(plain_tokens[i])
                i += 1
        words.append("".join(out) + tail)
    return " ".join(words)


def polish_fields(fields: Dict[str, str], keep_title: bool = False) -> Dict[str, str]:
    """Official BibTeX values in the survey's style (Title Case, protected terms, escapes)."""
    out = {k: _texify(v) if k in _TEXT_FIELDS else v for k, v in fields.items() if v}
    title = _normalize_word_braces(out.get("title", "").rstrip("."))
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
    """An entry made from official BibTeX (or, as a fallback, API metadata), ready to format."""

    entry_type: str
    fields: Dict[str, str]
    notes: List[str] = field(default_factory=list)
    # The library match, and the venue name and year as in the source.
    completion: Optional[EntryCompletion] = None
    venue_name: str = ""
    year: str = ""
    # The source's fields before polishing, and where they came from.
    raw: Dict[str, str] = field(default_factory=dict)
    source_label: str = "official BibTeX"


def _complete_built(built: BuiltEntry, library: VenueLibrary, interim_provider: str = "",
                    library_wins: bool = False) -> BuiltEntry:
    """Add the library's venue fields to *built* and note what differs.

    The source's values are kept on conflicts, unless *library_wins*: API
    metadata is less reliable than the user's library, so for entries built
    from it the library's venue name and fields replace the metadata's.
    """
    fields, raw, venue_name = built.fields, built.raw, built.venue_name
    done = complete_entry({"ID": "", "ENTRYTYPE": built.entry_type, **raw}, library)
    built.completion = done
    source = "official" if not library_wins else "metadata"
    if done.status == "matched" and done.venue is not None:
        for name, value in done.patch.items():
            fields.setdefault(name, value)
        for name, existing, value in done.conflicts:
            if library_wins:
                fields[name] = value
                built.notes.append(f"{name}: metadata '{existing}' replaced by the venue library's '{value}'")
            else:
                built.notes.append(f"{name}: {source} '{existing}' kept; the venue library has '{value}'")
        if library_wins and not done.interim_source:
            name_field = "journal" if done.kind == JOURNAL else "booktitle"
            if fields.get(name_field) and normalize_venue(venue_name) != normalize_venue(done.venue.name):
                fields[name_field] = done.venue.name
                built.notes.append(f"{name_field}: metadata '{venue_name}' replaced by the library's name")
        if done.interim_source and not interim_provider:
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
    if interim_provider and done.interim_source and done.venue is not None:
        built.notes.append(
            f"interim BibTeX from {interim_provider}: the paper was not found in '{done.venue.name}' "
            "(the published proceedings); `bibcc upgrade` can try again later"
        )
    elif interim_provider:
        built.notes.append(
            f"interim BibTeX from {interim_provider}: the proceedings are not out yet; "
            "`bibcc upgrade` replaces it once they are"
        )
    return built


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
    built = BuiltEntry(
        entry_type,
        polish_fields(raw, keep_title=keep_title),
        venue_name=raw.get("booktitle") or raw.get("journal") or "",
        year=raw.get("year", ""),
        raw=raw,
    )
    interim = official.provider if official.interim else ""
    return _complete_built(built, library, interim_provider=interim)


def build_metadata_entry(record: Record, library: VenueLibrary, keep_title: bool = False) -> BuiltEntry:
    """Entry fields from the metadata a paper was located by (CrossRef, Semantic Scholar, ...).

    The fallback when no official BibTeX is available: formatted like an
    official entry and completed from the venue library, whose venue name
    and fields win over the metadata's.
    """
    raw = {name: " ".join(value.split()) for name, value in record.fields.items() if value and value.strip()}
    doi = normalize_doi(record.doi or raw.get("doi", ""))
    if doi and not is_arxiv_doi(doi):
        raw["doi"] = doi
    if raw.get("pages"):
        raw["pages"] = page_range(raw["pages"])
    built = BuiltEntry(
        record.entry_type,
        polish_fields(raw, keep_title=keep_title),
        venue_name=raw.get("booktitle") or raw.get("journal") or "",
        year=raw.get("year", ""),
        raw=raw,
        source_label=f"{record.source} metadata",
    )
    return _complete_built(built, library, library_wins=True)


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
    official: Optional[Official],
    library: VenueLibrary,
    key: str,
    record: Optional[Record] = None,
) -> List[MissingVenue]:
    """Missing-venue records suggested by one new entry (empty if the library has its venue).

    *official* is None for an entry built from metadata.
    """
    done = built.completion
    if done is None or done.status != "missing" or not built.venue_name:
        return []
    names = JOURNAL_FIELDS if done.kind == JOURNAL else PROCEEDINGS_FIELDS
    raw = built.raw
    proposal = MissingVenue(
        done.kind,
        built.venue_name,
        built.year,
        collected={n: raw[n] for n in names if raw.get(n)},
        collected_label=f"from {built.source_label}",
    )
    if record is not None and record.source.startswith("CrossRef"):
        proposal.crossref = venue_fields_from_crossref(record, done.kind)
    if official is not None and official.interim:
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


def _safe_comment(text: str) -> str:
    # '@' in a comment line would start an entry for some parsers.
    return " ".join(text.replace("@", "(at)").split())


def metadata_entry(built: BuiltEntry, key: str, record: Record, lookup: OfficialLookup) -> str:
    """An entry built from metadata, under a comment that marks it for ``bibcc upgrade``."""
    lines = [f"{METADATA_MARK}; it was built from metadata. "
             "`bibcc upgrade` replaces it once the official BibTeX can be downloaded."]
    lines.append(f"%   source: {_safe_comment(record.source)}")
    lines.append(f"%   reason: {_safe_comment(lookup.error or lookup.reason or 'no official BibTeX source is known')}")
    if lookup.manual_url:
        lines.append(f"%   get it: {lookup.manual_url}")
    lines.append(format_entry(built.entry_type, key, built.fields))
    return "\n".join(lines)


def _comment_above(text: str, start: int) -> Tuple[int, List[str]]:
    """Offset and lines of the ``%`` comment lines directly above the entry at *start*."""
    block_start = text.rfind("\n", 0, start) + 1
    lines: List[str] = []
    while block_start > 0:
        line_start = text.rfind("\n", 0, block_start - 1) + 1
        line = text[line_start:block_start - 1]
        if not line.strip().startswith("%"):
            break
        lines.insert(0, line.strip())
        block_start = line_start
    return block_start, lines


def metadata_keys(text: str) -> Set[str]:
    """Keys of the entries in *text* that ``bibcc add`` built from metadata."""
    keys = set()
    for span in scan(text):
        if _mark_offset(text, span.start, METADATA_MARK) is not None:
            keys.add(span.key)
    return keys


def drop_metadata_comment(text: str, key: str) -> str:
    """*text* without the metadata comment above entry *key* (once it is official BibTeX)."""
    for span in scan(text):
        if span.key != key:
            continue
        mark = _mark_offset(text, span.start, METADATA_MARK)
        if mark is not None:
            return text[:mark] + text[text.rfind("\n", 0, span.start) + 1:]
    return text


def empty_entry(entry_type: str, key: str, record: Record, lookup: OfficialLookup) -> str:
    """An entry with no fields, under a comment saying what to paste and where to get it."""
    safe = _safe_comment
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


MANIFEST_COLUMNS = ("identifier", "method", "venue", "year", "key")
# In a local .bib file, the comment line that names where an entry's official BibTeX came from.
_SOURCE_LINE = re.compile(r"^%\s*source:\s*(\S+)\s*$")
_LOCAL_LABEL = re.compile(r"^(.+\.bib):([^:/\s]+)$", re.IGNORECASE)


@dataclass(frozen=True)
class Hints:
    """What a manifest row says about one paper: parts of its key, and its venue."""

    method: str = ""
    venue: str = ""
    year: str = ""
    key: str = ""


NO_HINTS = Hints()


@dataclass
class _Item:
    """One paper to add: an identifier to look up, or an entry of a local .bib file."""

    identifier: str
    hints: Hints = NO_HINTS
    local: Optional[Official] = None
    local_key: str = ""
    # The empty entry to fill, when it is known before the lookup (--retry).
    target: str = ""


def read_identifiers(path: str | Path) -> List[str]:
    """One identifier per line; blank lines and ``#`` comments are ignored."""
    lines = Path(path).read_text(encoding="utf-8").splitlines()
    return [line.strip() for line in lines if line.strip() and not line.lstrip().startswith("#")]


def read_manifest(path: str | Path) -> List[Tuple[str, Hints]]:
    """Rows of a CSV (or ``.tsv``) manifest with an ``identifier`` column.

    The optional ``method``, ``venue``, ``year``, and ``key`` columns set the
    key: ``key`` as given, or ``METHOD_Surname_VENUEYEAR`` from the columns
    that are filled in, guessing the rest.  Raises ``ValueError`` when there
    is no ``identifier`` column.
    """
    path = Path(path)
    delimiter = "\t" if path.suffix.lower() == ".tsv" else ","
    with path.open(encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f, delimiter=delimiter)
        columns = {(name or "").strip().lower(): name for name in reader.fieldnames or []}
        if "identifier" not in columns:
            found = ", ".join(c for c in columns if c) or "none"
            raise ValueError(f"{path} has no 'identifier' column (its columns: {found})")
        rows: List[Tuple[str, Hints]] = []
        for row in reader:
            cells = {name: " ".join((row.get(columns[name]) or "").split()) if name in columns else ""
                     for name in MANIFEST_COLUMNS}
            if cells["identifier"] and not cells["identifier"].startswith("#"):
                rows.append((cells["identifier"], Hints(cells["method"], cells["venue"], cells["year"], cells["key"])))
    return rows


def read_batch(path: str | Path) -> List[Tuple[str, Hints]]:
    """Identifiers and hints from ``--from FILE``: a manifest if it is ``.csv`` or ``.tsv``."""
    if Path(path).suffix.lower() in (".csv", ".tsv"):
        return read_manifest(path)
    return [(identifier, Hints()) for identifier in read_identifiers(path)]


def is_local_bib(identifier: str) -> bool:
    """True if *identifier* is a ``.bib`` file or a directory on disk."""
    path = Path(identifier).expanduser()
    return path.is_dir() or (path.suffix.lower() == ".bib" and path.is_file())


def local_entries(identifier: str, log: Callable[[str], None]) -> List[Tuple[str, str, Official]]:
    """``(label, key, official)`` for each entry with fields in a local ``.bib`` file or directory.

    Such BibTeX is official BibTeX that you got yourself (from a browser,
    say).  A ``% source: URL`` line in the comment just above an entry names
    where it came from.
    """
    path = Path(identifier).expanduser()
    if path.is_dir():
        files = sorted(
            p for p in path.rglob("*.bib") if not any(part.startswith(".") for part in p.relative_to(path).parts)
        )
    else:
        files = [path]
    found: List[Tuple[str, str, Official]] = []
    for file in files:
        try:
            text = read_bib(file)
            spans = scan(text)
        except (BibEditError, OSError, UnicodeDecodeError) as e:
            log(f"⚠️  Could not read {file}: {e}")
            continue
        for span in spans:
            if not span.fields:
                continue
            _, comment = _comment_above(text, span.start)
            url = next((m.group(1) for m in map(_SOURCE_LINE.match, comment) if m), "")
            entry_text = text[span.start:span.end]
            _, raw = official_fields(entry_text)
            interim = interim_source_of(raw.get("booktitle", ""), url, raw.get("year", ""))
            official = Official(f"local file {file.name}", url, entry_text, interim=interim)
            found.append((f"{file}:{span.key}", span.key, official))
    return found


def retry_items(output: Path, report_dir: Optional[Path]) -> List[_Item]:
    """The papers ``--retry`` looks up again: the empty entries of *output*, and the failed papers of its report."""
    items: List[_Item] = []
    if output.exists():
        text = read_bib(output)
        for span in scan(text):
            if span.fields:
                continue
            info = _empty_entry_info(text, span.start)
            identifier = info.get("doi") or info.get("arxiv") or info.get("title")
            if identifier:
                items.append(_Item(identifier, target=span.key))
    report = reports_for(output, report_dir, create=False) / "add.txt"
    if report.exists():
        for line in report.read_text(encoding="utf-8").splitlines()[1:]:
            cells = line.split("\t")
            if len(cells) < 2 or cells[1] != "failed" or not cells[0]:
                continue
            local = _LOCAL_LABEL.match(cells[0])
            if local and Path(local.group(1)).exists():
                continue  # BibTeX in your own file that did not parse; fix the file and pass it again
            items.append(_Item(cells[0], target=cells[2] if len(cells) > 2 else ""))
    return items


def fill_empty_entry(text: str, key: str, entry_text: str) -> str:
    """*text* with the empty entry *key*, and BibCC's comment above it, replaced by *entry_text*.

    *entry_text* must keep the key.  Raises :class:`BibEditError` unless the
    keys stay in order, the new entry parses, and every other entry is
    unchanged.
    """
    spans = scan(text)
    matches = [s for s in spans if s.key == key]
    if len(matches) != 1 or matches[0].fields:
        raise BibEditError(f"expected one empty entry '{key}'")
    span = matches[0]
    mark = _mark_offset(text, span.start)
    start = span.start if mark is None else mark
    new_text = text[:start] + entry_text.strip() + text[span.end:]
    if [s.key for s in scan(new_text)] != [s.key for s in spans]:
        raise BibEditError("filling the empty entry changed the sequence of citation keys")
    parser = bibtexparser.bparser.BibTexParser(common_strings=True)
    before = {e["ID"]: e for e in bibtexparser.loads(text, parser=parser).entries if e["ID"] != key}
    parser = bibtexparser.bparser.BibTexParser(common_strings=True)
    after = {e["ID"]: e for e in bibtexparser.loads(new_text, parser=parser).entries}
    if key not in after:
        raise BibEditError(f"the entry that fills '{key}' does not parse")
    after.pop(key)
    if before != after:
        raise BibEditError(f"filling '{key}' changed other entries")
    return new_text


def entry_counts(text: str) -> Tuple[int, int]:
    """``(populated, empty)`` entries in a .bib text; empty ones are placeholders with no fields."""
    spans = scan(text) if text else []
    empty = sum(1 for s in spans if not s.fields)
    return len(spans) - empty, empty


def _check_entry(text: str, key: str) -> None:
    spans = scan(text)
    if [e.key for e in spans] != [key]:
        raise BibEditError(f"generated entry '{key}' does not parse back")
    if spans[0].fields:
        parser = bibtexparser.bparser.BibTexParser(common_strings=True)
        entries = bibtexparser.loads(text, parser=parser).entries
        if [e["ID"] for e in entries] != [key]:
            raise BibEditError(f"generated entry '{key}' does not parse back")


def _hint_venue(record: Record, hints: Hints) -> None:
    """Let a manifest's venue stand in for a record that names none, so its official source is found."""
    if not hints.venue or record.extra.get("venue_abbrev"):
        return
    if record.fields.get("booktitle") or record.fields.get("journal"):
        return
    m = re.match(r"^(.*?)[\s_'-]*((?:19|20)\d{2})?$", hints.venue.strip())
    abbrev = re.sub(r"[^A-Za-z0-9\-]", "", m.group(1) if m else hints.venue)
    if abbrev:
        record.extra["venue_abbrev"] = abbrev
        year = hints.year or (m.group(2) if m and m.group(2) else "")
        if year:
            record.extra["venue_year"] = year


def _locate(
    identifier: str,
    library: VenueLibrary,
    prefer_published: bool,
    log: Callable[[str], None],
    hints: Hints = NO_HINTS,
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
    _hint_venue(result.record, hints)
    log(f"   📍 {result.record.source}; looking for the official BibTeX...")
    return result.record, find_official(result.record), None


@dataclass
class AddOutcome:
    """What happened to one identifier; a row of ``.bibcc/<output>/add.txt``."""

    identifier: str
    status: str  # official, interim, metadata, empty, failed, or duplicate
    key: str = ""
    title: str = ""
    detail: str = ""
    url: str = ""
    # For an empty entry or a failed download: the --fallback level that builds an entry instead.
    fallback: str = ""
    # What to do next (one of the NEXT_* values of bibcc.official), or "" when nothing is left to do.
    next: str = ""

    def row(self) -> str:
        cells = (self.identifier, self.status, self.key, self.title, self.detail, self.url, self.next)
        return "\t".join(" ".join(c.split()) for c in cells)


REPORT_HEADER = "add: identifier\tstatus\tkey\ttitle\tdetail\tget it\tnext"
LEFT_TO_DO = ("empty", "failed")
# The groups of the list at the end of the log, in order: (next, heading).
_LEFT_TO_DO_GROUPS = (
    (NEXT_BY_HAND, "By hand now: get the official BibTeX from the URL"),
    (NEXT_RETRY, "Retry later: a site could not be reached"),
    (NEXT_CHECK, "Check the identifier"),
    (NEXT_WAIT, "Wait for the publisher: there's no official BibTeX yet"),
)


def _use_metadata(lookup: OfficialLookup, fallback: str) -> bool:
    """Whether *fallback* builds an entry from metadata for this failed lookup."""
    if lookup.official is not None:
        return False
    if lookup.error:
        return fallback == FALLBACK_ALL
    return fallback in (FALLBACK_MISSING, FALLBACK_ALL)


def _log_left_to_do(outcomes: List[AddOutcome], report: Path, output: Path, log: Callable[[str], None]) -> None:
    todo = [o for o in outcomes if o.status in LEFT_TO_DO]
    interim = sum(1 for o in outcomes if o.status == "interim")
    if interim:
        what = "interim entry: `bibcc upgrade OUTPUT` replaces it" if interim == 1 else \
            "interim entries: `bibcc upgrade OUTPUT` replaces them"
        log(f"\n⏳ {interim} {what.replace('OUTPUT', str(output))} once the final version is out.")
    if not todo:
        return
    log(f"\n✋ {len(todo)} left to do (also listed in {report}, with what to do in its next column):")
    for step, heading in _LEFT_TO_DO_GROUPS:
        group = [o for o in todo if (o.next or NEXT_CHECK) == step]
        if not group:
            continue
        log(f"\n   {heading} ({len(group)}):")
        for o in group:
            name = f"{o.identifier} ({o.title})" if o.title and o.title != o.identifier else o.identifier
            if o.status == "empty":
                log(f"   📭 {name}: empty entry {o.key}; paste its official BibTeX into it ({o.detail})")
            else:
                log(f"   ❌ {name}: {o.detail}")
            if o.url:
                log(f"      get it: {o.url}")
            if o.fallback:
                log(f"      or run again with --fallback {o.fallback} to build the entry from metadata")
            elif o.status == "failed" and not o.key and not o.url and not o.title:
                log("      check the identifier, or try the paper's DOI or exact title (no fallback can build "
                    "an entry for a paper that was not found)")
        if step == NEXT_RETRY:
            log(f"      to look them up again, run `bibcc add --retry --output {output}` later")
        elif step == NEXT_WAIT:
            log(f"      `bibcc add --retry --output {output}` fills them in once the proceedings are out")


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
    fallback: str = FALLBACK_NONE,
    hints: Optional[Dict[str, Hints]] = None,
    retry: bool = False,
) -> Dict[str, list]:
    """Locate *identifiers*, download their official BibTeX, and append entries to *output*.

    An identifier that is a ``.bib`` file or directory on disk brings in its
    entries as official BibTeX that you got yourself (see
    :func:`local_entries`).  *hints* (from a manifest, by identifier) set the
    parts of the key.  A paper that matches an empty entry of *output* (same
    DOI, arXiv ID, title, or manifest key) fills that entry in place and
    keeps its key; with *retry*, the empty entries of *output* and the failed
    papers of its last report are looked up again.

    *fallback* (one of :data:`FALLBACK_LEVELS`) says when an entry is built
    from the metadata the paper was located by instead: ``missing`` when no
    official BibTeX can be had (blocked publishers, unknown sources,
    proceedings not out yet), ``all`` also when the official site cannot be
    reached.  Such entries carry a :data:`METADATA_MARK` comment so ``bibcc
    upgrade`` can replace them later.  Every identifier's outcome is written
    to ``.bibcc/<output>/add.txt``, and those left to do by hand (empty
    entries, failures) are listed at the end of the log.

    Returns ``{"added": [(identifier, key)], "filled": [(identifier, key)],
    "empty": [(identifier, key, reason)], "metadata": [(identifier, key,
    reason)], "duplicates": [(identifier, Duplicate)], "failed":
    [(identifier, error)], "outcomes": [AddOutcome]}``.  Empty and metadata
    entries are also listed in ``added`` (or in ``filled``, when they fill an
    empty entry).
    """
    if fallback not in FALLBACK_LEVELS:
        raise ValueError(f"fallback must be one of {', '.join(FALLBACK_LEVELS)}, not '{fallback}'")
    log = log or print
    output = Path(output)
    hints = hints or {}
    index = BibIndex()
    if against:
        count = index.add_paths(against, exclude=output, log=log)
        log(f"📚 Checking duplicates against {count} entries in {index.files} files.")
    else:
        log("⚠️  No --against bibliography given: duplicates are only checked against the output.")

    old_text = read_bib(output) if output.exists() else ""
    if old_text:
        index.add_text(old_text, str(output))

    items: List[_Item] = retry_items(output, report_dir) if retry else []
    if retry:
        log(f"🔁 Retrying {len(items)} papers: the empty entries of {output} and the failed papers of its report.")
    for identifier in identifiers:
        hint = hints.get(identifier, NO_HINTS)
        if not is_local_bib(identifier):
            items.append(_Item(identifier, hint))
            continue
        found = local_entries(identifier, log)
        if not found:
            log(f"⚠️  {identifier}: no entries with fields to add")
        if len(found) > 1 and hint != NO_HINTS:
            log(f"⚠️  {identifier} holds {len(found)} entries, so its manifest values are ignored")
            hint = NO_HINTS
        items += [_Item(label, hint, official, key) for label, key, official in found]
    seen_ids: Set[str] = set()
    items = [i for i in items if not (i.identifier in seen_ids or seen_ids.add(i.identifier))]

    added: List[Tuple[str, str]] = []
    filled: List[Tuple[str, str]] = []
    empty: List[Tuple[str, str, str]] = []
    metadata: List[Tuple[str, str, str]] = []
    duplicates: List[Tuple[str, Duplicate]] = []
    failed: List[Tuple[str, str]] = []
    outcomes: List[AddOutcome] = []
    proposals: List[MissingVenue] = []
    chunks: List[str] = []
    fills: Dict[str, str] = {}

    def is_open_placeholder(key: str) -> bool:
        return index.empty.get(key.lower()) == str(output) and key not in fills

    def skip_duplicate(identifier: str, dup: Duplicate, hint: str = "") -> None:
        if not hint and dup.key.lower() in index.empty:
            hint = f" (an empty entry; to fill it, run again with --output {dup.where})"
        log(f"   ⏭️  Already present as {dup.key} ({dup.where}): {dup.reason}{hint}")
        duplicates.append((identifier, dup))
        outcomes.append(AddOutcome(identifier, "duplicate", dup.key, detail=f"{dup.reason} ({dup.where})"))

    def match(identifier: str, record: Record, target: str) -> Tuple[bool, str]:
        """``(skip, target)``: whether *record* is already present, and the empty entry it fills."""
        dup = index.find(doi=record.doi, arxiv_id=record.arxiv_id, title=record.fields.get("title", ""))
        if dup is None or dup.key.lower() == target.lower():
            return False, target
        if not target and is_open_placeholder(dup.key):
            return False, dup.key
        hint = ""
        if record.entry_type != "misc" and dup.reason.startswith("same arXiv"):
            hint = " (the bibliography has the preprint; `bibcc upgrade` can replace it)"
        skip_duplicate(identifier, dup, hint)
        return True, target

    def fail(identifier: str, error: str, **outcome: str) -> None:
        log(f"   ❌ {error}")
        failed.append((identifier, error))
        outcome.setdefault("next", next_for_error(error))
        outcomes.append(AddOutcome(identifier, "failed", detail=error, **outcome))

    looked_up = False
    for item in items:
        identifier, hint = item.identifier, item.hints
        target = item.target if item.target and is_open_placeholder(item.target) else ""
        if hint.key and not target:
            if is_open_placeholder(hint.key):
                target = hint.key
            elif hint.key.lower() in index.keys:
                log(f"\n🔎 {identifier}")
                fail(identifier, f"key {hint.key} from the manifest is already used in "
                     f"{index.key_where.get(hint.key.lower(), str(output))}")
                continue
        if item.local is None:
            if looked_up and delay:
                time.sleep(delay)
            looked_up = True
        log(f"\n🔎 {identifier}")

        if item.local is not None:
            if not target and item.local_key and is_open_placeholder(item.local_key):
                target = item.local_key
            lookup = OfficialLookup(official=item.local)
            record = record_from_official(item.local)
            if record is None:
                fail(identifier, "the BibTeX does not parse", key=target, url=item.local.url)
                continue
        else:
            kind, value = parse_identifier(identifier)
            dup = index.find(doi=value if kind == "doi" else "", arxiv_id=value if kind == "arxiv" else "")
            if dup and dup.key.lower() != target.lower():
                if not target and is_open_placeholder(dup.key):
                    target = dup.key
                else:
                    skip_duplicate(identifier, dup)
                    continue
            record, lookup, error = _locate(identifier, library, prefer_published, log, hint)
            if record is None or lookup is None:
                fail(identifier, error or "not found", key=target, url=value if kind == "url" else "")
                continue
        skip, target = match(identifier, record, target)
        if skip:
            continue
        title = record.fields.get("title", "")
        notes = [note for note in record.notes if not note.startswith("booktitle ")]
        fixed_key = target or hint.key
        key_parts = {"method": hint.method, "venue": hint.venue, "year": hint.year}
        if _use_metadata(lookup, fallback):
            why = lookup.error or lookup.reason or "no official BibTeX source is known"
            built = build_metadata_entry(record, library, keep_title=keep_title)
            key = fixed_key or suggest_key(built.entry_type, built.fields, index.keys, **key_parts)
            entry_text = metadata_entry(built, key, record, lookup)
            log(f"   🧩 no official BibTeX ({why}); built {key} from {record.source} metadata")
            notes = list(record.notes) + built.notes
            proposals.extend(venue_proposals(built, None, library, key, record))
            index.add({"ID": key, **built.fields, "eprint": record.arxiv_id}, str(output))
            outcome = AddOutcome(identifier, "metadata", key, title, f"built from {record.source} metadata: {why}",
                                 lookup.manual_url, next=next_step(lookup))
        elif lookup.official is None and lookup.error:
            fail(identifier, f"could not get the official BibTeX: {lookup.error} (nothing written; try again later)",
                 key=target, title=title, url=lookup.manual_url, fallback=FALLBACK_ALL, next=NEXT_RETRY)
            continue
        elif lookup.official is None and target:
            log(f"   📭 still no official BibTeX ({lookup.reason}); the empty entry {target} stays")
            if lookup.manual_url:
                log(f"      get it from {lookup.manual_url}")
            empty.append((identifier, target, lookup.reason))
            outcomes.append(AddOutcome(identifier, "empty", target, title, lookup.reason, lookup.manual_url,
                                       fallback=FALLBACK_MISSING, next=next_step(lookup)))
            continue
        elif lookup.official is None:
            key = fixed_key or suggest_key(record.entry_type, record.fields, index.keys, **key_parts)
            entry_text = empty_entry(record.entry_type, key, record, lookup)
            log(f"   📭 no official BibTeX ({lookup.reason}); empty entry {key} to fill in by hand")
            if lookup.manual_url:
                log(f"      get it from {lookup.manual_url}")
            index.add({"ID": key, "title": title, "doi": record.doi, "eprint": record.arxiv_id}, str(output))
            outcome = AddOutcome(identifier, "empty", key, title, lookup.reason, lookup.manual_url,
                                 fallback=FALLBACK_MISSING, next=next_step(lookup))
        else:
            official = lookup.official
            built = build_entry(official, library, keep_title=keep_title, doi=record.doi)
            other = record_from_official(official)
            if other and (other.doi != record.doi or other.fields.get("title") != record.fields.get("title")):
                skip, target = match(identifier, other, target)
                if skip:
                    continue
            key = fixed_key or suggest_key(built.entry_type, built.fields, index.keys, **key_parts)
            entry_text = format_entry(built.entry_type, key, built.fields)
            log(f"   ✅ official BibTeX from {official.provider}: {key}")
            if lookup.reason:
                notes.append(lookup.reason)
            notes.extend(built.notes)
            proposals.extend(venue_proposals(built, official, library, key, record))
            index.add({"ID": key, **built.fields, "eprint": record.arxiv_id}, str(output))
            detail = official.provider + (f" ({lookup.reason})" if lookup.reason else "")
            outcome = AddOutcome(identifier, "interim" if official.interim else "official", key, title, detail,
                                 official.url, next=NEXT_WAIT if official.interim else "")
        if hint.key and target and hint.key != target:
            notes.append(f"fills the empty entry {target}, which keeps its key (the manifest says {hint.key})")
        try:
            _check_entry(entry_text, key)
        except BibEditError as e:
            fail(identifier, str(e), key=target, title=title)
            continue
        for note in notes:
            log(f"   ℹ️  {note}")
        log("\n".join("   " + line for line in entry_text.splitlines()))
        if target:
            log(f"   📥 fills the empty entry {target}")
            fills[target] = entry_text
            filled.append((identifier, key))
        else:
            chunks.append(entry_text)
            added.append((identifier, key))
        if outcome.status == "empty":
            empty.append((identifier, key, outcome.detail))
        elif outcome.status == "metadata":
            metadata.append((identifier, key, lookup.error or lookup.reason))
        outcomes.append(outcome)

    new_text = old_text
    for key, entry_text in fills.items():
        new_text = fill_empty_entry(new_text, key, entry_text)
    if chunks:
        new_text = new_text.rstrip()
        new_text = (new_text + "\n\n" if new_text else "") + "\n\n".join(chunks) + "\n"
    if (chunks or fills) and not dry_run:
        old_keys = [e.key for e in scan(old_text)] if old_text else []
        if [e.key for e in scan(new_text)] != old_keys + [k for _, k in added]:
            raise BibEditError("appending changed the existing entries of the output file")
        output.parent.mkdir(parents=True, exist_ok=True)
        write_bib(output, new_text)

    output_dir = reports_for(output, report_dir)
    yaml_path = output_dir / "missing_venues.yaml"
    if proposals and not dry_run:
        rerun = update_command(output)
        counts = write_missing_venues(yaml_path, proposals, library, rerun)
        log(f"\n📝 {counts['new']} venues missing from the library proposed in {yaml_path}")
    report = output_dir / "add.txt"
    write_report(report, REPORT_HEADER, [o.row() for o in outcomes])

    log(f"\n{SEPARATOR_THIN * SEPARATOR_WIDTH}")
    target_label = "(dry run, nothing written)" if dry_run else f"to {output}"
    new_empty = sum(1 for o in outcomes if o.status == "empty" and (o.identifier, o.key) in added)
    log(
        f"Added {len(added)} {target_label} ({new_empty} empty, to fill in by hand; {len(metadata)} built from "
        f"metadata); filled {len(filled)} empty entries; {len(duplicates)} already present; "
        f"{len(failed)} failed. Report: {report}"
    )
    populated, placeholders = entry_counts(new_text)
    log(f"{output}: {populated + placeholders} entries ({populated} with fields, {placeholders} empty)"
        + (" after this run" if dry_run else ""))
    _log_left_to_do(outcomes, report, output, log)
    if (added or filled) and not dry_run:
        log("\n💡 Review the keys (METHOD is a guess unless a manifest gives it), then run:")
        if placeholders:
            log(f"   fill in the {placeholders} empty entries (each has a comment saying where to get its BibTeX), "
                f"or run `bibcc add --retry --output {output}` later")
        if metadata:
            log(f"   check the entries built from metadata ({len(metadata)}); `bibcc upgrade {output}` "
                "replaces them once their official BibTeX can be downloaded")
        log(f"   bibcc check {output} --check-keys --title-case --quote")
        log(f"   bibcc complete {output}")
    return {"added": added, "filled": filled, "empty": empty, "metadata": metadata, "duplicates": duplicates,
            "failed": failed, "outcomes": outcomes}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=f"""\
Fetch papers by DOI, arXiv ID or URL, paper page URL, or title, and append
their official BibTeX to a staging file ({DEFAULT_OUTPUT} by default). Review
the entries there, and then move them into your topic files.

The command finds the paper through CrossRef (DOIs), arXiv (arXiv IDs), and,
for titles, Semantic Scholar, OpenReview, CrossRef, and arXiv. A title counts
as found only when it matches exactly (ignoring case and punctuation). For
arXiv papers, the command uses the published version when one exists (to
keep the arXiv entry, pass --preprint). The entry itself is the official
BibTeX of the publisher or proceedings site:

  IEEE Xplore      CVPR, ICCV, WACV, and their workshops; IEEE journals
  Springer         ECCV; Springer and Nature journals
  PMLR             ICML, CoLLAs, and other PMLR volumes
  proceedings      NeurIPS (proceedings.neurips.cc), ICLR 2024 and later (proceedings.iclr.cc)
  OpenReview       ICLR 2023 and earlier
  ACL Anthology, IJCAI, and arXiv (preprints)

CVPR, ICCV, and WACV papers that aren't in IEEE Xplore yet get the CVF Open
Access BibTeX, and NeurIPS, ICLR, and ICML papers that aren't in the
proceedings yet get the OpenReview BibTeX; 'bibcc upgrade' replaces these
later.

Expect some papers to have no official BibTeX. AAAI, ACM, and Elsevier block
automated downloads, ECCV papers aren't on SpringerLink right away, and IEEE
Xplore, Springer, and the APIs rate-limit or bot-check scripted requests. By
default (--fallback none), such a paper gets an empty entry with a comment
that gives the title, DOI, reason, and where to get the BibTeX by hand. The
command doesn't write a paper whose site it can't reach (run again later).
With --fallback, the command instead builds the entry from the metadata that
it found the paper through (CrossRef, Semantic Scholar, OpenReview, or arXiv)
and completes it from the venue library:

  none     Official BibTeX only (the default)
  missing  Metadata entries when no official BibTeX is available
  all      Also when the official site can't be reached

These entries carry a comment that says so; 'bibcc upgrade' replaces them
when the official BibTeX becomes available. The command lists whatever is
left to do at the end of the run and in .bibcc/OUTPUT/add.txt, grouped by
what to do next (the next column): get the BibTeX by hand, retry later,
check the identifier, or wait until the proceedings are out.

The command formats each entry like the rest of the bibliography: Title
Case, {{braces}} around acronyms and technical terms, -- page ranges, month
macros, no abstract or keywords, venue fields that the official BibTeX lacks
added from the venue library (differences are reported, never overwritten),
and a suggested METHOD_AUTHOR_VENUEYEAR key (check the METHOD part). The
command proposes venues that are missing from the library in a fill-in YAML
file. It skips papers that are already in the --against files or in the
staging file (same DOI, arXiv ID, or title). An empty entry in another file
counts as present, but a paper that matches an empty entry of the staging file
fills that entry in place and keeps its key.

To add BibTeX that you downloaded yourself (for example, from a browser), pass
the .bib file or a directory of .bib files as an identifier. The command
treats each entry as official BibTeX: it formats the entry, checks for
duplicates, and fills a matching empty entry. A '% source: URL' comment line
just before an entry names where the entry came from.

To set the keys, pass --from with a .csv or .tsv manifest. Its 'identifier'
column is required, and the optional 'method', 'venue', 'year', and 'key'
columns give the key as METHOD_AUTHOR_VENUEYEAR or in full. A 'venue' value
also helps the command find the official source of a paper whose metadata
names no venue.

To look up again the papers that have no entry yet, pass --retry. The command
retries the empty entries of the staging file and the papers that failed in
its last report, .bibcc/OUTPUT/add.txt. The run ends with the number of
entries in the staging file, with and without fields.""",
        epilog=epilog(
            examples=[
                ("Add a DOI and an arXiv ID, and skip papers already in bib/",
                 "bibcc add 10.1109/TPAMI.2024.3429383 2501.13198 --against bib/"),
                ("Add a paper by its title (quote it)",
                 'bibcc add "SD-LoRA: Scalable Decoupled Low-Rank Adaptation for Class '
                 'Incremental Learning"'),
                ("Add a paper page (IEEE Xplore, CVF, PMLR, NeurIPS, ICLR, ACL, or IJCAI)",
                 "bibcc add https://proceedings.mlr.press/v235/abad-rocamora24a.html"),
                ("Add many papers from a file, one identifier per line",
                 "bibcc add --from new_papers.txt --against bib/ --output new.bib"),
                ("Add papers from a manifest that sets the parts of each key",
                 "bibcc add --from papers.csv --against bib/ --output new.bib"),
                ("Add BibTeX that you downloaded by hand, filling empty entries",
                 "bibcc add downloads/ --output new.bib"),
                ("Look up the empty entries and failed papers again",
                 "bibcc add --retry --output new.bib"),
                ("Build entries from metadata when no official BibTeX is available",
                 "bibcc add --from new_papers.txt --fallback all"),
                ("Print the entries without writing anything", "bibcc add 2501.13198 --dry-run"),
            ],
            outputs=[
                ("OUTPUT", f"Staging file that the command appends new entries to (default: {DEFAULT_OUTPUT})"),
                (".bibcc/OUTPUT/add.txt", "Each paper's outcome, source, and where to get its BibTeX"),
                (".bibcc/OUTPUT/missing_venues.yaml", "Fill-in records for venues that aren't in the library"),
                (".bibcc/OUTPUT/logs/adder.log", "Everything printed to the terminal"),
            ],
            exit_status="0 if the command adds every paper (possibly as an empty entry or from\n"
            "metadata) or skips it as a duplicate, 1 if a lookup or download fails and\n"
            "--fallback doesn't cover it (try again later) or if BibCC can't write the\n"
            "staging file safely, 2 on usage errors.",
            env=[ENV_S2, ENV_VENUES],
        ),
        formatter_class=HelpFormatter,
    )
    parser.add_argument(
        "identifiers",
        nargs="*",
        metavar="IDENTIFIER",
        help="A DOI (10.xxxx/...), an arXiv ID or URL (2501.13198, arxiv.org/abs/...), "
        "a paper page URL, a quoted title, or a .bib file or directory of official BibTeX.",
    )
    parser.add_argument(
        "--from",
        dest="from_file",
        default="",
        metavar="FILE",
        help="Read more identifiers from FILE, one per line ('#' starts a comment). A .csv or "
        ".tsv FILE is a manifest with an 'identifier' column and optional 'method', 'venue', "
        "'year', and 'key' columns that set the key.",
    )
    parser.add_argument(
        "--retry",
        action="store_true",
        help="Also look up the empty entries of the staging file and the papers that failed in "
        "its last report.",
    )
    parser.add_argument(
        "--against",
        action="append",
        default=[],
        metavar="PATH",
        help="An existing .bib file or directory (searched recursively) to check for "
        "duplicates. Repeatable.",
    )
    parser.add_argument(
        "--output",
        default=DEFAULT_OUTPUT,
        metavar="FILE",
        help=f"Staging .bib file to append new entries to (default: {DEFAULT_OUTPUT}).",
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
        help="Don't title-case official titles (term protection still applies).",
    )
    parser.add_argument(
        "--fallback",
        choices=FALLBACK_LEVELS,
        default=FALLBACK_NONE,
        metavar="LEVEL",
        help="When to build the entry from the metadata of the lookup source instead of from "
        "official BibTeX: 'none' (default; official BibTeX only, otherwise empty entries and "
        "failures), 'missing' (when no official BibTeX is available, such as for blocked "
        "publishers, unknown sources, and proceedings that aren't out yet), or 'all' (also "
        "when the official site can't be reached).",
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
        help="Directory to use instead of .bibcc/ next to the staging file; the log, the report, "
        "and the missing-venues YAML go to DIR/OUTPUT/.",
    )
    return parser


def run(args: argparse.Namespace) -> None:
    identifiers = list(args.identifiers)
    hints: Dict[str, Hints] = {}
    if args.from_file:
        try:
            rows = read_batch(args.from_file)
        except (OSError, ValueError) as e:
            build_parser().error(str(e))
        identifiers += [identifier for identifier, _ in rows]
        hints = {identifier: hint for identifier, hint in rows if hint != NO_HINTS}
    if not identifiers and not args.retry:
        build_parser().error("give at least one identifier, --from FILE, or --retry")

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
                fallback=args.fallback,
                hints=hints,
                retry=args.retry,
            )
        except BibEditError as e:
            logger.log(f"❌ Could not write {args.output} safely: {e}")
            sys.exit(1)
    if summary["failed"]:
        sys.exit(1)


if __name__ == "__main__":
    run(build_parser().parse_args())
