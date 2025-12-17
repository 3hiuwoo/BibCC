import argparse
import re

import bibtexparser


def check_smart_protection(input_path):
    print(f"🧠 Smart-Scanning {input_path} for unprotected terms...\n")

    try:
        with open(input_path, "r", encoding="utf-8") as f:
            parser = bibtexparser.bparser.BibTexParser(common_strings=True)
            bib_db = parser.parse_file(f)
    except FileNotFoundError:
        print(f"❌ Error: File '{input_path}' not found.")
        return

    issues_found = 0

    # --- UPDATED REGEX PATTERNS ---

    # Pattern A: CamelCase/Mixed (e.g., ResNet, LoRA, iPhone)
    # (Matches words with a capital inside, but ignores standard Titlecase like 'Learning')
    regex_mixed = r"\b(?:[a-z]+[A-Z][a-zA-Z]*)|(?:[A-Z][a-z]*[A-Z][a-zA-Z]*)\b"

    # Pattern B: All Caps (e.g., BERT, LLM), length > 1
    regex_allcaps = r"\b[A-Z]{2,}\b"

    # Pattern C: Contains Numbers (e.g., GPT-4, Llama3, VGG16)
    regex_numeric = r"\b[A-Za-z]*\d+[A-Za-z0-9\-]*\b"

    print(f"{'ID':<30} | {'Suspicious Word':<20} | {'Reason'}")
    print("-" * 75)

    for entry in bib_db.entries:
        title = entry.get("title")
        if not title:
            continue

        # Clean protected content
        clean_title = re.sub(r"\{.*?\}", lambda x: " " * len(x.group()), title)

        if sum(1 for c in clean_title if c.isupper()) / max(len(clean_title), 1) > 0.7:
            continue

        found_issues = []

        # 1. Check Mixed Case (LoRA)
        for match in re.finditer(regex_mixed, clean_title):
            found_issues.append((match.group(), "Mixed Case"))

        # 2. Check All Caps (BERT)
        for match in re.finditer(regex_allcaps, clean_title):
            found_issues.append((match.group(), "Acronym"))

        # 3. Check Numeric (GPT-4)
        for match in re.finditer(regex_numeric, clean_title):
            found_issues.append((match.group(), "Contains Number"))

        # Deduplicate results (So S-LoRA doesn't appear twice)
        # We process matches to prefer longer matches (S-LoRA) over shorter ones (LoRA)
        unique_issues = {}
        for word, reason in found_issues:
            # If this word is already part of a longer word we found, skip it
            # e.g. If we found "S-LoRA", don't report "LoRA" separately
            is_substring = False
            for existing in list(unique_issues.keys()):
                if word in existing and word != existing:
                    is_substring = True
                elif existing in word and existing != word:
                    del unique_issues[existing]  # Replace shorter with longer

            if not is_substring:
                unique_issues[word] = reason

        for word, reason in unique_issues.items():
            print(f"{entry['ID']:<30} | {word:<20} | {reason}")
            issues_found += 1

    print("-" * 75)
    if issues_found > 0:
        print(f"⚠️  Found {issues_found} terms to protect.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Check BibTeX file for unprotected terms."
    )
    parser.add_argument("input", type=str, help="Path to the input BibTeX file.")
    args = parser.parse_args()
    check_smart_protection(args.input)
