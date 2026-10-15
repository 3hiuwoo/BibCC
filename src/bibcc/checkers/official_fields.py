"""
Compare entries with their official BibTeX, field by field.

For each entry that already has its published BibTeX, the check locates
and downloads the official BibTeX again, the same way ``bibcc add`` does
(see :mod:`bibcc.official`), or takes it from ``--local`` files that you
fetched yourself, and compares the two:

* ``upstream_only``: the official BibTeX has a field the entry lacks.
* ``differs``: both have the field, with different values (braces, case,
  whitespace, accents, and month spellings don't count).
* ``local_only``: the entry has a field the official BibTeX lacks, other
  than BibCC's ``citation`` and the fields the venue library supplies.
* ``type``: the entry types differ.

The venue summary says, for each venue and year, how many checked entries
the official BibTeX gives a field and how many of them lack it
(``entries_lack``), and compares the venue library records with the
official values (``library_lacks`` and ``library_differs``) and the
venues' schemas, the fields the official BibTeX of each paper has, with the
fields the downloaded BibTeX has (``schema_lacks`` and ``schema_differs``;
see :mod:`bibcc.schemas`).  ``bibcc check official --learn`` writes those
schemas into the venue library.

``apply`` adds the official values of the listed fields that the entries
lack.

Preprints, interim (CVF or OpenReview) entries, and entries built from
metadata are skipped: ``bibcc upgrade`` replaces them.

Usage:
    from bibcc.checkers.official_fields import check_official_fields

    result = check_official_fields("refs.bib", library, local=["exports/"])
"""

from __future__ import annotations

import time
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional, Sequence, Set, Tuple

import bibtexparser

from bibcc.bibedit import BibEditError, read_bib, set_fields, write_bib
from bibcc.logging_utils import SEPARATOR_LIGHT, SEPARATOR_WIDTH
from bibcc.missing_venues import JOURNAL_FIELDS, PROCEEDINGS_FIELDS
from bibcc.schemas import (
    IGNORED_FIELDS,
    OFFICIAL,
    SCHEMA_LACKS,
    SCHEMA_STATUSES,
    Observation,
    Proposal,
    observe,
    propose,
)
from bibcc.venues import Venue, VenueLibrary, venue_kind

UPSTREAM_ONLY = "upstream_only"
DIFFERS = "differs"
LOCAL_ONLY = "local_only"
TYPE = "type"
# Findings that `--strict` counts; local_only fields are often added on purpose.
STRICT_ISSUES = (UPSTREAM_ONLY, DIFFERS, TYPE)

ENTRIES_LACK = "entries_lack"
LIBRARY_LACKS = "library_lacks"
LIBRARY_DIFFERS = "library_differs"

APPLY_ALL = "all"

FIELDS_HEADER = "official fields: entry_id\tfield\tissue_type\tbib\tofficial\tsource"
UNCHECKED_HEADER = "official unchecked: entry_id\tstatus\tdetail\turl\tnext"
VENUES_HEADER = "official venues: venue\tyear\tfield\tissue_type\tchecked\tlacking\tdetail"

# BibCC's own field (`bibcc scholar cite`), never in official BibTeX.
_OWN_FIELDS = {"citation"}
_LIBRARY_FIELDS = set(JOURNAL_FIELDS) | set(PROCEEDINGS_FIELDS)

FieldRow = Tuple[str, str, str, str, str, str]
UncheckedRow = Tuple[str, str, str, str, str]
VenueRow = Tuple[str, str, str, str, str, str, str]


@dataclass
class _Checked:
    key: str
    venue: str
    year: str
    source: str
    record: Optional[Venue]
    upstream: Dict[str, str]  # official fields, polished as `add` writes them
    local: Set[str]
    missing: Dict[str, str] = field(default_factory=dict)  # field -> official value the entry lacks


@dataclass
class OfficialCheck:
    """What :func:`check_official_fields` found."""

    fields: List[FieldRow] = field(default_factory=list)
    unchecked: List[UncheckedRow] = field(default_factory=list)
    venues: List[VenueRow] = field(default_factory=list)
    checked: int = 0
    skipped: int = 0
    unmatched: int = 0  # entries that --offline couldn't compare: no --local match
    applied: int = 0
    # Schemas the official BibTeX supports and the library lacks (see bibcc.schemas).
    proposals: List[Proposal] = field(default_factory=list)

    @property
    def strict_findings(self) -> int:
        return sum(row[2] in STRICT_ISSUES for row in self.fields)


