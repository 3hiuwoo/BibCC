"""
Smart term-protection checker for BibTeX titles.

Detects technical terms, acronyms, mixed-case words, and vocabulary terms
that should be wrapped in braces to prevent BibTeX from altering casing.

Usage:
    from bibcc.checkers.smart_protection import check_smart_protection, DEFAULT_VOCAB

    rows = check_smart_protection("refs.bib", extra_vocab=["BERT", "ResNet"])
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional, Set, Tuple

import bibtexparser

DEFAULT_VOCAB: Set[str] = {
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
    "Kronecker",
    "arnold",
}

# Roman numerals and short words to never flag as acronyms
_ROMAN_NUMERALS = {
    "I",
    "II",
    "III",
    "IV",
    "V",
    "VI",
    "VII",
    "VIII",
    "IX",
    "X",
    "XI",
    "XII",
    "XIII",
    "XIV",
    "XV",
    "XVI",
    "XX",
    "XXI",
}

# Minimum length for acronym detection to avoid single-letter false positives
MIN_ACRONYM_LENGTH = 2

# Minimum length for mixed-case detection
MIN_MIXED_CASE_LENGTH = 3


def parse_terms(raw: str) -> List[str]:
    """Parse a comma-separated string of terms into a list."""
    if not raw:
        return []
    return [t.strip() for t in raw.split(",") if t.strip()]


def load_vocab_file(
    path: Path,
    log: Callable[[str], None] = print,
) -> Set[str]:
    """Load vocabulary terms from a newline-delimited file."""
    vocab: Set[str] = set()
    if not path.exists():
        log(f"⚠️  Vocab file '{path}' not found; skipping.")
        return vocab
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            term = line.strip()
            if term:
                vocab.add(term.lower())
    return vocab


def _extract_author_surnames(entry: Dict) -> Set[str]:
    """Extract author last names from entry for false-positive filtering."""
    author_str = entry.get("author", "")
    if not author_str:
        return set()
    surnames: Set[str] = set()
    # Handle "Last, First and Last, First" and "First Last and First Last"
    for part in re.split(r"\s+and\s+", author_str):
        part = part.strip().replace("{", "").replace("}", "")
        if "," in part:
            surname = part.split(",")[0].strip()
        else:
            tokens = part.split()
            surname = tokens[-1] if tokens else ""
        if surname:
            surnames.add(surname.lower())
    return surnames


def _is_pure_number(word: str) -> bool:
    """Check if a word is a pure number (e.g., '3', '100')."""
    return bool(re.fullmatch(r"\d+", word))


def check_smart_protection(
    input_path: str,
    extra_vocab: Iterable[str],
    use_default_vocab: bool = True,
    min_length: int = MIN_MIXED_CASE_LENGTH,
    log: Optional[Callable[[str], None]] = None,
) -> List[Tuple[str, str, str]]:
    """Check for unprotected terms and return the results.

    Args:
        input_path: Path to the BibTeX file.
        extra_vocab: Additional vocabulary terms to protect.
        use_default_vocab: Whether to include ``DEFAULT_VOCAB``.
        min_length: Minimum word length for mixed-case / acronym detection.
        log: Optional logging callback; falls back to ``print``.

    Returns:
        List of ``(entry_id, word, reason)`` tuples.
    """
    log = log or print
    log(f"🧠 Smart-Scanning {input_path} for unprotected terms...\n")

    try:
        with open(input_path, "r", encoding="utf-8") as f:
            parser = bibtexparser.bparser.BibTexParser(common_strings=True)
            bib_db = bibtexparser.load(f, parser=parser)
    except FileNotFoundError:
        log(f"❌ Error: File '{input_path}' not found.")
        return []

    protection_rows: List[Tuple[str, str, str]] = []  # (entry_id, word, reason)

    # Mixed case: require at least min_length chars and a lowercase→uppercase transition
    regex_mixed = r"\b(?:[a-z]+[A-Z][a-zA-Z]*)|(?:[A-Z][a-z]*[A-Z][a-zA-Z]*)\b"
    regex_allcaps = r"\b[A-Z]{2,}\b"
    # Numbers with letters (model names like ResNet50), but skip pure numbers
    regex_numeric = r"\b[A-Za-z]+\d+[A-Za-z0-9\-]*\b"

    log(f"{'ID':<30} | {'Suspicious Word':<20} | {'Reason'}")
    log("-" * 75)

    vocab_terms = set(DEFAULT_VOCAB) if use_default_vocab else set()
    vocab_terms.update([t.lower() for t in extra_vocab])

    for entry in bib_db.entries:
        title = entry.get("title")
        if not title:
            continue

        clean_title = re.sub(r"\{.*?\}", lambda x: " " * len(x.group()), title)

        if sum(1 for c in clean_title if c.isupper()) / max(len(clean_title), 1) > 0.7:
            continue

        # Build per-entry context for false-positive filtering
        author_surnames = _extract_author_surnames(entry)

        found_issues: List[Tuple[str, str]] = []

        for match in re.finditer(regex_mixed, clean_title):
            word = match.group()
            # Skip words shorter than minimum length
            if len(word) < min_length:
                continue
            found_issues.append((word, "Mixed Case"))

        for match in re.finditer(regex_allcaps, clean_title):
            word = match.group()
            # Skip Roman numerals
            if word in _ROMAN_NUMERALS:
                continue
            # Skip very short acronyms (single letter already excluded by regex)
            if len(word) < MIN_ACRONYM_LENGTH:
                continue
            found_issues.append((word, "Acronym"))

        for match in re.finditer(regex_numeric, clean_title):
            word = match.group()
            # Pure numbers are already excluded by the regex (requires letters)
            found_issues.append((word, "Contains Number"))

        for term in vocab_terms:
            pattern = re.compile(rf"(?<!\w){re.escape(term)}(?!\w)", re.IGNORECASE)
            for match in pattern.finditer(clean_title):
                matched = match.group()
                # Skip if the term is an author surname in this entry
                if matched.lower() in author_surnames:
                    continue
                found_issues.append((matched, "Vocabulary"))

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
            log(f"{entry['ID']:<30} | {word:<20} | {reason}")
            protection_rows.append((entry["ID"], word, reason))

    log("-" * 75)
    if protection_rows:
        log(f"⚠️  Found {len(protection_rows)} terms to protect.")

    return protection_rows
