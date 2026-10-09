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

from bibcc.logging_utils import SEPARATOR_LIGHT, SEPARATOR_WIDTH

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

# Shortest mixed-case / acronym / number-bearing term to flag.  Two letters
# still matter (AI, ML, dB, 3D); single letters ("A", "I") never do.
MIN_TERM_LENGTH = 2


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


_WORD = re.compile(r"[^\W_]+")


def _classify_word(word: str, min_length: int) -> Optional[str]:
    """Reason *word* needs braces, or None.

    All-lowercase words are never at risk, since BibTeX styles only ever
    lowercase.  Plain capitalized words are left to the vocabulary, except
    identifiers mixing letters and digits (``V2``, ``Llama2``, ``3D``).
    """
    if len(word) < min_length or not any(c.isupper() for c in word):
        return None
    if any(c.isdigit() for c in word):
        return "Contains Number"
    if not any(c.isupper() for c in word[1:]):
        return None
    if word.isupper():
        return None if word in _ROMAN_NUMERALS else "Acronym"
    return "Mixed Case"


def find_unprotected_terms(
    title: str,
    author: str = "",
    vocab_terms: Optional[Iterable[str]] = None,
    min_length: int = MIN_TERM_LENGTH,
) -> List[Tuple[str, str]]:
    """Return ``(word, reason)`` pairs in *title* that should be brace-protected.

    Text already inside braces is ignored, and vocabulary terms that are
    author surnames are skipped.  Titles that are mostly upper case return
    nothing (they are likely all-caps titles, not acronyms).  *min_length*
    applies to mixed-case words, acronyms, and words containing numbers.
    """
    vocab = {t.lower() for t in (DEFAULT_VOCAB if vocab_terms is None else vocab_terms)}
    clean_title = re.sub(r"\{.*?\}", lambda x: " " * len(x.group()), title)
    if sum(1 for c in clean_title if c.isupper()) / max(len(clean_title), 1) > 0.7:
        return []

    author_surnames = _extract_author_surnames({"author": author})
    spans: List[Tuple[int, int, str]] = []  # (start, end, reason)
    for match in _WORD.finditer(clean_title):
        reason = _classify_word(match.group(), min_length)
        if reason:
            spans.append((match.start(), match.end(), reason))
    for term in vocab:
        pattern = re.compile(rf"(?<!\w){re.escape(term)}(?!\w)", re.IGNORECASE)
        for match in pattern.finditer(clean_title):
            if match.group().lower() not in author_surnames:
                spans.append((match.start(), match.end(), "Vocabulary"))

    # Overlaps are resolved by position, longest first, so a standalone
    # "BERT" is still reported when "RoBERTa" appears in the same title.
    kept: List[Tuple[int, int, str]] = []
    for start, end, reason in sorted(spans, key=lambda s: (s[0] - s[1], s[0])):
        if all(end <= s or start >= e for s, e, _ in kept):
            kept.append((start, end, reason))

    unique: Dict[str, str] = {}
    for start, end, reason in sorted(kept):
        unique.setdefault(clean_title[start:end], reason)
    return list(unique.items())


_OPEN, _CLOSE = "\x00", "\x01"


def protect_terms(title: str, words: Iterable[str]) -> str:
    """Wrap each occurrence of *words* outside existing braces in ``{...}``.

    Neighbouring terms joined by ``-`` or ``/`` share one group, so ``SD-LoRA``
    becomes ``{SD-LoRA}`` rather than ``{SD}-{LoRA}``.
    """
    words = sorted(set(words), key=len, reverse=True)
    if not words:
        return title
    pattern = re.compile(
        r"(?<![\w{])(" + "|".join(re.escape(w) for w in words) + r")(?![\w}])"
    )
    out: List[str] = []
    depth = 0
    i = 0
    while i < len(title):
        ch = title[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
        elif depth == 0:
            m = pattern.match(title, i)
            if m and (i == 0 or not title[i - 1].isalnum()):
                out.append(_OPEN + m.group(1) + _CLOSE)
                i = m.end()
                continue
        out.append(ch)
        i += 1
    text = re.sub(f"{_CLOSE}([-/]){_OPEN}", r"\1", "".join(out))
    return text.replace(_OPEN, "{").replace(_CLOSE, "}")


def check_smart_protection(
    input_path: str,
    extra_vocab: Iterable[str],
    use_default_vocab: bool = True,
    min_length: int = MIN_TERM_LENGTH,
    log: Optional[Callable[[str], None]] = None,
) -> List[Tuple[str, str, str]]:
    """Check for unprotected terms and return the results.

    Args:
        input_path: Path to the BibTeX file.
        extra_vocab: Additional vocabulary terms to protect.
        use_default_vocab: Whether to include ``DEFAULT_VOCAB``.
        min_length: Minimum length for mixed-case, acronym, and number-bearing terms.
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

    log(f"{'ID':<30} | {'Suspicious Word':<20} | {'Reason'}")
    log(SEPARATOR_LIGHT * SEPARATOR_WIDTH)

    vocab_terms = set(DEFAULT_VOCAB) if use_default_vocab else set()
    vocab_terms.update([t.lower() for t in extra_vocab])

    for entry in bib_db.entries:
        title = entry.get("title")
        if not title:
            continue
        for word, reason in find_unprotected_terms(
            title, entry.get("author", ""), vocab_terms, min_length
        ):
            log(f"{entry['ID']:<30} | {word:<20} | {reason}")
            protection_rows.append((entry["ID"], word, reason))

    log(SEPARATOR_LIGHT * SEPARATOR_WIDTH)
    if protection_rows:
        log(f"⚠️  Found {len(protection_rows)} terms to protect.")
    else:
        log(f"✅ No unprotected terms in {len(bib_db.entries)} entries.")

    return protection_rows
