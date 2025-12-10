import argparse
import re

import bibtexparser

from templates import TEMPLATES


def normalize_text(text):
    if not text:
        return ""
    return text.replace("{", "").replace("}", "").strip().lower()


def main(input_path, output_path):
    print(f"Reading {input_path}...")

    # --- PASS 1: THE BRAIN ---
    # Parse strictly to understand the data (Which ID belongs to which Venue?)
    with open(input_path, "r", encoding="utf-8") as f:
        parser = bibtexparser.bparser.BibTexParser(common_strings=True)
        bib_db = parser.parse_file(f)

    # Create a "Patch List": { "ENTRY_ID": { "field": "value", ... } }
    patches = {}

    for entry in bib_db.entries:
        entry_id = entry["ID"]
        year = entry.get("year")
        venue_raw = entry.get("booktitle") or entry.get("journal")

        if not year or not venue_raw:
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

        # Determine which fields need to be ADDED (don't overwrite existing)
        if matched_template:
            fields_to_add = {}
            for k, v in matched_template.items():
                if k not in entry:
                    fields_to_add[k] = v

            if fields_to_add:
                patches[entry_id] = fields_to_add

    print(f" identified {len(patches)} entries to patch.")

    # --- PASS 2: THE SURGEON ---
    # Read the file as plain text lines to preserve comments
    with open(input_path, "r", encoding="utf-8") as f:
        lines = f.readlines()

    with open(output_path, "w", encoding="utf-8") as f:
        for line in lines:
            # write the original line first (always preserve)
            f.write(line)

            # Check if this line is the start of an entry we need to patch
            # Regex looks for: @type{ID,
            match = re.search(r"@\w+\s*\{\s*([^,]+),", line)

            if match:
                current_id = match.group(1).strip()

                # If this ID is in our patch list, inject the new fields right here
                if current_id in patches:
                    new_data = patches[current_id]

                    # Inject fields nicely formatted
                    for key, val in new_data.items():
                        # We use 2 spaces indentation to match typical styles
                        # You can adjust whitespace here if you prefer tabs
                        f.write(f"  {key:<12} = {{{val}}},\n")

                    # Remove from patches so we don't add it twice if ID appears twice (rare error)
                    del patches[current_id]

    print(f"✅ Done! Saved to {output_path} (Comments preserved)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Enhance a BibTeX (.bib) file by adding missing metadata fields from templates."
    )
    parser.add_argument("input", type=str, help="Path to the input BibTeX (.bib) file")
    parser.add_argument(
        "output", type=str, help="Path to save the output enhanced BibTeX (.bib) file"
    )
    args = parser.parse_args()
    main(args.input, args.output)
