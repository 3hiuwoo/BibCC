from __future__ import annotations

import argparse
import re
from pathlib import Path
from typing import Dict, List, Tuple

import bibtexparser

from templates import TEMPLATES


def normalize_text(text):
    if not text:
        return ""
    return text.replace("{", "").replace("}", "").strip().lower()


def _write_log(path: Path, header: str, rows: List[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    content = [header]
    content.extend(rows if rows else ["(none)"])
    path.write_text("\n".join(content) + "\n", encoding="utf-8")


def main(
    input_path: str,
    output_path: str,
    dry_run: bool = False,
    log_dir: Path | None = None,
):
    print(f"Reading {input_path}...")

    # --- PASS 1: THE BRAIN ---
    # Parse strictly to understand the data (Which ID belongs to which Venue?)
    with open(input_path, "r", encoding="utf-8") as f:
        parser = bibtexparser.bparser.BibTexParser(common_strings=True)
        bib_db = bibtexparser.load(f, parser=parser)

    # Create a "Patch List": { "ENTRY_ID": { "field": "value", ... } }
    patches: Dict[str, Dict[str, str]] = {}
    conflicts: Dict[str, List[Tuple[str, str, str]]] = {}
    # Map normalized (venue, year) -> first-seen raw (venue, year) for unique reporting
    missing_templates: Dict[Tuple[str, str], Tuple[str, str]] = {}

    for entry in bib_db.entries:
        entry_id = entry["ID"]
        year = entry.get("year")
        venue_raw = entry.get("booktitle") or entry.get("journal")

        if not year or not venue_raw:
            key = (normalize_text(venue_raw or ""), normalize_text(year or ""))
            missing_templates.setdefault(key, (venue_raw or "", year or ""))
            continue

        # Find matching template
        clean_venue = normalize_text(venue_raw)
        clean_year = normalize_text(year)

        matched_template = None
        for (tmpl_venue, tmpl_year), meta_data in TEMPLATES.items():
            if (
                normalize_text(tmpl_venue) == clean_venue
                and normalize_text(tmpl_year) == clean_year
            ):
                matched_template = meta_data
                break

        if not matched_template:
            key = (clean_venue, clean_year)
            missing_templates.setdefault(key, (venue_raw, year))
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

    print(f" identified {len(patches)} entries to patch.")

    # Prepare log paths (all under log_dir)
    log_dir = log_dir or Path(".")
    log_dir.mkdir(parents=True, exist_ok=True)
    base = Path(input_path).name
    conflict_log = log_dir / f"{base}.conflicts.txt"
    missing_log = log_dir / f"{base}.missing_templates.txt"

    # Collect log rows
    conflict_rows: List[str] = []
    for eid, rows in conflicts.items():
        for k, existing_val, tmpl_val in rows:
            conflict_rows.append(
                f"{eid}\t{k}\tEXISTING={existing_val}\tTEMPLATE={tmpl_val}"
            )

    missing_rows: List[str] = []
    for venue_raw, year in missing_templates.values():
        missing_rows.append(f"{venue_raw}\t{year}")

    # Dry-run summary
    if dry_run:
        if patches:
            print("\n🧪 Dry-run additions:")
            for eid, fields in patches.items():
                print(f"Entry ID: {eid}")
                for k, v in fields.items():
                    print(f"    add {k} = {{{v}}}")
        else:
            print("\n🧪 Dry-run: no additions needed.")

        if conflicts:
            print(
                "\n⚠️  Conflicts (existing value differs from template, not overwritten):"
            )
            for eid, conflicts_fields in conflicts.items():
                print(f"Entry ID: {eid}")
                for k, existing_val, tmpl_val in conflicts_fields:
                    print(
                        f"  field '{k}': existing='{existing_val}', template='{tmpl_val}'"
                    )
        else:
            print("\n✅ No conflicts detected.")

        if missing_templates:
            print(
                "\nℹ️  Missing (venue, year) combinations not in templates (deduplicated):"
            )
            for venue_raw, year in missing_templates.values():
                print(f"  venue='{venue_raw}' year='{year}'")
        else:
            print("\n✅ All entries matched existing templates.")

        _write_log(
            conflict_log,
            "conflicts: entry_id\tfield\texisting\ttemplate",
            conflict_rows,
        )
        _write_log(missing_log, "missing templates: venue\tyear", missing_rows)
        print(f"\nLogs saved: {conflict_log}, {missing_log}")
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

    print(f"✅ Done! Saved to {output_path} (Comments preserved)")


if __name__ == "__main__":
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
        help="Directory to write logs (conflicts/missing). Default: current directory.",
    )
    args = parser.parse_args()

    dry_run = not bool(args.output)
    log_dir = Path(args.log_dir) if args.log_dir else None

    # If dry-run and no output given, still run and emit logs
    main(
        args.input,
        args.output or args.input,
        dry_run=dry_run,
        log_dir=log_dir,
    )