@dataclass
class _Local:
    key: str
    stem: str
    doi: str
    title: str
    official: object  # bibcc.official.Official


def _local_index(paths: Iterable[str | Path], log: Callable[[str], None]) -> List[_Local]:
    from bibcc.adder import local_entries
    from bibcc.official import official_fields
    from bibcc.sources import normalize_doi

    index: List[_Local] = []
    for path in paths:
        if not Path(path).exists():
            log(f"⚠️  --local path not found: {path}")
            continue
        for label, key, official in local_entries(str(path), log):
            _, fields = official_fields(official.text)
            stem = Path(label.rsplit(":", 1)[0]).stem
            index.append(_Local(key, stem, normalize_doi(fields.get("doi", "")).lower(),
                                fields.get("title", ""), official))
    return index


def _find_local(entry: Dict[str, str], index: Sequence[_Local]) -> object:
    from bibcc.sources import normalize_doi

    key = entry["ID"]
    doi = normalize_doi(entry.get("doi", "")).lower()
    title = entry.get("title", "")
    for match in (
        lambda item: item.key == key or item.stem == key,
        lambda item: bool(doi) and item.doi == doi,
        lambda item: bool(title.strip()) and _same_title(title, item.title),
    ):
        for item in index:
            if match(item):
                return item.official
    return None


def _compare(
    entry: Dict[str, str],
    entry_type: str,
    upstream: Dict[str, str],
    record: Optional[Venue],
    ignored: Set[str],
    source: str,
) -> Tuple[List[FieldRow], Dict[str, str]]:
    """Field rows for one entry, and the official values of the fields it lacks."""
    key = entry["ID"]
    local = {k: v for k, v in entry.items() if k not in ("ID", "ENTRYTYPE") and str(v).strip()}
    rows: List[FieldRow] = []
    missing: Dict[str, str] = {}
    if entry_type and entry.get("ENTRYTYPE", "").lower() != entry_type:
        rows.append((key, "ENTRYTYPE", TYPE, entry.get("ENTRYTYPE", "").lower(), entry_type, source))
    supplied = set(record.fields) if record is not None else set()
    for name in sorted(set(local) | set(upstream)):
        if name in ignored or name == "title":
            continue
        ours, theirs = local.get(name, ""), upstream.get(name, "")
        if theirs and not ours:
            missing[name] = theirs
            rows.append((key, name, UPSTREAM_ONLY, "", theirs, source))
        elif ours and not theirs:
            if name not in _OWN_FIELDS and name not in supplied:
                rows.append((key, name, LOCAL_ONLY, " ".join(ours.split()), "", source))
        elif not _same_value(name, ours, theirs):
            rows.append((key, name, DIFFERS, " ".join(ours.split()), theirs, source))
    return rows, missing


def _same_value(name: str, ours: str, theirs: str) -> bool:
    """Like :func:`bibcc.completer.same_field_value`, but blind to spaces.

    Exports end control words with a space (``Micha\\l and``), which TeX
    swallows, so the two spellings of a name only agree without spaces.
    """
    from bibcc.completer import _comparable, same_field_value

    if same_field_value(name, ours, theirs):
        return True
    a, b = _comparable(name, ours), _comparable(name, theirs)
    return isinstance(a, str) and isinstance(b, str) and "".join(a.split()) == "".join(b.split())


def _same_title(ours: str, theirs: str) -> bool:
    """Titles agree on their letters and digits (IEEE marks some with a trailing ``*``)."""
    from bibcc.completer import _comparable

    def letters(title: str) -> str:
        return "".join(ch for ch in _comparable("title", title) if ch.isalnum())

    return letters(ours) == letters(theirs)


def _lookup(entry: Dict[str, str], offline: bool, index: Sequence[_Local], library: VenueLibrary):
    """``(official or None, record DOI, OfficialLookup or None)`` for one entry."""
    from bibcc.official import find_official
    from bibcc.sources import is_arxiv_doi, normalize_doi
    from bibcc.upgrader import record_from_entry

    local = _find_local(entry, index) if index else None
    doi = normalize_doi(entry.get("doi", ""))
    doi = "" if is_arxiv_doi(doi) else doi
    if local is not None or offline:
        return local, doi, None
    lookup = find_official(record_from_entry(entry), download=True, interim=False, library=library)
    return lookup.official, doi, lookup


