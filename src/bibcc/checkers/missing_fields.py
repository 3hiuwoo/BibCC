"""
Missing field checker for BibTeX entries.

Scans a .bib file and reports entries that lack specified required fields
(e.g., month, publisher).

Usage:
    from bibcc.checkers.missing_fields import check_missing_fields

    rows = check_missing_fields("refs.bib", ["month"], ["article"])
"""

from __future__ import annotations

from typing import Callable, List, Optional, Sequence, Tuple

import bibtexparser

DEFAULT_ENTRY_TYPES = ["inproceedings", "article", "proceedings", "conference"]


def check_missing_fields(
    input_path: str,
    required_fields: Sequence[str],
    target_types: Sequence[str],
    log: Optional[Callable[[str], None]] = None,
) -> List[Tuple[str, str, str, List[str]]]:
    """Check for missing fields and return the results.

    Args:
        input_path: Path to the BibTeX file.
        required_fields: Field names that every matching entry must have.
        target_types: Entry types to inspect (e.g. ``["article"]``).
        log: Optional logging callback; falls back to ``print``.

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

    log(f"{'ID':<40} | {'Type':<15} | {'Year':<6} | Missing")
    log("-" * 95)

    for entry in bib_db.entries:
        entry_type = entry.get("ENTRYTYPE", "").lower()
        if entry_type not in target_types:
            continue

        missing = [
            field for field in required_fields if not entry.get(field, "").strip()
        ]
        if missing:
            missing_rows.append(
                (entry.get("ID", ""), entry_type, entry.get("year", "N/A"), missing)
            )

    for row in missing_rows:
        rid, rtype, ryear, rmiss = row
        log(f"{rid:<40} | {rtype:<15} | {ryear:<6} | {', '.join(rmiss)}")

    log("-" * 95)
    if not missing_rows:
        log("✅ Perfect! All target entries contain the required fields.")
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
