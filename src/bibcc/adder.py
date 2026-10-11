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
Each identifier's outcome goes to ``.bibcc/<output>/add.txt``, and the papers
left to do by hand are listed at the end of the log.

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
import re
import sys
import time
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional, Set, Tuple

import bibtexparser

from bibcc.bibedit import BibEditError, month_macro, page_range, read_bib, scan, write_bib
from bibcc.checkers.citation_keys import abbreviate_venue
from bibcc.checkers.smart_protection import find_unprotected_terms, protect_terms
from bibcc.completer import EntryCompletion, complete_entry
from bibcc.crosscheck import venue_fields_from_crossref
from bibcc.helptext import ENV_S2, ENV_VENUES, VENUES_HELP, HelpFormatter, epilog
from bibcc.logging_utils import SEPARATOR_THIN, SEPARATOR_WIDTH, Logger, write_report
from bibcc.logging_utils import report_dir as reports_for
from bibcc.missing_venues import JOURNAL_FIELDS, PROCEEDINGS_FIELDS, MissingVenue, update_command, write_missing_venues
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


_LATEX_LETTERS = re.compile(r"\\(ss|ae|AE|oe|OE|aa|AA|l|L|o|O|i|j)(?![A-Za-z])")
# \'e  \"{u}  {\^ o}: symbol accents, with or without braces around the letter.
_LATEX_SYMBOL_ACCENT = re.compile(r"\\['`^\"~=.]\s*(?:\{\s*([A-Za-z])\s*\}|([A-Za-z]))")
# \k{a}  \v S  \c{c}: letter accents, which need braces or a space before the letter.
_LATEX_LETTER_ACCENT = re.compile(r"\\[uvHckbdrt](?:\s*\{\s*([A-Za-z])\s*\}|\s+([A-Za-z]))")


def decode_latex_letters(text: str) -> str:
    """``Zaj\\k{a}c`` → ``Zajac``: LaTeX accents and special letters as their ASCII base letters.

    Braces are kept, so that name splitting still sees ``{...}`` groups.
    """
    text = _LATEX_LETTERS.sub(lambda m: {"ss": "ss", "aa": "a", "AA": "A"}.get(m.group(1), m.group(1)), text)
    text = _LATEX_SYMBOL_ACCENT.sub(lambda m: m.group(1) or m.group(2), text)
    return _LATEX_LETTER_ACCENT.sub(lambda m: m.group(1) or m.group(2), text)


def _ascii_name(text: str) -> str:
    text = re.sub(r"\\[a-zA-Z]+|\\.", "", decode_latex_letters(text))
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^A-Za-z'\-]", "", text)


def first_author_surname(author: str) -> str:
    """Surname of the first author, ASCII-folded, particles joined (``vandeVen``)."""
    first = decode_latex_letters(re.split(r"\s+and\s+", author.strip())[0])
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
        _, lines = _comment_above(text, span.start)
        if lines and lines[0].startswith(METADATA_MARK):
            keys.add(span.key)
    return keys


def drop_metadata_comment(text: str, key: str) -> str:
    """*text* without the metadata comment above entry *key* (once it is official BibTeX)."""
    for span in scan(text):
        if span.key != key:
            continue
        block_start, lines = _comment_above(text, span.start)
        if lines and lines[0].startswith(METADATA_MARK):
            return text[:block_start] + text[text.rfind("\n", 0, span.start) + 1:]
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

    def row(self) -> str:
        cells = (self.identifier, self.status, self.key, self.title, self.detail, self.url)
        return "\t".join(" ".join(c.split()) for c in cells)


REPORT_HEADER = "add: identifier\tstatus\tkey\ttitle\tdetail\tget it"
LEFT_TO_DO = ("empty", "failed")


def _use_metadata(lookup: OfficialLookup, fallback: str) -> bool:
    """Whether *fallback* builds an entry from metadata for this failed lookup."""
    if lookup.official is not None:
        return False
    if lookup.error:
        return fallback == FALLBACK_ALL
    return fallback in (FALLBACK_MISSING, FALLBACK_ALL)


