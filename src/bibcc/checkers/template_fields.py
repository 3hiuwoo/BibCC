"""
Venue library completeness checker.

Inspects the journal and proceedings records of a venue library file (see
:mod:`bibcc.venues`) for missing fields (publisher, ISSN, venue, and so
on).  A proceedings record also has the fields of its family record, so a
field that the family supplies is never missing.  The check also lists the
family records, compares the editions of each conference with one another,
reports fields that one edition defines and another lacks, and suggests
moving the fields that every edition shares into a family record.

Usage:
    from bibcc.checkers.template_fields import check_template_fields

    check_template_fields(Path("venues.yaml"), ["publisher", "issn"], ["venue"])
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence, Tuple

from bibcc.logging_utils import SEPARATOR_LIGHT, SEPARATOR_WIDTH
from bibcc.venues import EVENT_FIELDS, Venue, VenueLibrary, edition_group, family_label

DEFAULT_JOURNAL_FIELDS = ["publisher", "issn"]
DEFAULT_PROCEEDINGS_FIELDS = ["venue", "publisher", "month"]

# Fields that differ from one edition to the next by nature, so sharing them isn't a family trait.
_PER_EDITION = set(EVENT_FIELDS) | {"editor", "isbn", "volume", "day"}


def _norm_value(value: str) -> str:
    """Braces, case, and whitespace don't matter when comparing field values."""
    return " ".join(value.replace("{", "").replace("}", "").split()).casefold()


def _editions(library: VenueLibrary) -> Dict[str, List[Venue]]:
    groups: Dict[str, List[Venue]] = {}
    for venue in library.proceedings:
        groups.setdefault(edition_group(library, venue.name), []).append(venue)
    return groups


def check_edition_consistency(library: VenueLibrary, log: Callable[[str], None]) -> None:
    """Report fields that one edition of a venue defines and another lacks.

    Editions of the same conference (grouped by
    :func:`bibcc.venues.edition_group`: their family record, else the name
    without years and ordinals) should define the same fields.  A field that
    the family record supplies counts for every edition.  When every edition
    that has a field agrees on its value, the report suggests that value for
    the editions that lack it, and when every edition has the same value,
    it suggests moving the field into a family record.  A record still named
    by its interim (CVF or OpenReview) booktitle describes proceedings that
    aren't out yet, so only its event fields count as missing.
    """
    # Imported here: bibcc.official imports this package.
    from bibcc.official import interim_source_of

    log("\n🔗 Cross-edition consistency (fields one edition has and another lacks):")
    found = False
    moves: List[str] = []
    for editions in (e for _, e in sorted(_editions(library).items()) if len(e) > 1):
        editions.sort(key=lambda venue: str(venue.year))
        family = library.family_of_record(editions[0])
        interim = {
            str(v.year) for v in editions if interim_source_of(v.name, year=str(v.year), library=library)
        }
        published = [v for v in editions if str(v.year) not in interim]
        label = family.label if family is not None else family_label((published or editions)[-1].name)
        effective = [(str(v.year), library.fields_of(v)) for v in editions]
        all_fields = sorted({f for _, fields in effective for f in fields})
        for fname in all_fields:
            have = [(year, fields[fname]) for year, fields in effective if fields.get(fname)]
            lack = [
                year for year, fields in effective
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
        shared = {}
        for fname in sorted({f for v in published for f in v.fields} - _PER_EDITION):
            values = {_norm_value(v.fields.get(fname, "")) for v in published}
            if len(published) > 1 and len(values) == 1 and "" not in values:
                shared[fname] = published[-1].fields[fname]
        if family is not None:
            shared = {k: v for k, v in shared.items() if k not in family.fields}
            for venue in editions:
                for fname, value in venue.fields.items():
                    if fname in family.fields and _norm_value(value) != _norm_value(family.fields[fname]):
                        log(f"  ℹ️  {label}: {venue.year} overrides the family's '{fname}' "
                            f"('{family.fields[fname]}') with '{value}'")
        if shared:
            pairs = ", ".join(f"{k}: '{v}'" for k, v in shared.items())
            target = f"the family record {family.label}" if family is not None else "a family record"
            moves.append(f"  💡 {label}: every edition has {pairs}; move it into {target}")
    if not found:
        log("  ✅ Editions of the same venue define the same fields.")
    if moves:
        log("\n🧩 Fields that every edition shares (a family record supplies them to each edition):")
        for line in moves:
            log(line)


def _log_families(library: VenueLibrary, log: Callable[[str], None]) -> None:
    if not library.families:
        return
    groups = _editions(library)
    log(f"\n👪 Family records ({len(library.families)}):")
    for family in sorted(library.families, key=lambda f: f.label.casefold()):
        editions = []
        for venues in groups.values():
            if venues and library.family_of_record(venues[0]) is family:
                editions = sorted(str(v.year) for v in venues)
        schema = (f"schema: {', '.join(family.entry_fields)}" if family.entry_fields
                  else "no schema yet (bibcc check official FILE --learn)")
        years = f"editions {', '.join(editions)}" if editions else "no editions in the library"
        log(f"  • {family.label}: {years}; {schema}")


def check_template_fields(
    templates_path: Path,
    journal_fields: Sequence[str],
    proceedings_fields: Sequence[str],
    log: Optional[Callable[[str], None]] = None,
) -> None:
    """Check the records of a venue library for missing fields.

    Args:
        templates_path: Path to the venue library YAML.
        journal_fields: Fields to require in journal records.
        proceedings_fields: Fields to require in proceedings records, which
            also have the fields of their family record.
        log: Optional logging callback; falls back to ``print``.
    """
    log = log or print

    try:
        library = VenueLibrary.load(templates_path)
    except Exception as e:
        log(f"❌ Error loading venue library {templates_path}: {e}")
        return

    journal_templates: Dict[str, Dict] = {v.name: v.fields for v in library.journals}
    proceedings_templates: Dict[Tuple[str, str], Dict] = {
        (v.name, str(v.year)): library.fields_of(v) for v in library.proceedings
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
            missing = [f for f in proceedings_fields if f not in fields or not fields[f]]
            if missing:
                proceedings_issues.append(((venue, year), missing))
                display = f"({venue[:50]}, {year})"
                log(f"{display:<70} | {', '.join(missing)}")

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

    _log_families(library, log)
    check_edition_consistency(library, log)
