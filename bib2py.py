import bibtexparser
import argparse


def bib2py(input_file):
    # Load the bib file containing multiple conference/proceedings entries
    with open(input_file, "r", encoding="utf-8") as bibtex_file:
        parser = bibtexparser.bparser.BibTexParser(common_strings=True)
        bib_database = parser.parse_file(bibtex_file)

    print("# Copy the following content into your templates.py file:\n")

    for entry in bib_database.entries:
        # 1. Identify the Key (Booktitle/Journal + Year)
        # We check multiple fields because bibtex is inconsistent (journal vs booktitle vs title)
        venue_name = (
            entry.get("booktitle") or entry.get("journal") or entry.get("title")
        )
        year = entry.get("year")

        # Skip entries that are incomplete (can't form a key without them)
        if not venue_name or not year:
            print(
                f"!Skipped Entry '{entry.get('ID', 'unknown')}': Missing year or venue name."
            )
            continue

        # 2. Extract Metadata
        # We filter out fields that define the entry itself (ID, Type) or serve as the key (Year, Venue)
        excluded_keys = [
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
            "note"
        ]

        # Create the dictionary for this specific entry
        meta_data = {k: v for k, v in entry.items() if k not in excluded_keys}

        # 3. Print the Python Code
        # We use repr() to safely handle quotes and special characters inside strings
        print(f'    ("{venue_name}", "{year}"): {{')
        for k, v in meta_data.items():
            # Clean up newlines/tabs in the values which sometimes happen in bibtex
            clean_val = v.replace("\n", " ").replace("\r", "").strip()
            # Double check for internal quotes escaping
            print(f'        "{k}": {repr(clean_val)},')
        print("    },")
        print()  # Add a blank line between entries


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Convert BibTeX entries to Python dictionary format for templates.py"
    )
    parser.add_argument("input", type=str, help="Path to the input BibTeX (.bib) file")
    args = parser.parse_args()
    try:
        bib2py(args.input)
    except FileNotFoundError:
        print("Error: Please create a 'new_conferences.bib' file first.")
