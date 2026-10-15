"""
Missing field checker for BibTeX entries.

Scans a .bib file and reports entries that lack specified required fields
(e.g., month, publisher).  With a venue library, an entry whose venue record
says ``month: none`` (a conference held across two months, or a journal
without monthly issues) isn't expected to have a month, and an entry whose
venue has a schema (see :mod:`bibcc.schemas`) isn't expected to have a
per-paper field that the venue's official BibTeX never has.

Usage:
    from bibcc.checkers.missing_fields import check_missing_fields

    rows = check_missing_fields("refs.bib", ["month"], ["article"])
"""

from __future__ import annotations

from typing import Callable, List, Optional, Sequence, Tuple

import bibtexparser

from bibcc.logging_utils import SEPARATOR_LIGHT, SEPARATOR_WIDTH
from bibcc.missing_venues import JOURNAL_FIELDS, PROCEEDINGS_FIELDS
from bibcc.schemas import IGNORED_FIELDS, expected_fields
from bibcc.venues import JOURNAL, VenueLibrary, has_no_month, venue_kind

DEFAULT_ENTRY_TYPES = ["inproceedings", "article", "proceedings", "conference"]


def _venue_has_no_month(entry: dict, library: Optional[VenueLibrary]) -> bool:
    if library is None:
        return False
    venue = entry.get("booktitle") or entry.get("journal") or ""
    year = entry.get("year", "")
    if not venue:
        return False
    found = library.lookup(venue, year, venue_kind(entry.get("ENTRYTYPE", ""), entry), issn=entry.get("issn"))
    return found.venue is not None and has_no_month(library.fields_of(found.venue))


def _outside_schema(entry: dict, fields: Sequence[str], library: Optional[VenueLibrary]) -> List[str]:
    """The *fields* that the schema of the entry's venue leaves out, as per-paper fields it never has."""
    if library is None or not fields:
        return []
    schema = expected_fields(entry, library)[0]
    if not schema:
        return []
    kind = venue_kind(entry.get("ENTRYTYPE", ""), entry)
    described = set(JOURNAL_FIELDS if kind == JOURNAL else PROCEEDINGS_FIELDS) | set(IGNORED_FIELDS)
    return [f for f in fields if f.lower() not in schema and f.lower() not in described]


def check_missing_fields(
    input_path: str,
    required_fields: Sequence[str],
    target_types: Sequence[str],
    log: Optional[Callable[[str], None]] = None,
    library: Optional[VenueLibrary] = None,
) -> List[Tuple[str, str, str, List[str]]]:
    """Check for missing fields and return the results.

    Args:
        input_path: Path to the BibTeX file.
        required_fields: Field names that every matching entry must have.
        target_types: Entry types to inspect (e.g. ``["article"]``).
        log: Optional logging callback; falls back to ``print``.
        library: Venue library; an entry whose record says ``month: none``
            isn't reported for a missing month, nor for a field outside its
            venue's schema.

    Returns:
        List of ``(entry_id, entry_type, year, missing_fields)`` tuples.
    """
    log = log or print
    required_fields = [f.strip() for f in required_fields if f.strip()]
    if not required_fields:
        log("ℹ️  No required fields specified, skipping missing-field check.")
        return []

    log(f"🔍 Scanning {input_path} for missing fields: {', '.join(required_fields)}\n")

    try:
        with open(input_path, "r", encoding="utf-8") as f:
            parser = bibtexparser.bparser.BibTexParser(common_strings=True)
            bib_db = bibtexparser.load(f, parser=parser)
    except FileNotFoundError:
        log(f"❌ Error: File '{input_path}' not found.")
        return []

    missing_rows: List[Tuple[str, str, str, List[str]]] = []
    no_month: List[str] = []
    outside: List[str] = []

    log(f"{'ID':<40} | {'Type':<15} | {'Year':<6} | Missing")
    log(SEPARATOR_LIGHT * SEPARATOR_WIDTH)

    for entry in bib_db.entries:
        entry_type = entry.get("ENTRYTYPE", "").lower()
        if entry_type not in target_types:
            continue

        missing = [
            field for field in required_fields if not entry.get(field, "").strip()
        ]
        if "month" in missing and _venue_has_no_month(entry, library):
            missing.remove("month")
            no_month.append(entry.get("ID", ""))
        unexported = _outside_schema(entry, missing, library)
        if unexported:
            missing = [f for f in missing if f not in unexported]
            outside.append(f"{entry.get('ID', '')} ({', '.join(unexported)})")
        if missing:
            missing_rows.append(
                (entry.get("ID", ""), entry_type, entry.get("year", "N/A"), missing)
            )

    for row in missing_rows:
        rid, rtype, ryear, rmiss = row
        log(f"{rid:<40} | {rtype:<15} | {ryear:<6} | {', '.join(rmiss)}")

    log(SEPARATOR_LIGHT * SEPARATOR_WIDTH)
    if no_month:
        log(f"ℹ️  {len(no_month)} entries have no month because the venue library says that their venue "
            f"has none: {', '.join(no_month)}")
    if outside:
        log(f"ℹ️  {len(outside)} entries lack fields that the official BibTeX of their venue doesn't have "
            f"(see its entry_fields in the venue library): {'; '.join(outside)}")
    if not missing_rows:
        log("✅ All target entries contain the required fields.")
    else:
        field_counts = {f: 0 for f in required_fields}
        for _, _, _, miss in missing_rows:
            for f in miss:
                field_counts[f] += 1
        summary = "; ".join([f"{k}: {v}" for k, v in field_counts.items()])
        log(
            f"⚠️  Found {len(missing_rows)} entries missing fields. Breakdown -> {summary}"
        )

    return missing_rows