def _venue_rows(checked: List[_Checked]) -> List[VenueRow]:
    from bibcc.completer import same_field_value

    rows: List[VenueRow] = []
    groups: Dict[Tuple[str, str], List[_Checked]] = defaultdict(list)
    for item in checked:
        groups[(item.venue, item.year)].append(item)
    for (venue, year), items in sorted(groups.items()):
        for name in sorted({n for i in items for n in i.missing}):
            have = [i for i in items if name in i.upstream]
            lacking = [i.key for i in have if name in i.missing]
            rows.append((venue, year, name, ENTRIES_LACK, str(len(have)), str(len(lacking)),
                         ", ".join(lacking)))

    by_record: Dict[int, List[_Checked]] = defaultdict(list)
    for item in checked:
        if item.record is not None:
            by_record[id(item.record)].append(item)
    for items in by_record.values():
        record = items[0].record
        for name in sorted(_LIBRARY_FIELDS):
            values = [i.upstream[name] for i in items if name in i.upstream]
            if not values or any(not same_field_value(name, v, values[0]) for v in values[1:]):
                continue
            ours = record.fields.get(name, "")
            if ours and same_field_value(name, ours, values[0]):
                continue
            issue = LIBRARY_DIFFERS if ours else LIBRARY_LACKS
            detail = f"library '{ours}', official '{values[0]}'" if ours else f"official '{values[0]}'"
            rows.append((record.name, str(record.year or ""), name, issue, str(len(values)), "", detail))
    return rows


def schema_rows(proposals: Iterable[Proposal]) -> List[VenueRow]:
    """``schema_lacks`` and ``schema_differs`` rows of the venue summary."""
    return [
        (p.venue, p.year, "entry_fields", p.status, str(len(p.entries)), "", p.detail())
        for p in proposals
    ]


def check_official_fields(
    input_path: str,
    library: VenueLibrary,
    ids: Iterable[str] = (),
    local: Sequence[str | Path] = (),
    offline: bool = False,
    apply: Iterable[str] = (),
    ignore_fields: Iterable[str] = (),
    delay: float = 1.0,
    log: Optional[Callable[[str], None]] = None,
) -> OfficialCheck:
    """Compare the entries of *input_path* with their official BibTeX.

    Args:
        input_path: Path to the BibTeX file.
        library: Venue library, to skip interim entries, to leave out the
            fields it supplies, and to compare its records with the official values.
        ids: Check only these citation keys.
        local: ``.bib`` files or directories of official BibTeX that you got
            yourself; an entry matches by citation key (or file name), DOI,
            or title, and isn't downloaded.
        offline: Use only *local*; download nothing.
        apply: Fields to add to the entries that lack them, with the official
            value (``all``: every ``upstream_only`` field).  Writes *input_path*.
        ignore_fields: Fields not to compare.
        delay: Seconds to wait between downloads.
        log: Optional logging callback; falls back to ``print``.
    """
    from bibcc.adder import metadata_keys, polish_fields
    from bibcc.official import next_step, official_fields
    from bibcc.upgrader import candidate_kind

    log = log or print
    ids = set(ids)
    apply = {f.lower() for f in apply}
    ignored = {f.lower() for f in ignore_fields}
    result = OfficialCheck()
    log(f"🏛️  Comparing the entries of {input_path} with their official BibTeX...")

    text = read_bib(input_path)
    parser = bibtexparser.bparser.BibTexParser(common_strings=True)
    entries = [e for e in bibtexparser.loads(text, parser=parser).entries if not ids or e["ID"] in ids]
    built = metadata_keys(text)
    index = _local_index(local, log) if local else []
    if local:
        log(f"   {len(index)} entries of official BibTeX in {', '.join(map(str, local))}.")

    checked: List[_Checked] = []
    observations: List[Observation] = []
    downloads = 0
    for entry in entries:
        key = entry["ID"]
        year = entry.get("year", "").strip()
        venue = (entry.get("booktitle") or entry.get("journal") or "").strip()
        if not venue or not year or candidate_kind(entry, library, key in built):
            result.skipped += 1
            continue
        if downloads and delay and not offline:
            time.sleep(delay)
        official, doi, lookup = _lookup(entry, offline, index, library)
        downloads += lookup is not None
        if official is None:
            if lookup is None:
                result.unmatched += 1
            elif lookup.error:
                result.unchecked.append((key, "failed", lookup.error, lookup.manual_url, next_step(lookup)))
            else:
                result.unchecked.append((key, "no_bibtex", lookup.reason, lookup.manual_url, next_step(lookup)))
            continue
        if official.interim:
            result.unchecked.append((key, "no_bibtex", f"only interim BibTeX ({official.provider})",
                                     official.url, "wait"))
            continue
        entry_type, cleaned = official_fields(official.text)
        if doi and not cleaned.get("doi"):
            cleaned["doi"] = doi  # like `add`: Springer exports have no DOI
        upstream = polish_fields(cleaned, keep_title=True)
        if not _same_title(entry.get("title", ""), upstream.get("title", "")):
            result.unchecked.append((key, "mismatch", f"the official BibTeX is '{upstream.get('title', '')}'",
                                     official.url, "check"))
            continue
        record = library.lookup(venue, year, venue_kind(entry.get("ENTRYTYPE", ""), entry),
                                issn=entry.get("issn")).venue
        source = " ".join(f"{official.provider} {official.url}".split())
        rows, missing = _compare(entry, entry_type, upstream, record, ignored, source)
        local_fields = {k for k, v in entry.items() if str(v).strip()}
        item = _Checked(key, record.name if record is not None else venue, year, source, record,
                        upstream, local_fields, missing)
        checked.append(item)
        result.fields.extend(rows)
        seen = observe(entry, library, [n for n, v in upstream.items() if str(v).strip()],
                       set(IGNORED_FIELDS) | ignored)
        if seen is not None:
            observations.append(seen)
    result.checked = len(checked)

    if apply:
        patches = {
            item.key: {
                n: v for n, v in item.missing.items()
                if n in apply or APPLY_ALL in apply
            }
            for item in checked
        }
        patches = {k: v for k, v in patches.items() if v}
        if patches:
            try:
                new_text, applied = set_fields(text, patches, replace=False)
            except BibEditError as e:
                log(f"❌ Could not add the official fields safely: {e}\n   Nothing was written.")
            else:
                write_bib(input_path, new_text)
                result.applied = len(applied)
                done = {(a.key, a.field) for a in applied}
                result.fields = [r for r in result.fields if (r[0], r[1]) not in done]
                for item in checked:
                    item.missing = {n: v for n, v in item.missing.items() if (item.key, n) not in done}
                log(f"✍️  Added {len(applied)} official field values to {input_path}.")

    result.venues = _venue_rows(checked)
    result.proposals = propose(observations, library, OFFICIAL)
    result.venues += schema_rows(result.proposals)
    _log_result(result, log)
    return result


