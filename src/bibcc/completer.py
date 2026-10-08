"""
BibTeX Completer - Enhanced version with new template structure support.

This module completes BibTeX entries by adding missing metadata fields from templates.
It supports the new optimized template structure that separates journals (year-agnostic)
from proceedings (year-specific).

New workflow for missing templates:
1. Run completer.py (this file) - generates YAML file with missing combos
2. User fills in the YAML file directly with required fields
3. Run yaml2templates.py to update templates from the filled YAML
"""

from __future__ import annotations

import argparse
import re
from collections import Counter
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import bibtexparser

from bibcc.logging_utils import Logger, get_output_dir, write_report
from bibcc.templates import JOURNAL_TEMPLATES, PROCEEDINGS_TEMPLATES


def normalize_text(text: Optional[str]) -> str:
    """Normalize text for comparison by removing braces and lowercasing."""
    if not text:
        return ""
    return text.replace("{", "").replace("}", "").strip().lower()


# Publisher inference from venue name patterns
_PUBLISHER_PATTERNS: List[Tuple[str, str]] = [
    ("ieee", "IEEE"),
    ("acm", "Association for Computing Machinery"),
    ("springer", "Springer"),
    ("lecture notes", "Springer"),
    ("elsevier", "Elsevier"),
    ("aaai", "AAAI Press"),
    ("pmlr", "PMLR"),
    ("jmlr", "JMLR"),
    ("nature", "Springer Nature"),
    ("wiley", "Wiley"),
    ("mdpi", "MDPI"),
    ("oxford", "Oxford University Press"),
    ("cambridge", "Cambridge University Press"),
]

# Known conference month patterns
_CONFERENCE_MONTHS: Dict[str, str] = {
    "cvpr": "June",
    "iccv": "October",
    "eccv": "October",
    "neurips": "December",
    "nips": "December",
    "icml": "July",
    "iclr": "May",
    "aaai": "February",
    "ijcai": "August",
    "acl": "July",
    "emnlp": "November",
    "naacl": "June",
    "kdd": "August",
    "sigir": "July",
    "www": "May",
    "mm": "October",
    "interspeech": "September",
    "bmvc": "November",
    "wacv": "January",
    "miccai": "October",
    "coling": "October",
}


# Fields to collect from bib entries for pre-filling YAML templates
_JOURNAL_COLLECT_FIELDS = ["publisher", "issn", "address"]
_PROCEEDINGS_COLLECT_FIELDS = [
    "publisher",
    "month",
    "isbn",
    "issn",
    "editor",
    "series",
    "address",
]


def _guess_publisher(venue: str) -> str:
    """Infer publisher from venue name patterns. Returns empty string if unknown."""
    lower = venue.lower()
    for pattern, publisher in _PUBLISHER_PATTERNS:
        if pattern in lower:
            return publisher
    return ""


def _guess_month(venue: str) -> str:
    """Infer conference month from known conference name patterns."""
    lower = venue.lower()
    for pattern, month in _CONFERENCE_MONTHS.items():
        if pattern in lower:
            return month
    return ""


