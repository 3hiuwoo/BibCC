"""
YAML-based template update tool for BibCC.

This replaces the old workflow of:
  1. completer.py reports missing combos
  2. User collects BibTeX entries manually
  3. bib2py.py converts BibTeX to templates

New workflow:
  1. completer.py reports missing combos AND generates a YAML file with required fields
  2. User fills in the YAML file directly
  3. yaml2templates.py updates templates.py from the filled YAML

Usage:
  python yaml2templates.py missing_templates.yaml --update
"""

from __future__ import annotations

import argparse
import importlib.util
from pathlib import Path
from typing import Any, Dict, List, Tuple

import yaml


def load_templates_module(
    path: Path,
) -> Tuple[Dict[str, Dict], Dict[Tuple[str, str], Dict]]:
    """Load JOURNAL_TEMPLATES and PROCEEDINGS_TEMPLATES from templates file."""
    spec = importlib.util.spec_from_file_location("templates", path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load module spec from {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    journal_templates = getattr(mod, "JOURNAL_TEMPLATES", {})
    proceedings_templates = getattr(mod, "PROCEEDINGS_TEMPLATES", {})

    return journal_templates, proceedings_templates


def normalize_text(text: str) -> str:
    """Normalize text for comparison."""
    if not text:
        return ""
    return text.replace("{", "").replace("}", "").strip().lower()


def _year_value(year_str: str) -> int:
    """Extract numeric year value for sorting."""
    digits = "".join(ch for ch in str(year_str) if ch.isdigit())
    if not digits:
        return -1
    try:
        return int(digits)
    except ValueError:
        return -1


def load_yaml_templates(yaml_path: Path) -> List[Dict[str, Any]]:
    """Load template entries from YAML file."""
    with open(yaml_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    if data is None:
        return []

    # Support both list format and dict format
    if isinstance(data, list):
        return data
    elif isinstance(data, dict) and "templates" in data:
        return data["templates"]
    else:
        raise ValueError(
            "YAML file must contain a list of templates or a 'templates' key"
        )


def render_journal_templates(journals: Dict[str, Dict]) -> str:
    """Render JOURNAL_TEMPLATES section."""
    lines = ["JOURNAL_TEMPLATES = {"]

    # Sort alphabetically by journal name
    for name in sorted(journals.keys()):
        fields = journals[name]
        lines.append(f'    "{name}": {{')
        for k, v in fields.items():
            clean_val = str(v).replace("\n", " ").replace("\r", "").strip()
            lines.append(f'        "{k}": {repr(clean_val)},')
        lines.append("    },")
        lines.append("")

    lines.append("}")
    return "\n".join(lines)


def render_proceedings_templates(proceedings: Dict[Tuple[str, str], Dict]) -> str:
    """Render PROCEEDINGS_TEMPLATES section."""
    lines = ["PROCEEDINGS_TEMPLATES = {"]

    # Sort by year descending, then by name
    sorted_items = sorted(
        proceedings.items(),
        key=lambda item: (-_year_value(item[0][1]), item[0][0].lower()),
    )

    for (venue, year), fields in sorted_items:
        lines.append(f'    ("{venue}", "{year}"): {{')
        for k, v in fields.items():
            clean_val = str(v).replace("\n", " ").replace("\r", "").strip()
            lines.append(f'        "{k}": {repr(clean_val)},')
        lines.append("    },")
        lines.append("")

    lines.append("}")
    return "\n".join(lines)


def write_templates_file(
    path: Path,
    journal_templates: Dict[str, Dict],
    proceedings_templates: Dict[Tuple[str, str], Dict],
) -> None:
    """Write the complete templates.py file."""

    header = '''"""
Optimized Template Structure for BibCC

Templates are separated into two categories:
1. JOURNAL_TEMPLATES - Year-agnostic (journals have consistent metadata across years)
2. PROCEEDINGS_TEMPLATES - Year-specific (conferences vary by year: venue, isbn, editor, etc.)

This eliminates redundancy where the same journal was repeated for each year with identical fields.
"""

'''

    content = (
        header
        + "# Journal templates are keyed by journal name only (no year)\n"
        + "# These fields are constant across all years for a given journal\n"
        + render_journal_templates(journal_templates)
        + "\n\n\n"
        + "# Proceedings templates are keyed by (venue_name, year) tuple\n"
        + "# These fields vary by year: venue location, isbn, editor, month, etc.\n"
        + render_proceedings_templates(proceedings_templates)
        + "\n"
    )

    path.write_text(content, encoding="utf-8")


def yaml2templates(
    yaml_path: Path,
    templates_path: Path,
    update: bool = False,
    dry_run: bool = True,
) -> None:
    """Convert YAML template definitions to Python templates file."""

    # Load existing templates
    try:
        journal_templates, proceedings_templates = load_templates_module(templates_path)
    except (ImportError, FileNotFoundError):
        print(
            f"⚠️  Could not load existing templates from {templates_path}, starting fresh."
        )
        journal_templates = {}
        proceedings_templates = {}

    # Load YAML entries
    yaml_entries = load_yaml_templates(yaml_path)

    if not yaml_entries:
        print("ℹ️  No entries found in YAML file.")
        return

    added_journals = 0
    added_proceedings = 0
    updated_journals = 0
    updated_proceedings = 0
    skipped = 0

    for entry in yaml_entries:
        venue = entry.get("venue", "").strip()
        year = entry.get("year", "").strip()
        entry_type = entry.get("type", "proceedings").lower()
        fields = entry.get("fields", {})

        if not venue:
            print(f"⚠️  Skipping entry with missing venue: {entry}")
            skipped += 1
            continue

        # Remove empty fields
        fields = {k: v for k, v in fields.items() if v and str(v).strip()}

        if entry_type == "journal":
            # Journal: keyed by name only
            norm_venue = normalize_text(venue)
            existing_key = None
            for key in journal_templates:
                if normalize_text(key) == norm_venue:
                    existing_key = key
                    break

            if existing_key:
                # Update existing
                old_fields = journal_templates[existing_key]
                merged = dict(old_fields)
                merged.update(fields)
                if merged != old_fields:
                    journal_templates[existing_key] = merged
                    updated_journals += 1
                    print(f"📝 Updated journal: {existing_key}")
                else:
                    print(f"⏭️  Journal unchanged: {existing_key}")
            else:
                # Add new
                journal_templates[venue] = fields
                added_journals += 1
                print(f"➕ Added journal: {venue}")

        else:
            # Proceedings: keyed by (venue, year)
            if not year:
                print(f"⚠️  Skipping proceedings entry with missing year: {venue}")
                skipped += 1
                continue

            norm_key = (normalize_text(venue), normalize_text(year))
            existing_key = None
            for key in proceedings_templates:
                if (normalize_text(key[0]), normalize_text(key[1])) == norm_key:
                    existing_key = key
                    break

            if existing_key:
                # Update existing
                old_fields = proceedings_templates[existing_key]
                merged = dict(old_fields)
                merged.update(fields)
                if merged != old_fields:
                    proceedings_templates[existing_key] = merged
                    updated_proceedings += 1
                    print(f"📝 Updated proceedings: {existing_key}")
                else:
                    print(f"⏭️  Proceedings unchanged: {existing_key}")
            else:
                # Add new
                proceedings_templates[(venue, year)] = fields
                added_proceedings += 1
                print(f"➕ Added proceedings: ({venue}, {year})")

    print(f"\n📊 Summary:")
    print(f"   Journals: +{added_journals} new, ~{updated_journals} updated")
    print(f"   Proceedings: +{added_proceedings} new, ~{updated_proceedings} updated")
    print(f"   Skipped: {skipped}")

    if dry_run and not update:
        print("\n🧪 Dry run - no files modified. Use --update to apply changes.")
        return

    if update:
        # Create backup
        if templates_path.exists():
            backup = templates_path.with_suffix(templates_path.suffix + ".bak")
            backup.write_text(
                templates_path.read_text(encoding="utf-8"), encoding="utf-8"
            )
            print(f"\n💾 Backup created: {backup}")

        # Write updated templates
        write_templates_file(templates_path, journal_templates, proceedings_templates)
        print(f"✅ Templates updated: {templates_path}")


def main():
    parser = argparse.ArgumentParser(
        description="Update templates from a YAML file containing venue/year/fields definitions."
    )
    parser.add_argument(
        "yaml_file",
        type=str,
        help="Path to the YAML file with template definitions.",
    )
    parser.add_argument(
        "--templates-path",
        type=str,
        default="templates.py",
        help="Path to templates file (default: templates.py)",
    )
    parser.add_argument(
        "--update",
        action="store_true",
        help="Actually update the templates file (default is dry-run).",
    )

    args = parser.parse_args()

    yaml2templates(
        yaml_path=Path(args.yaml_file),
        templates_path=Path(args.templates_path),
        update=args.update,
        dry_run=not args.update,
    )


if __name__ == "__main__":
    main()
