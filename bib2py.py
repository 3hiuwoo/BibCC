from __future__ import annotations

import argparse
import importlib.util
from pathlib import Path
from typing import Dict, List, Tuple

import bibtexparser

EXCLUDED_KEYS = {
    "ID",
    "ENTRYTYPE",
    "year",
    "booktitle",
    "journal",
    "title",
    "author",
    "pages",
    "volume",
    "url",
    "doi",
    "pdf",
    "numpages",
    "articleno",
    "number",
    "note",
}


def normalize_text(text: str) -> str:
    if not text:
        return ""
    return text.replace("{", "").replace("}", "").strip().lower()


def load_templates_dict(path: Path) -> Dict[Tuple[str, str], Dict[str, str]]:
    spec = importlib.util.spec_from_file_location("templates", path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load module spec from {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return getattr(mod, "TEMPLATES", {})


def render_entry(venue: str, year: str, meta: Dict[str, str]) -> str:
    lines = [f'    ("{venue}", "{year}"): {{']
    for k, v in meta.items():
        clean_val = v.replace("\n", " ").replace("\r", "").strip()
        lines.append(f'        "{k}": {repr(clean_val)},')
    lines.append("    },")
    return "\n".join(lines)


def _year_value(year_str: str) -> int:
    digits = "".join(ch for ch in str(year_str) if ch.isdigit())
    if not digits:
        return -1
    try:
        return int(digits)
    except ValueError:
        return -1


def bib2py(input_file: str, update: bool, templates_path: Path) -> None:
    with open(input_file, "r", encoding="utf-8") as bibtex_file:
        parser = bibtexparser.bparser.BibTexParser(common_strings=True)
        bib_database = bibtexparser.load(bibtex_file, parser=parser)

    existing = load_templates_dict(templates_path)
    norm_index = {
        (normalize_text(kv[0]), normalize_text(kv[1])): kv for kv in existing.keys()
    }

    new_snippets: List[str] = []  # only used when not updating directly
    update_snippets: List[str] = []
    added = 0
    skipped_missing = 0
    skipped_existing = 0
    updated_existing = 0

    for entry in bib_database.entries:
        venue = entry.get("booktitle") or entry.get("journal")
        year = entry.get("year")

        if not venue or not year:
            print(
                f"!Skipped '{entry.get('ID', 'unknown')}': Missing year or venue name."
            )
            skipped_missing += 1
            continue

        norm_key = (normalize_text(venue), normalize_text(year))

        meta = {k: v for k, v in entry.items() if k not in EXCLUDED_KEYS}

        match_key = norm_index.get(norm_key)

        if match_key:
            tpl = existing[match_key]
            merged = dict(tpl)
            missing_fields = []
            differing_fields = []

            for mk, mv in meta.items():
                if mk not in merged:
                    merged[mk] = mv
                    missing_fields.append(mk)
                else:
                    if normalize_text(merged[mk]) != normalize_text(mv):
                        merged[mk] = mv  # prefer new value
                        differing_fields.append(mk)

            if missing_fields or differing_fields:
                existing[match_key] = merged
                update_snippets.append(render_entry(venue, year, merged))
                updated_existing += 1
            else:
                skipped_existing += 1
        else:
            existing[(venue, year)] = meta
            new_snippets.append(render_entry(venue, year, meta))
            norm_index[norm_key] = (venue, year)
            added += 1

    if not update:
        print("ℹ️ New templates:\n")
        for s in new_snippets:
            print(s + "\n")
        print("⚠️ Updated templates:\n")
        for s in update_snippets:
            print(s + "\n")
        print(
            f"Summary: new={added}, skipped_missing={skipped_missing}, skipped_existing={skipped_existing}, existing_updated={updated_existing}"
        )

    if update:
        # Overwrite templates.py with updated/merged dictionary (sorted reverse-chronologically)
        text = templates_path.read_text(encoding="utf-8")
        backup = templates_path.with_suffix(templates_path.suffix + ".bak")
        backup.write_text(text, encoding="utf-8")

        sorted_items = sorted(
            existing.items(),
            key=lambda item: (-_year_value(item[0][1]), item[0][0].lower()),
        )

        lines = ["TEMPLATES = {"]
        for (venue, year), meta in sorted_items:
            lines.append(f'    ("{venue}", "{year}"): {{')
            for k, v in meta.items():
                clean_val = str(v).replace("\n", " ").replace("\r", "").strip()
                lines.append(f'        "{k}": {repr(clean_val)},')
            lines.append("    },")
            lines.append("")
        lines.append("}")
        templates_path.write_text("\n".join(lines), encoding="utf-8")
        print(f"✅ templates updated (backup: {backup})")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Convert BibTeX entries to Python dictionary format for templates.py"
    )
    parser.add_argument("input", type=str, help="Path to the input BibTeX (.bib) file")
    parser.add_argument(
        "--update",
        action="store_true",
        help="Append new templates directly into templates.py (skip existing keys).",
    )
    parser.add_argument(
        "--templates-path",
        type=str,
        default="templates.py",
        help="Path to templates.py (default: templates.py)",
    )
    args = parser.parse_args()

    try:
        bib2py(args.input, update=args.update, templates_path=Path(args.templates_path))
    except FileNotFoundError:
        print("Error: bib file or templates file not found.")