def _log_left_to_do(outcomes: List[AddOutcome], report: Path, log: Callable[[str], None]) -> None:
    todo = [o for o in outcomes if o.status in LEFT_TO_DO]
    if not todo:
        return
    log(f"\n✋ {len(todo)} left to do by hand (also listed in {report}):")
    for o in todo:
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
) -> Dict[str, list]:
    """Locate *identifiers*, download their official BibTeX, and append entries to *output*.

    *fallback* (one of :data:`FALLBACK_LEVELS`) says when an entry is built
    from the metadata the paper was located by instead: ``missing`` when no
    official BibTeX can be had (blocked publishers, unknown sources,
    proceedings not out yet), ``all`` also when the official site cannot be
    reached.  Such entries carry a :data:`METADATA_MARK` comment so ``bibcc
    upgrade`` can replace them later.  Every identifier's outcome is written
    to ``.bibcc/<output>/add.txt``, and those left to do by hand (empty
    entries, failures) are listed at the end of the log.

    Returns ``{"added": [(identifier, key)], "empty": [(identifier, key,
    reason)], "metadata": [(identifier, key, reason)], "duplicates":
    [(identifier, Duplicate)], "failed": [(identifier, error)], "outcomes":
    [AddOutcome]}``.  Empty and metadata entries are also listed in ``added``.
    """
    if fallback not in FALLBACK_LEVELS:
        raise ValueError(f"fallback must be one of {', '.join(FALLBACK_LEVELS)}, not '{fallback}'")
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
    metadata: List[Tuple[str, str, str]] = []
    duplicates: List[Tuple[str, Duplicate]] = []
    failed: List[Tuple[str, str]] = []
    outcomes: List[AddOutcome] = []
    proposals: List[MissingVenue] = []
    chunks: List[str] = []

    def skip_duplicate(identifier: str, dup: Duplicate, hint: str = "") -> None:
        log(f"   ⏭️  Already present as {dup.key} ({dup.where}): {dup.reason}{hint}")
        duplicates.append((identifier, dup))
        outcomes.append(AddOutcome(identifier, "duplicate", dup.key, detail=f"{dup.reason} ({dup.where})"))

    def duplicate_of(record: Record, identifier: str, title: str = "") -> bool:
        dup = index.find(doi=record.doi, arxiv_id=record.arxiv_id, title=title or record.fields.get("title", ""))
        if dup is None:
            return False
        hint = ""
        if record.entry_type != "misc" and dup.reason.startswith("same arXiv"):
            hint = " (the bibliography has the preprint; `bibcc upgrade` can replace it)"
        skip_duplicate(identifier, dup, hint)
        return True

    def fail(identifier: str, error: str, **outcome: str) -> None:
        log(f"   ❌ {error}")
        failed.append((identifier, error))
        outcomes.append(AddOutcome(identifier, "failed", detail=error, **outcome))

    for n, identifier in enumerate(identifiers):
        if n and delay:
            time.sleep(delay)
        log(f"\n🔎 {identifier}")
        kind, value = parse_identifier(identifier)
        dup = index.find(doi=value if kind == "doi" else "", arxiv_id=value if kind == "arxiv" else "")
        if dup:
            skip_duplicate(identifier, dup)
            continue

        record, lookup, error = _locate(identifier, library, prefer_published, log)
        if record is None or lookup is None:
            fail(identifier, error or "not found", url=value if kind == "url" else "")
            continue
        if duplicate_of(record, identifier):
            continue
        title = record.fields.get("title", "")
        notes = [note for note in record.notes if not note.startswith("booktitle ")]

        if _use_metadata(lookup, fallback):
            why = lookup.error or lookup.reason or "no official BibTeX source is known"
            built = build_metadata_entry(record, library, keep_title=keep_title)
            key = suggest_key(built.entry_type, built.fields, index.keys)
            entry_text = metadata_entry(built, key, record, lookup)
            log(f"   🧩 no official BibTeX ({why}); built {key} from {record.source} metadata")
            notes = list(record.notes) + built.notes
            proposals.extend(venue_proposals(built, None, library, key, record))
            index.add({"ID": key, **built.fields, "eprint": record.arxiv_id}, str(output))
            outcome = AddOutcome(identifier, "metadata", key, title, f"built from {record.source} metadata: {why}",
                                 lookup.manual_url)
        elif lookup.official is None and lookup.error:
            fail(identifier, f"could not get the official BibTeX: {lookup.error} (nothing written; try again later)",
                 title=title, url=lookup.manual_url, fallback=FALLBACK_ALL)
            continue
        elif lookup.official is None:
            key = suggest_key(record.entry_type, record.fields, index.keys)
            entry_text = empty_entry(record.entry_type, key, record, lookup)
            log(f"   📭 no official BibTeX ({lookup.reason}); empty entry {key} to fill in by hand")
            if lookup.manual_url:
                log(f"      get it from {lookup.manual_url}")
            index.add({"ID": key, "title": title, "doi": record.doi, "eprint": record.arxiv_id}, str(output))
            outcome = AddOutcome(identifier, "empty", key, title, lookup.reason, lookup.manual_url,
                                 fallback=FALLBACK_MISSING)
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
            detail = official.provider + (f" ({lookup.reason})" if lookup.reason else "")
            outcome = AddOutcome(identifier, "interim" if official.interim else "official", key, title, detail,
                                 official.url)
        try:
            _check_entry(entry_text, key)
        except BibEditError as e:
            fail(identifier, str(e), title=title)
            continue
        for note in notes:
            log(f"   ℹ️  {note}")
        log("\n".join("   " + line for line in entry_text.splitlines()))
        added.append((identifier, key))
        if outcome.status == "empty":
            empty.append((identifier, key, outcome.detail))
        elif outcome.status == "metadata":
            metadata.append((identifier, key, lookup.error or lookup.reason))
        outcomes.append(outcome)
        chunks.append(entry_text)

    if chunks and not dry_run:
        new_text = old_text.rstrip()
        new_text = (new_text + "\n\n" if new_text else "") + "\n\n".join(chunks) + "\n"
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
    target = "(dry run, nothing written)" if dry_run else f"to {output}"
    log(
        f"Added {len(added)} {target} ({len(empty)} empty, to fill in by hand; {len(metadata)} built from "
        f"metadata); {len(duplicates)} already present; {len(failed)} failed. Report: {report}"
    )
    _log_left_to_do(outcomes, report, log)
    if added and not dry_run:
        log("\n💡 Review the keys (METHOD is a guess), then run:")
        if empty:
            log(f"   fill in the {len(empty)} empty entries (each has a comment saying where to get its BibTeX)")
        if metadata:
            log(f"   check the entries built from metadata ({len(metadata)}); `bibcc upgrade {output}` "
                "replaces them once their official BibTeX can be downloaded")
        log(f"   bibcc check {output} --check-keys --title-case --quote")
        log(f"   bibcc complete {output}")
    return {"added": added, "empty": empty, "metadata": metadata, "duplicates": duplicates,
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
left to do by hand at the end of the run and in .bibcc/OUTPUT/add.txt.

The command formats each entry like the rest of the bibliography: Title
Case, {{braces}} around acronyms and technical terms, -- page ranges, month
macros, no abstract or keywords, venue fields that the official BibTeX lacks
added from the venue library (differences are reported, never overwritten),
and a suggested METHOD_AUTHOR_VENUEYEAR key (check the METHOD part). The
command proposes venues that are missing from the library in a fill-in YAML
file. It skips papers that are already in the --against files or in the
staging file (same DOI, arXiv ID, or title, including empty entries).""",
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
                fallback=args.fallback,
            )
        except BibEditError as e:
            logger.log(f"❌ Could not write {args.output} safely: {e}")
            sys.exit(1)
    if summary["failed"]:
        sys.exit(1)


if __name__ == "__main__":
    run(build_parser().parse_args())
