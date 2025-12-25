import argparse
import re
from pathlib import Path
from typing import Iterable, List, Sequence, Set, Tuple

import bibtexparser

from titlecases import DEFAULT_STOPWORDS, check_title_case, get_style


DEFAULT_ENTRY_TYPES = ["inproceedings", "article", "proceedings", "conference"]
# DEFAULT_REQUIRED_FIELDS = ["month"]

DEFAULT_VOCAB = {
    "gaussian",
    "bayesian",
    "markov",
    "poisson",
    "fourier",
    "laplace",
    "euler",
    "kalman",
    "kolmogorov",
    "newton",
    "hamilton",
    "lagrange",
    "riemann",
    "hilbert",
    "bessel",
    "hadamard",
    "chernoff",
    "hoeffding",
    "chebyshev",
    "bernoulli",
    "dirichlet",
    "fisher",
    "neyman",
    "cauchy",
    "boltzmann",
    "gibbs",
    "wiener",
    "ito",
    "lévy",
    "levy",
    "gram",
    "schmidt",
    "heaviside",
    "noether",
    "poincaré",
    "weibull",
    "rayleigh",
    "shannon",
    "huffman",
    "turing",
}


def parse_list_arg(raw: str) -> List[str]:
    if not raw:
        return []
    return [item.strip() for item in raw.split(",") if item.strip()]


def load_vocab_file(path: Path) -> Set[str]:
    vocab: Set[str] = set()
    if not path.exists():
        print(f"⚠️  Vocab file '{path}' not found; skipping.")
        return vocab
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            term = line.strip()
            if term:
                vocab.add(term.lower())
    return vocab


def parse_terms(raw: str) -> List[str]:
    if not raw:
        return []
    return [t.strip() for t in raw.split(",") if t.strip()]


def check_missing_fields(
    input_path: str, required_fields: Sequence[str], target_types: Sequence[str]
) -> None:
    required_fields = [f.strip() for f in required_fields if f.strip()]
    if not required_fields:
        print("ℹ️  No required fields specified, skipping missing-field check.")
        return

    print(
        f"🔍 Scanning {input_path} for missing fields: {', '.join(required_fields)}\n"
    )

    try:
        with open(input_path, "r", encoding="utf-8") as f:
            parser = bibtexparser.bparser.BibTexParser(common_strings=True)
            bib_db = bibtexparser.load(f, parser=parser)
    except FileNotFoundError:
        print(f"❌ Error: File '{input_path}' not found.")
        return

    missing_rows: List[Tuple[str, str, str, List[str]]] = []

    print(f"{'ID':<40} | {'Type':<15} | {'Year':<6} | Missing")
    print("-" * 95)

    for entry in bib_db.entries:
        entry_type = entry.get("ENTRYTYPE", "").lower()
        if entry_type not in target_types:
            continue

        missing = [
            field for field in required_fields if not entry.get(field, "").strip()
        ]
        if missing:
            missing_rows.append(
                (entry.get("ID", ""), entry_type, entry.get("year", "N/A"), missing)
            )

    for row in missing_rows:
        rid, rtype, ryear, rmiss = row
        print(f"{rid:<40} | {rtype:<15} | {ryear:<6} | {', '.join(rmiss)}")

    print("-" * 95)
    if not missing_rows:
        print("✅ Perfect! All target entries contain the required fields.")
    else:
        field_counts = {f: 0 for f in required_fields}
        for _, _, _, miss in missing_rows:
            for f in miss:
                field_counts[f] += 1
        summary = "; ".join([f"{k}: {v}" for k, v in field_counts.items()])
        print(
            f"⚠️  Found {len(missing_rows)} entries missing fields. Breakdown -> {summary}"
        )


