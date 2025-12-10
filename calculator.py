import argparse

import bibtexparser

from templates import TEMPLATES


def list_templates(input_file):
    try:
        with open(input_file, "r", encoding="utf-8") as bibtex_file:
            parser = bibtexparser.bparser.BibTexParser(common_strings=True)
            bib_database = parser.parse_file(bibtex_file)
    except FileNotFoundError:
        print(f"Error: Could not find '{input_file}'.")
        return

    # Use a set to store unique combinations of (Year, Venue)
    # We store the "raw" version for display, but use a normalized version to check for duplicates
    unique_combinations = {}

    print(f"Scanning {len(bib_database.entries)} entries for venue info...\n")

    for entry in bib_database.entries:
        # 1. Get Fields
        year = entry.get("year")
        venue = entry.get("booktitle") or entry.get("journal") or entry.get("publisher")

        if not year or not venue:
            print(
                f'!Skipped entry "{entry.get("ID", "unknown")}": Missing year or venue name.'
            )
            continue

        # 2. Normalize for Uniqueness Check (ignore case and braces)
        # This ensures "NeurIPS" and "{NeurIPS}" don't show up twice
        norm_key = (
            year.strip(),
            venue.strip().lower(),
        )

        # 3. Store the cleanest looking version found (removing outer braces)
        clean_venue = venue.strip()
        clean_year = year.strip()

        # We only save it if we haven't seen this venue/year combo before
        if norm_key not in unique_combinations:
            unique_combinations[norm_key] = (clean_venue, clean_year)

    # --- OUTPUT ---
    print("--- Templates Checklist (Sorted by Year) ---")
    print("Copy lines below into your templates.py file:\n")

    # Sort by Year (descending), then by Venue Name (alphabetical)
    sorted_keys = sorted(
        unique_combinations.keys(), key=lambda x: (x[0], x[1]), reverse=True
    )

    current_year = ""
    for key in sorted_keys:
        real_venue, real_year = unique_combinations[key]

        # Print a header when the year changes
        if real_year != current_year:
            print(f"\n# --- {real_year} ---")
            current_year = real_year

        # Print the formatted Python Key
        print(f'    ("{real_venue}", "{real_year}"): {{}},')

    print(f"\nFound {len(unique_combinations)} unique (Venue, Year) combinations.")

    # Print combinations not in TEMPLATES
    print("\n--- Missing from templates.py ---")
    missing_count = 0
    for key in sorted_keys:
        real_venue, real_year = unique_combinations[key]
        if (real_venue, real_year) not in TEMPLATES:
            print(f'("{real_venue}", "{real_year}")')
            missing_count += 1

    print(f"\nFound {missing_count} combinations missing from templates.py.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="List unique (Venue, Year) combinations from a .bib file for templates."
    )
    parser.add_argument("input", type=str, help="Path to the input BibTeX (.bib) file")
    args = parser.parse_args()
    list_templates(args.input)
