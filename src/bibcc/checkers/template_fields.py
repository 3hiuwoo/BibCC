"""
Venue library completeness checker.

Inspects the journal and proceedings records of a venue library file (see
:mod:`bibcc.venues`) for missing fields (publisher, ISSN, venue, etc.).  Supports per-venue
field overrides so that specific conferences can require additional fields
(e.g., ECCV → ``series``, some conferences → ``editor``).  Also compares the
editions of each conference with one another and reports fields that one
edition defines and another lacks.

Usage:
    from bibcc.checkers.template_fields import check_template_fields

    check_template_fields(Path("venues.yaml"), ["publisher", "issn"], ["venue"])
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence, Tuple

from bibcc.logging_utils import SEPARATOR_LIGHT, SEPARATOR_WIDTH
from bibcc.venues import EVENT_FIELDS, VenueLibrary, family_key, family_label

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


def _norm_value(value: str) -> str:
    """Braces, case, and whitespace don't matter when comparing field values."""
    return " ".join(value.replace("{", "").replace("}", "").split()).casefold()


def check_edition_consistency(
    proceedings_templates: Dict[Tuple[str, str], Dict],
    log: Callable[[str], None],
) -> None:
    """Report fields that one edition of a venue defines and another lacks.

    Editions of the same conference (grouped by :func:`bibcc.venues.family_key`,
    which ignores years and ordinals in the name) should define the same
    fields.  When every edition that has a field agrees on its value, the
    report suggests that value for the editions that lack it.  A record still
    named by its interim (CVF or OpenReview) booktitle describes proceedings
    that aren't out yet, so only its event fields count as missing.
    """
    # Imported here: bibcc.official imports this package.
    from bibcc.official import interim_source_of

    families: Dict[str, List[Tuple[str, str, Dict]]] = {}
    for (venue, year), fields in proceedings_templates.items():
        families.setdefault(family_key(venue), []).append((venue, year, fields))

    log("\n🔗 Cross-edition consistency (fields one edition has and another lacks):")
    found = False
    for editions in (e for _, e in sorted(families.items()) if len(e) > 1):
        editions.sort(key=lambda edition: edition[1])
        interim = {year for venue, year, _ in editions if interim_source_of(venue, year=year)}
        published = [venue for venue, year, _ in editions if year not in interim]
        label = family_label(published[-1] if published else editions[-1][0])
        all_fields = sorted({f for _, _, fields in editions for f in fields})
        for fname in all_fields:
            have = [(year, fields[fname]) for _, year, fields in editions if fields.get(fname)]
            lack = [
                year for _, year, fields in editions
                if not fields.get(fname) and (year not in interim or fname in EVENT_FIELDS)
            ]
            if not lack or not have:
                continue
            found = True
            hint = ""
            if len({_norm_value(value) for _, value in have}) == 1:
                years = ", ".join(year for year, _ in have)
                hint = f"; {years} {'have' if len(have) > 1 else 'has'} '{have[0][1]}'"
            log(f"  🔸 {label}: '{fname}' missing in {', '.join(lack)}{hint}")
    if not found:
        log("  ✅ Editions of the same venue define the same fields.")


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
        log(SEPARATOR_LIGHT * SEPARATOR_WIDTH)

        for name, fields in sorted(journal_templates.items()):
            missing = [f for f in journal_fields if f not in fields or not fields[f]]
            if missing:
                journal_issues.append((name, missing))
                log(f"{name[:60]:<60} | {', '.join(missing)}")

        log(SEPARATOR_LIGHT * SEPARATOR_WIDTH)
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
        log(SEPARATOR_LIGHT * SEPARATOR_WIDTH)

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

        log(SEPARATOR_LIGHT * SEPARATOR_WIDTH)
        if proceedings_issues:
            log(
                f"⚠️  {len(proceedings_issues)}/{len(proceedings_templates)} proceedings have missing fields"
            )
        else:
            log(f"✅ All {len(proceedings_templates)} proceedings have required fields")

    # Summary by field
    log("\n📊 Summary by field:")

    for label, checked, issues in (
        ("Journals", journal_fields, journal_issues),
        ("Proceedings", proceedings_fields, proceedings_issues),
    ):
        if not checked:
            continue
        counts: Dict[str, int] = {f: 0 for f in checked}
        for _, missing in issues:
            for f in missing:
                counts[f] = counts.get(f, 0) + 1
        log(f"\n  {label}:")
        for field, count in counts.items():
            log(f"    {field}: {count} missing")

    # Cross-edition consistency
    check_edition_consistency(proceedings_templates, log)