def _log_result(result: OfficialCheck, log: Callable[[str], None]) -> None:
    log(f"   Checked {result.checked} entries; skipped {result.skipped} preprints, interim entries, "
        f"entries built from metadata, and entries without a venue or year (bibcc upgrade handles the first three).")
    if result.unmatched:
        log(f"   {result.unmatched} entries match no --local entry; without --offline, BibCC downloads them.")
    if result.unchecked:
        log(f"\n⏳ {len(result.unchecked)} entries could not be compared:")
        for key, status, detail, url, next_ in result.unchecked:
            log(f"   {key} [{status}, next: {next_}] {detail}" + (f" ({url})" if url else ""))
    log(f"\n{'ID':<40} | {'Field':<12} | {'Issue':<13} | Bib → Official")
    log(SEPARATOR_LIGHT * SEPARATOR_WIDTH)
    for key, name, issue, ours, theirs, _ in result.fields:
        log(f"{key:<40} | {name:<12} | {issue:<13} | {ours or '—'} → {theirs or '—'}")
    log(SEPARATOR_LIGHT * SEPARATOR_WIDTH)
    if result.venues:
        log("\n📚 By venue and year:")
        for venue, year, name, issue, have, lacking, detail in result.venues:
            if issue == ENTRIES_LACK:
                log(f"   {venue} ({year}): '{name}' is in the official BibTeX of {have} checked entries; "
                    f"{lacking} lack it")
            elif issue in SCHEMA_STATUSES:
                when = f" ({year})" if year else ""
                verb = "has no schema" if issue == SCHEMA_LACKS else "has a different schema"
                log(f"   {venue}{when}: the venue library {verb}; {detail}")
            else:
                verb = "lacks" if issue == LIBRARY_LACKS else "differs on"
                log(f"   {venue} ({year}): the venue library {verb} '{name}', {detail}")
    if result.fields:
        counts: Dict[str, int] = defaultdict(int)
        for row in result.fields:
            counts[row[2]] += 1
        breakdown = "; ".join(f"{k}: {n}" for k, n in sorted(counts.items()))
        log(f"⚠️  Found {len(result.fields)} differences in {len({r[0] for r in result.fields})} entries. "
            f"Breakdown -> {breakdown}")
        log(f"   To add official values, run with --apply FIELDS (or --apply {APPLY_ALL}).")
    elif result.checked:
        log("✅ The checked entries agree with their official BibTeX.")