def check_smart_protection(
    input_path: str,
    extra_vocab: Iterable[str],
    use_default_vocab: bool = True,
) -> None:
    print(f"🧠 Smart-Scanning {input_path} for unprotected terms...\n")

    try:
        with open(input_path, "r", encoding="utf-8") as f:
            parser = bibtexparser.bparser.BibTexParser(common_strings=True)
            bib_db = bibtexparser.load(f, parser=parser)
    except FileNotFoundError:
        print(f"❌ Error: File '{input_path}' not found.")
        return

    issues_found = 0

    regex_mixed = r"\b(?:[a-z]+[A-Z][a-zA-Z]*)|(?:[A-Z][a-z]*[A-Z][a-zA-Z]*)\b"
    regex_allcaps = r"\b[A-Z]{2,}\b"
    regex_numeric = r"\b[A-Za-z]*\d+[A-Za-z0-9\-]*\b"

    print(f"{'ID':<30} | {'Suspicious Word':<20} | {'Reason'}")
    print("-" * 75)

    vocab_terms = set(DEFAULT_VOCAB) if use_default_vocab else set()
    vocab_terms.update([t.lower() for t in extra_vocab])

    for entry in bib_db.entries:
        title = entry.get("title")
        if not title:
            continue

        clean_title = re.sub(r"\{.*?\}", lambda x: " " * len(x.group()), title)

        if sum(1 for c in clean_title if c.isupper()) / max(len(clean_title), 1) > 0.7:
            continue

        found_issues = []

        for match in re.finditer(regex_mixed, clean_title):
            found_issues.append((match.group(), "Mixed Case"))

        for match in re.finditer(regex_allcaps, clean_title):
            found_issues.append((match.group(), "Acronym"))

        for match in re.finditer(regex_numeric, clean_title):
            found_issues.append((match.group(), "Contains Number"))

        for term in vocab_terms:
            pattern = re.compile(rf"(?<!\w){re.escape(term)}(?!\w)", re.IGNORECASE)
            for match in pattern.finditer(clean_title):
                found_issues.append((match.group(), "Vocabulary"))

        unique_issues = {}
        for word, reason in found_issues:
            is_substring = False
            for existing in list(unique_issues.keys()):
                if word in existing and word != existing:
                    is_substring = True
                elif existing in word and existing != word:
                    del unique_issues[existing]

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
        description="Unified checker for BibTeX: missing fields, title case, and smart protection."
    )
    parser.add_argument("input", type=str, help="Path to the input BibTeX (.bib) file")
    parser.add_argument(
        "--fields",
        type=str,
        default="",
        help="Comma-separated required fields to enforce (default: month).",
    )
    parser.add_argument(
        "--entry-types",
        type=str,
        default=",".join(DEFAULT_ENTRY_TYPES),
        help="Comma-separated ENTRYTYPEs to check (default: inproceedings,article,proceedings,conference).",
    )
    parser.add_argument(
        "--title-case",
        action="store_true",
        help="Check that titles are in Title Case (APA by default).",
    )
    parser.add_argument(
        "--title-style",
        type=str,
        default="apa",
        help="Title case style to apply (default: apa).",
    )
    parser.add_argument(
        "--extra-stopwords",
        type=str,
        default="",
        help="Comma-separated additional stopwords to keep lowercase in title-case suggestions.",
    )
    parser.add_argument(
        "--quote",
        action="store_true",
        help="Run smart protection to suggest curly braces for technical terms (merged quoter).",
    )
    parser.add_argument(
        "--quote-terms",
        type=str,
        default="",
        help="Comma-separated extra terms to protect (in addition to default vocab).",
    )
    parser.add_argument(
        "--quote-vocab-file",
        type=str,
        default=None,
        help="Optional path to newline-delimited vocabulary file of technical terms to protect.",
    )
    parser.add_argument(
        "--quote-no-default",
        action="store_true",
        help="Do not include built-in technical vocabulary when running smart protection.",
    )

    args = parser.parse_args()

    required_fields = parse_list_arg(args.fields)  # or DEFAULT_REQUIRED_FIELDS
    entry_types = [
        t.lower() for t in parse_list_arg(args.entry_types) or DEFAULT_ENTRY_TYPES
    ]

    # Missing fields
    if required_fields:
        check_missing_fields(args.input, required_fields, entry_types)

    # Title case
    if args.title_case:
        print("\n")
        style = get_style(args.title_style)
        stopwords = set(style.stopwords)
        stopwords.update([s.lower() for s in parse_list_arg(args.extra_stopwords)])
        check_title_case(args.input, stopwords, style.name)

    # Smart protection
    if args.quote:
        print("\n")
        extra_vocab: List[str] = []
        if args.quote_vocab_file:
            extra_vocab.extend(load_vocab_file(Path(args.quote_vocab_file)))
        extra_vocab.extend(parse_terms(args.quote_terms))
        check_smart_protection(
            args.input,
            extra_vocab,
            use_default_vocab=not args.quote_no_default,
        )
