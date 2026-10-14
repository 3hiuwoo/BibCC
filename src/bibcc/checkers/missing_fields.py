"""
Missing field checker for BibTeX entries.

Scans a .bib file and reports entries that lack specified required fields
(e.g., month, publisher).  With a venue library, an entry whose venue record
says ``month: none`` (a conference held across two months, or a journal
without monthly issues) isn't expected to have a month.

Usage:
    from bibcc.checkers.missing_fields import check_missing_fields

    rows = check_missing_fields("refs.bib", ["month"], ["article"])
"""

from __future__ import annotations

from typing import Callable, List, Optional, Sequence, Tuple

import bibtexparser

from bibcc.logging_utils import SEPARATOR_LIGHT, SEPARATOR_WIDTH
from bibcc.venues import VenueLibrary, has_no_month, venue_kind

DEFAULT_ENTRY_TYPES = ["inproceedings", "article", "proceedings", "conference"]


def _venue_has_no_month(entry: dict, library: Optional[VenueLibrary]) -> bool:
    if library is None:
        return False
    venue = entry.get("booktitle") or entry.get("journal") or ""
    year = entry.get("year", "")
    if not venue:
        return False
    found = library.lookup(venue, year, venue_kind(entry.get("ENTRYTYPE", ""), entry), issn=entry.get("issn"))
    return found.venue is not None and has_no_month(found.venue.fields)


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
            isn't reported for a missing month.

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
