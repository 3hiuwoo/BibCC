"""
Cross-edition field check for BibTeX entries.

Groups the entries of a .bib file, and of the ``--against`` files, by venue
across its editions (see :func:`bibcc.venues.family_key`), and reports the
fields an entry lacks that the other entries of its venue have.  The
official BibTeX of a venue usually has the same fields every year (PMLR
gives every ICML paper ``day``, ``pdf``, ``series``, and so on), so a gap
is either a field lost on the way or a change of the venue's export.  Two
kinds of finding tell these apart:

* ``same_year``: most other entries of the same venue and year have the
  field.  The entry is probably incomplete.
* ``other_years``: few or none of this year's entries have it, but most
  other years do.  Either the field is missing from all of them, or the
  venue changed what it exports.

Fields in :data:`DEFAULT_IGNORED_FIELDS` (the fields every compared entry
has, BibCC's own ``citation``, and exporter bookkeeping) are never compared.  Entries that cite an interim (CVF or
OpenReview) booktitle, entries built from metadata, and empty entries are
left out: they lack fields by design.  So are ``month`` and ``day`` for an
entry whose venue library record says ``month: none``.

Usage:
    from bibcc.checkers.edition_fields import check_edition_fields

    rows = check_edition_fields("refs.bib", against=["bib/"], library=library)
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional, Sequence, Set, Tuple

import bibtexparser

from bibcc.bibedit import read_bib
from bibcc.logging_utils import SEPARATOR_LIGHT, SEPARATOR_WIDTH
from bibcc.missing_venues import JOURNAL_FIELDS, PROCEEDINGS_FIELDS
from bibcc.venues import (
    JOURNAL,
    VenueLibrary,
    family_key,
    family_label,
    has_no_month,
    normalize_venue,
    venue_kind,
)

DEFAULT_IGNORED_FIELDS: Tuple[str, ...] = (
    # Every compared entry has these, and `check missing` reports them.
    "title", "author", "year", "booktitle", "journal",
    # Written by BibCC itself (`bibcc scholar cite`).
    "citation",
    # Exporter and reference-manager bookkeeping.
    "annote", "bibsource", "biburl", "copyright", "mendeley-groups", "timestamp", "urldate",
)

SAME_YEAR = "same_year"
OTHER_YEARS = "other_years"

# A field counts as the venue's style when at least this share of the
# entries (same year) or of the years (other years) has it.
SHARE = 0.75
MIN_PEERS = 2  # same-year entries that must have the field
MIN_YEARS = 2  # other years that must have the field

# Fields a venue library record usually supplies.
_LIBRARY_FIELDS = set(JOURNAL_FIELDS) | set(PROCEEDINGS_FIELDS)

Row = Tuple[str, str, str, str, str, str]  # (entry_id, venue, year, field, issue_type, evidence)


@dataclass
class _Item:
    key: str
    year: str
    venue: str
    fields: Set[str]
    in_input: bool
    library_fields: Optional[Set[str]] = None  # fields of the matched library record
    no_month: bool = False  # the record says the venue has no month


def _bib_files(paths: Iterable[str | Path], exclude: Path, log: Callable[[str], None]) -> List[Path]:
    excluded = exclude.resolve()
    files: List[Path] = []
    for raw in paths:
        path = Path(raw)
        if path.is_dir():
            found = sorted(
                p for p in path.rglob("*.bib")
                if not any(part.startswith(".") for part in p.relative_to(path).parts)
            )
        elif path.is_file():
            found = [path]
        else:
            log(f"⚠️  --against path not found: {path}")
            continue
        files += [p for p in found if p.resolve() != excluded and p not in files]
    return files


def _items(
    path: Path,
    in_input: bool,
    library: Optional[VenueLibrary],
    families: Dict[Tuple[str, str], List[_Item]],
    skipped: Dict[str, int],
    seen: Set[str],
) -> int:
    # Imported here: bibcc.adder and bibcc.official import this package.
    from bibcc.adder import metadata_keys
    from bibcc.official import interim_source_of

    text = read_bib(path)
    parser = bibtexparser.bparser.BibTexParser(common_strings=True)
    entries = bibtexparser.loads(text, parser=parser).entries
    built = metadata_keys(text)
    for entry in entries:
        # A key seen before (the input itself, or a copy of it) would count one paper twice.
        if entry["ID"] in seen:
            continue
        seen.add(entry["ID"])
        year = entry.get("year", "").strip()
        venue = (entry.get("booktitle") or entry.get("journal") or "").strip()
        if not year or not venue:
            continue
        if entry["ID"] in built:
            skipped["metadata"] += in_input
            continue
        kind = venue_kind(entry.get("ENTRYTYPE", ""), entry)
        record = None
        if library is not None:
            result = library.lookup(venue, year, kind, issn=entry.get("issn"))
            if result.interim_source:
                skipped["interim"] += in_input
                continue
            record = result.venue
        if kind != JOURNAL and interim_source_of(venue, url=entry.get("url", ""), year=year):
            skipped["interim"] += in_input
            continue
        name = record.name if record is not None else venue
        group = normalize_venue(name) if kind == JOURNAL else family_key(name)
        fields = {k for k, v in entry.items() if k not in ("ID", "ENTRYTYPE") and str(v).strip()}
        no_month = record is not None and has_no_month(record.fields)
        families[(kind, group)].append(_Item(
            key=entry["ID"],
            year=year,
            venue=name,
            fields=fields,
            in_input=in_input,
            library_fields=None if record is None else set(record.fields) - ({"month"} if no_month else set()),
            no_month=no_month,
        ))
    return len(entries)


def _share(items: Sequence[_Item], name: str) -> float:
    return sum(name in i.fields for i in items) / len(items) if items else 0.0


def _library_hint(item: _Item, name: str) -> str:
    if item.library_fields is None:
        return ""
    if name in item.library_fields:
        return "; the library has it, so 'bibcc complete' adds it"
    if name in _LIBRARY_FIELDS:
        return "; the library record lacks it too"
    return ""


def _family_rows(items: List[_Item], ignored: Set[str]) -> List[Row]:
    by_year: Dict[str, List[_Item]] = defaultdict(list)
    for item in items:
        by_year[item.year].append(item)
    label = family_label(max(items, key=lambda i: i.year).venue)
    compared = sorted({f for i in items for f in i.fields} - ignored)
    styled_years = {
        name: {year for year, group in by_year.items() if _share(group, name) >= SHARE} for name in compared
    }
    rows: List[Row] = []
    for item in sorted((i for i in items if i.in_input), key=lambda i: (i.year, i.key)):
        same_year = [i for i in by_year[item.year] if i is not item]
        for name in compared:
            if name in item.fields or (item.no_month and name in ("month", "day")):
                continue
            have = sum(name in i.fields for i in same_year)
            if have >= MIN_PEERS and have / len(same_year) >= SHARE:
                evidence = f"{have} of {len(same_year)} other {item.year} entries have it"
                rows.append((item.key, label, item.year, name, SAME_YEAR, evidence + _library_hint(item, name)))
                continue
            if item.year in styled_years[name]:
                continue
            others = sorted(y for y in by_year if y != item.year)
            with_field = sorted(styled_years[name] - {item.year})
            if len(with_field) < MIN_YEARS or len(with_field) / len(others) < SHARE:
                continue
            evidence = f"{len(with_field)} of {len(others)} other years have it ({', '.join(with_field)})"
            if have:
                evidence += f", and {have} of {len(same_year)} other {item.year} entries"
            rows.append((item.key, label, item.year, name, OTHER_YEARS, evidence + _library_hint(item, name)))
    return rows


def check_edition_fields(
    input_path: str,
    against: Sequence[str | Path] = (),
    library: Optional[VenueLibrary] = None,
    ignore_fields: Iterable[str] = (),
    include_fields: Iterable[str] = (),
    log: Optional[Callable[[str], None]] = None,
) -> List[Row]:
    """Report fields that other entries of the same venue have and an entry of *input_path* lacks.

    Args:
        input_path: Path to the BibTeX file whose entries are reported.
        against: Other ``.bib`` files or directories whose entries join the
            comparison (their own gaps aren't reported).
        library: Venue library, to group entries by the record they match,
            to leave out interim entries, and to say whether the library
            supplies a missing field.  Optional.
        ignore_fields: Fields to ignore in addition to :data:`DEFAULT_IGNORED_FIELDS`.
        include_fields: Fields of :data:`DEFAULT_IGNORED_FIELDS` to compare anyway.
        log: Optional logging callback; falls back to ``print``.

    Returns:
        ``(entry_id, venue, year, field, issue_type, evidence)`` tuples,
        where *issue_type* is ``same_year`` or ``other_years``.
    """
    log = log or print
    ignored = (set(DEFAULT_IGNORED_FIELDS) - {f.lower() for f in include_fields}) | {
        f.lower() for f in ignore_fields
    }
    log(f"🧬 Comparing the entries of {input_path} with other editions of their venues...")
    log(f"   Ignored fields: {', '.join(sorted(ignored))}\n")

    families: Dict[Tuple[str, str], List[_Item]] = defaultdict(list)
    skipped = {"interim": 0, "metadata": 0}
    seen: Set[str] = set()
    _items(Path(input_path), True, library, families, skipped, seen)
    files = _bib_files(against, Path(input_path), log)
    others = 0
    for file in files:
        try:
            others += _items(file, False, library, families, skipped, seen)
        except Exception as e:  # noqa: BLE001 - a broken file should not stop the run
            log(f"⚠️  Could not read {file}: {e}")
    if files:
        log(f"   Compared with {others} entries in {len(files)} other files.")
    if skipped["interim"] or skipped["metadata"]:
        log(f"   Left out {skipped['interim']} entries with an interim booktitle and "
            f"{skipped['metadata']} entries built from metadata.")

    rows: List[Row] = []
    for _, items in sorted(families.items()):
        if any(i.in_input for i in items) and len(items) > 1:
            rows.extend(_family_rows(items, ignored))

    log(f"\n{'ID':<40} | {'Year':<4} | {'Field':<10} | {'Issue':<11} | Evidence")
    log(SEPARATOR_LIGHT * SEPARATOR_WIDTH)
    venue = None
    for entry_id, label, year, name, kind, evidence in rows:
        if label != venue:
            venue = label
            log(f"📚 {label}")
        log(f"{entry_id:<40} | {year:<4} | {name:<10} | {kind:<11} | {evidence}")
    log(SEPARATOR_LIGHT * SEPARATOR_WIDTH)
    if not rows:
        log("✅ Every entry has the fields that the other entries of its venue have.")
        return rows
    same = sum(r[4] == SAME_YEAR for r in rows)
    log(f"⚠️  Found {len(rows)} missing fields in {len({r[0] for r in rows})} entries. "
        f"Breakdown -> {SAME_YEAR}: {same}; {OTHER_YEARS}: {len(rows) - same}")
    if same < len(rows):
        log(f"   An {OTHER_YEARS} finding can mean that the venue changed its BibTeX, "
            "not that the entry lacks the field.")
    return rows