def _write_yaml_missing_templates(
    path: Path,
    missing_templates: Dict[Tuple[str, str], Tuple[str, str, str]],
    bib_collected: Optional[Dict[Tuple[str, str], Dict[str, str]]] = None,
) -> None:
    """
    Write missing templates to a YAML file for user to fill in.

    The YAML format allows users to directly specify fields without
    needing to collect BibTeX entries first. Fields are pre-filled from
    three sources (highest priority first):
      1. Values from existing bib entries (``# from bib``)
      2. Auto-guessed values from venue name patterns (``# auto-guessed``)
      3. Empty placeholder
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    bib_collected = bib_collected or {}

    lines = [
        "# Missing templates - fill in the 'fields' section for each entry",
        "# Then run: python yaml2templates.py {} --update".format(path.name),
        "#",
        "# Entry types:",
        '#   - "journal": For journal articles (year-agnostic, keyed by journal name)',
        '#   - "proceedings": For conference papers (year-specific)',
        "# Fields marked with '# auto-guessed' were inferred from the venue name.",
        "# Fields marked with '# from bib' were sourced from existing bib entries.",
        "",
        "templates:",
    ]

    for key, (venue_raw, year, entry_type) in missing_templates.items():
        # Escape backslashes for YAML double-quoted strings (e.g., \& -> \\&)
        venue_escaped = venue_raw.replace("\\", "\\\\")
        lines.append(f'  - venue: "{venue_escaped}"')
        lines.append(f'    year: "{year}"')
        lines.append(f"    type: {entry_type}")
        lines.append("    fields:")

        guessed_publisher = _guess_publisher(venue_raw)
        guessed_month = _guess_month(venue_raw) if entry_type != "journal" else ""
        collected = bib_collected.get(key, {})

        def _field_line(
            name: str, value: str, comment: str, commented_out: bool = False
        ) -> str:
            prefix = "# " if commented_out else ""
            return f'      {prefix}{name}: "{value}"{comment}'

        def _resolve(
            name: str, guessed: str = "", hint: str = "", commented_out: bool = False
        ) -> str:
            """Pick best value: bib > guessed > empty, with appropriate comment."""
            bib_val = collected.get(name, "")
            if bib_val:
                return _field_line(name, bib_val, "  # from bib", commented_out)
            if guessed:
                return _field_line(name, guessed, "  # auto-guessed", commented_out)
            comment = f"  {hint}" if hint else ""
            return _field_line(name, "", comment, commented_out)

        if entry_type == "journal":
            lines.append(
                _resolve(
                    "publisher", guessed_publisher, "# e.g., IEEE, Elsevier, Springer"
                )
            )
            lines.append(_resolve("issn"))
            lines.append(
                _resolve(
                    "address",
                    hint="# optional, e.g., New York, NY, USA",
                    commented_out=True,
                )
            )
        else:
            lines.append(_resolve("venue", hint="# e.g., City, Country"))
            lines.append(_resolve("publisher", guessed_publisher))
            lines.append(_resolve("month", guessed_month, "# e.g., June, October"))
            lines.append(_resolve("isbn", commented_out=True))
            lines.append(_resolve("issn", commented_out=True))
            lines.append(_resolve("editor", commented_out=True))
            lines.append(_resolve("series", commented_out=True))
            lines.append(_resolve("address", commented_out=True))
        lines.append("")

    path.write_text("\n".join(lines), encoding="utf-8")


def _detect_entry_type(entry: Dict[str, Any]) -> str:
    """Detect if an entry is a journal article or proceedings."""
    entry_type = entry.get("ENTRYTYPE", "").lower()

    # Article type is typically journal
    if entry_type == "article":
        return "journal"

    # Inproceedings is typically proceedings/conference
    if entry_type in ("inproceedings", "proceedings", "conference"):
        return "proceedings"

    # Check by field presence
    if entry.get("journal"):
        return "journal"
    if entry.get("booktitle"):
        return "proceedings"

    return "proceedings"  # default


def find_template(
    venue: str,
    year: str,
    entry_type: str,
) -> Optional[Dict[str, str]]:
    """
    Find matching template for a venue/year combination.

    For journals: looks up by venue name only (year-agnostic)
    For proceedings: looks up by (venue, year) tuple
    """
    clean_venue = normalize_text(venue)
    clean_year = normalize_text(year)

    if entry_type == "journal":
        # Journal lookup: by name only
        for tmpl_name, fields in JOURNAL_TEMPLATES.items():
            if normalize_text(tmpl_name) == clean_venue:
                return fields
    else:
        # Proceedings lookup: by (venue, year)
        for (tmpl_venue, tmpl_year), fields in PROCEEDINGS_TEMPLATES.items():
            if (
                normalize_text(tmpl_venue) == clean_venue
                and normalize_text(tmpl_year) == clean_year
            ):
                return fields
    return None


def main(
    input_path: str,
    output_path: str,
    dry_run: bool = False,
    log_dir: Path | None = None,
    log: Optional[Callable[[str], None]] = None,
):
    """Main entry point for the completer."""
    log = log or print
    log(f"Reading {input_path}...")
    log("📦 Using template structure (journals + proceedings)")

    # --- PASS 1: THE BRAIN ---
    # Parse to understand the data
    with open(input_path, "r", encoding="utf-8") as f:
        parser = bibtexparser.bparser.BibTexParser(common_strings=True)
        bib_db = bibtexparser.load(f, parser=parser)

    # Create a "Patch List": { "ENTRY_ID": { "field": "value", ... } }
    patches: Dict[str, Dict[str, str]] = {}
    conflicts: Dict[str, List[Tuple[str, str, str]]] = {}

    # Map normalized key -> (raw_venue, year, entry_type) for unique reporting
    missing_templates: Dict[Tuple[str, str], Tuple[str, str, str]] = {}

    # Collect field values from bib entries for pre-filling YAML templates.
    # key -> { field_name -> Counter of values }
    bib_field_counters: Dict[Tuple[str, str], Dict[str, Counter]] = {}

    # Incomplete entries: missing year or venue (e.g., arxiv misc)
    # These are reported separately and do NOT contribute to the YAML file
    incomplete_entries: List[Tuple[str, str, str]] = []  # (entry_id, venue, year)

    for entry in bib_db.entries:
        entry_id = entry["ID"]
        year = entry.get("year", "")
        venue_raw = entry.get("booktitle") or entry.get("journal") or ""
        entry_type = _detect_entry_type(entry)

        if not year or not venue_raw:
            # Incomplete entry - missing year or venue, likely arxiv/misc
            incomplete_entries.append((entry_id, venue_raw, year))
            continue

        # Find matching template
        clean_venue = normalize_text(venue_raw)
        clean_year = normalize_text(year)

        matched_template = find_template(venue_raw, year, entry_type)

        if not matched_template:
            # For journals, key is venue only (year-agnostic)
            # For proceedings, key is (venue, year)
            if entry_type == "journal":
                key = (clean_venue, "")  # journals are year-agnostic
            else:
                key = (clean_venue, clean_year)
            missing_templates.setdefault(key, (venue_raw, year, entry_type))

            # Collect existing field values from this entry
            collect_fields = (
                _JOURNAL_COLLECT_FIELDS
                if entry_type == "journal"
                else _PROCEEDINGS_COLLECT_FIELDS
            )
            counters = bib_field_counters.setdefault(key, {})
            for fname in collect_fields:
                val = entry.get(fname, "").strip()
                if val:
                    counters.setdefault(fname, Counter())[val] += 1
            continue

        fields_to_add = {}
        conflicts_to_add = []
        for k, v in matched_template.items():
            if k not in entry:
                fields_to_add[k] = v
            else:
                existing_val = entry.get(k, "")
                if normalize_text(existing_val) != normalize_text(v):
                    conflicts_to_add.append((k, existing_val, v))

        if fields_to_add:
            patches[entry_id] = fields_to_add
        if conflicts_to_add:
            conflicts[entry_id] = conflicts_to_add

    log(f"  Identified {len(patches)} entries to patch.")

    output_dir = get_output_dir(input_path, log_dir)
    base = Path(input_path).name
    conflict_log = output_dir / f"{base}.conflicts.txt"
    missing_txt_log = output_dir / f"{base}.missing_templates.txt"
    missing_yaml_log = output_dir / f"{base}.missing_templates.yaml"

    # Collect log rows
    conflict_rows: List[str] = []
    for eid, rows in conflicts.items():
        for k, existing_val, tmpl_val in rows:
            conflict_rows.append(
                f"{eid}\t{k}\tEXISTING={existing_val}\tTEMPLATE={tmpl_val}"
            )

    missing_rows: List[str] = []
    for venue_raw, year, entry_type in missing_templates.values():
        missing_rows.append(f"{venue_raw}\t{year}\t{entry_type}")

    incomplete_rows: List[str] = []
    for entry_id, venue, year in incomplete_entries:
        incomplete_rows.append(
            f"{entry_id}\tvenue={venue or '(empty)'}\tyear={year or '(empty)'}"
        )

    # Dry-run summary
    if dry_run:
        if patches:
            log("\n🧪 Dry-run additions:")
            for eid, fields in patches.items():
                log(f"Entry ID: {eid}")
                for k, v in fields.items():
                    log(f"    add {k} = {{{v}}}")
        else:
            log("\n🧪 Dry-run: no additions needed.")

        if conflicts:
            log(
                "\n⚠️  Conflicts (existing value differs from template, not overwritten):"
            )
            for eid, conflicts_fields in conflicts.items():
                log(f"Entry ID: {eid}")
                for k, existing_val, tmpl_val in conflicts_fields:
                    log(
                        f"  field '{k}': existing='{existing_val}', template='{tmpl_val}'"
                    )
        else:
            log("\n✅ No conflicts detected.")

        if incomplete_entries:
            log(
                "\n📭 Incomplete entries (missing year or venue, e.g., arxiv/misc) - skipped:"
            )
            for entry_id, venue, year in incomplete_entries:
                log(
                    f"  🔸 {entry_id}: venue='{venue or '(empty)'}' year='{year or '(empty)'}'"
                )

        if missing_templates:
            log(
                "\nℹ️  Missing (venue, year) combinations not in templates (deduplicated):"
            )
            for venue_raw, year, entry_type in missing_templates.values():
                type_icon = "📰" if entry_type == "journal" else "📋"
                log(f"  {type_icon} [{entry_type}] venue='{venue_raw}' year='{year}'")
        else:
            log("\n✅ All complete entries matched existing templates.")

        # Write logs
        write_report(
            conflict_log,
            "conflicts: entry_id\tfield\texisting\ttemplate",
            conflict_rows,
        )
        write_report(
            missing_txt_log,
            "missing templates: venue\tyear\ttype",
            missing_rows,
        )

        # Write incomplete entries log
        incomplete_log = output_dir / f"{base}.incomplete_entries.txt"
        write_report(
            incomplete_log,
            "incomplete entries (missing year or venue): entry_id\tvenue\tyear",
            incomplete_rows,
        )

        # Write YAML file for missing templates (new workflow!)
        # Only include entries with both venue and year (not incomplete ones)
        if missing_templates:
            # Flatten counters to most-common values
            bib_collected: Dict[Tuple[str, str], Dict[str, str]] = {}
            for tkey, field_counters in bib_field_counters.items():
                bib_collected[tkey] = {
                    fname: counter.most_common(1)[0][0]
                    for fname, counter in field_counters.items()
                }
            _write_yaml_missing_templates(
                missing_yaml_log, missing_templates, bib_collected
            )
            log(f"\n📝 YAML template file created: {missing_yaml_log}")
            log(
                "   Fill in the fields and run: python yaml2templates.py {} --update".format(
                    missing_yaml_log
                )
            )

        log(f"\nLogs saved: {conflict_log}, {missing_txt_log}, {incomplete_log}")
        return

    # --- PASS 2: THE SURGEON ---
    # Read the file as plain text lines to preserve comments
    with open(input_path, "r", encoding="utf-8") as f:
        lines = f.readlines()

    with open(output_path, "w", encoding="utf-8") as f:
        for line in lines:
            f.write(line)

            match = re.search(r"@\w+\s*\{\s*([^,]+),", line)

            if match:
                current_id = match.group(1).strip()

                if current_id in patches:
                    new_data = patches[current_id]

                    for key, val in new_data.items():
                        f.write(f"  {key:<12} = {{{val}}},\n")

                    del patches[current_id]

    log(f"✅ Done! Saved to {output_path} (Comments preserved)")


def build_parser() -> argparse.ArgumentParser:
    """Build argument parser for BibTeX completer."""
    parser = argparse.ArgumentParser(
        description="Enhance a BibTeX (.bib) file by adding missing metadata fields from templates."
    )
    parser.add_argument("input", type=str, help="Path to the input BibTeX (.bib) file")
    parser.add_argument(
        "--output",
        type=str,
        default="",
        help="Path to save the output enhanced BibTeX (.bib) file (omit for dry-run).",
    )
    parser.add_argument(
        "--log-dir",
        type=str,
        default="",
        help="Directory to write logs and reports. Default: .bibcc/ next to the input file.",
    )
    parser.add_argument(
        "--update-templates",
        action="store_true",
        help="After YAML generation, invoke yaml2templates to update templates.py "
        "and re-run completion. Requires that the YAML file has been filled in.",
    )
    return parser


def run(args: argparse.Namespace) -> None:
    """Run completer with parsed arguments."""
    dry_run = not bool(args.output)
    log_dir = Path(args.log_dir) if args.log_dir else None

    with Logger("completer", input_file=args.input, log_dir=log_dir) as logger:
        main(
            args.input,
            args.output or args.input,
            dry_run=dry_run,
            log_dir=log_dir,
            log=logger.log,
        )

        # If --update-templates is set, invoke yaml2templates on the generated YAML
        if args.update_templates:
            from bibcc.yaml2templates import yaml2templates as y2t

            base = Path(args.input).name
            yaml_path = get_output_dir(args.input, log_dir) / f"{base}.missing_templates.yaml"
            templates_path = Path(__file__).parent / "templates.py"

            if not yaml_path.exists():
                logger.log("\nℹ️  No missing_templates.yaml found — nothing to update.")
            else:
                logger.log(f"\n🔄 Updating templates from {yaml_path}...")
                y2t(
                    yaml_path=yaml_path,
                    templates_path=templates_path,
                    update=True,
                    dry_run=False,
                )
                logger.log("✅ Templates updated.")

                # Re-run completion if output was requested
                if args.output:
                    logger.log(f"\n🔄 Re-running completion with updated templates...")
                    # Force reload of templates module
                    import importlib
                    from bibcc import templates as _tpl_mod

                    importlib.reload(_tpl_mod)

                    main(
                        args.input,
                        args.output,
                        dry_run=False,
                        log_dir=log_dir,
                        log=logger.log,
                    )


if __name__ == "__main__":
    parser = build_parser()
    args = parser.parse_args()
    run(args)
