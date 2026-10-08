"""
Venue library completeness checker.

Inspects the journal and proceedings records in the venue library
(``bibcc/data/venues.yaml``) for missing fields (publisher, ISSN, venue, etc.).  Supports per-venue
field overrides so that specific conferences can require additional fields
(e.g., ECCV → ``series``, some conferences → ``editor``).

Usage:
    from bibcc.checkers.template_fields import check_template_fields

    check_template_fields(Path("venues.yaml"), ["publisher", "issn"], ["venue"])
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence, Tuple

from bibcc.venues import VenueLibrary

DEFAULT_JOURNAL_FIELDS = ["publisher", "issn"]
DEFAULT_PROCEEDINGS_FIELDS = ["venue", "publisher", "month"]

# Per-venue additional required fields.
# Keys are regex patterns matched (case-insensitive) against the venue name.
# Values are lists of extra fields required for matching templates.
VENUE_FIELD_OVERRIDES: Dict[str, List[str]] = {
    r"ECCV|European Conference on Computer Vision": ["series"],
    r"Lecture Notes in Computer Science|LNCS": ["series"],
}


def _get_venue_extra_fields(
    venue: str,
    overrides: Dict[str, List[str]],
) -> List[str]:
    """Return additional required fields for a venue based on override patterns."""
    extras: List[str] = []
    for pattern, fields in overrides.items():
        if re.search(pattern, venue, re.IGNORECASE):
            for f in fields:
                if f not in extras:
                    extras.append(f)
    return extras


def check_template_fields(
    templates_path: Path,
    journal_fields: Sequence[str],
    proceedings_fields: Sequence[str],
    venue_overrides: Optional[Dict[str, List[str]]] = None,
    log: Optional[Callable[[str], None]] = None,
) -> None:
    """Check templates for missing fields.

    This helps maintain consistency across templates by identifying
    which templates are missing certain expected fields.  When
    *venue_overrides* is provided (or defaults to ``VENUE_FIELD_OVERRIDES``),
    matching proceedings templates are also checked for the extra fields.

    Args:
        templates_path: Path to the venue library YAML.
        journal_fields: Fields to require in journal templates.
        proceedings_fields: Fields to require in proceedings templates.
        venue_overrides: Per-venue extra field requirements.  Defaults to
            ``VENUE_FIELD_OVERRIDES``.
        log: Optional logging callback; falls back to ``print``.
    """
    log = log or print
    if venue_overrides is None:
        venue_overrides = VENUE_FIELD_OVERRIDES

    try:
        library = VenueLibrary.load(templates_path)
    except Exception as e:
        log(f"❌ Error loading venue library {templates_path}: {e}")
        return

    journal_templates: Dict[str, Dict] = {v.name: v.fields for v in library.journals}
    proceedings_templates: Dict[Tuple[str, str], Dict] = {
        (v.name, str(v.year)): v.fields for v in library.proceedings
    }

    log(f"🔍 Checking venue library {templates_path}")
    log(f"   Journal fields to check: {', '.join(journal_fields)}")
    log(f"   Proceedings fields to check: {', '.join(proceedings_fields)}")
    log("")

    # Check journals
    journal_issues = []
    if journal_fields:
        log(f"{'Journal Name':<60} | Missing Fields")
        log("-" * 90)

        for name, fields in sorted(journal_templates.items()):
            missing = [f for f in journal_fields if f not in fields or not fields[f]]
            if missing:
                journal_issues.append((name, missing))
                log(f"{name[:60]:<60} | {', '.join(missing)}")

        log("-" * 90)
        if journal_issues:
            log(
                f"⚠️  {len(journal_issues)}/{len(journal_templates)} journals have missing fields"
            )
        else:
            log(f"✅ All {len(journal_templates)} journals have required fields")

    log("")

    # Check proceedings
    proceedings_issues = []
    if proceedings_fields:
        log(f"{'Proceedings (Venue, Year)':<70} | Missing Fields")
        log("-" * 100)

        # Sort by year descending
        sorted_procs = sorted(
            proceedings_templates.items(),
            key=lambda x: (-int(x[0][1]) if x[0][1].isdigit() else 0, x[0][0]),
        )

        for (venue, year), fields in sorted_procs:
            # Base required fields + venue-specific extra fields
            required = list(proceedings_fields)
            extras = _get_venue_extra_fields(venue, venue_overrides)
            for ef in extras:
                if ef not in required:
                    required.append(ef)

            missing = [f for f in required if f not in fields or not fields[f]]
            if missing:
                proceedings_issues.append(((venue, year), missing))
                display = f"({venue[:50]}, {year})"
                extra_note = f" [+{', '.join(extras)}]" if extras else ""
                log(f"{display:<70} | {', '.join(missing)}{extra_note}")

        log("-" * 100)
        if proceedings_issues:
            log(
                f"⚠️  {len(proceedings_issues)}/{len(proceedings_templates)} proceedings have missing fields"
            )
        else:
            log(f"✅ All {len(proceedings_templates)} proceedings have required fields")

    # Summary by field
    log("\n📊 Summary by field:")

    if journal_fields:
        log("\n  Journals:")
        for field in journal_fields:
            count = sum(
                1
                for _, fields in journal_templates.items()
                if field not in fields or not fields[field]
            )
            log(f"    {field}: {count} missing")

    if proceedings_fields:
        log("\n  Proceedings:")
        for field in proceedings_fields:
            count = sum(
                1
                for _, fields in proceedings_templates.items()
                if field not in fields or not fields[field]
            )
            log(f"    {field}: {count} missing")
