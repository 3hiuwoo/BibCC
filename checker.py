import argparse

import bibtexparser


def check_missing_months(input_path):
    print(f"🔍 Scanning {input_path} for missing months...\n")

    try:
        with open(input_path, "r", encoding="utf-8") as f:
            parser = bibtexparser.bparser.BibTexParser(common_strings=True)
            bib_db = parser.parse_file(f)
    except FileNotFoundError:
        print(f"❌ Error: File '{input_path}' not found.")
        return

    missing_count = 0

    # Define which entry types usually require a month
    # You can remove 'book' or 'misc' if you don't care about months for those
    target_types = ["inproceedings", "article", "proceedings", "conference"]

    print(f"{'ID':<40} | {'Type':<15} | {'Year'}")
    print("-" * 65)

    for entry in bib_db.entries:
        # 1. Filter by Type
        if entry["ENTRYTYPE"].lower() not in target_types:
            continue

        # 2. Check if month is missing or empty
        month = entry.get("month", "").strip()

        if not month:
            missing_count += 1
            print(
                f"{entry['ID']:<40} | {entry['ENTRYTYPE']:<15} | {entry.get('year', 'N/A')}"
            )

    print("-" * 65)
    if missing_count == 0:
        print("✅ Perfect! All target entries have a month field.")
    else:
        print(f"⚠️  Found {missing_count} entries missing a month.")


# Standalone execution
if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Check for missing month fields in a BibTeX (.bib) file."
    )
    parser.add_argument("input", type=str, help="Path to the input BibTeX (.bib) file")
    args = parser.parse_args()
    check_missing_months(args.input)