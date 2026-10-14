"""
Smart term-protection checker for BibTeX titles.

Detects technical terms, acronyms, mixed-case words, and vocabulary terms
that should be wrapped in braces to prevent BibTeX from altering casing,
and hyphenated compounds braced as a whole when only some parts need it
(``{CLIP-Based}`` → ``{CLIP}-Based``).

Usage:
    from bibcc.checkers.smart_protection import check_smart_protection, DEFAULT_VOCAB

    rows = check_smart_protection("refs.bib", extra_vocab=["BERT", "ResNet"])
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional, Set, Tuple

import bibtexparser

from bibcc.bibedit import BibEditError, read_bib, set_fields, write_bib
from bibcc.logging_utils import SEPARATOR_LIGHT, SEPARATOR_WIDTH, report_dir

AUTO_VOCAB_NAME = "vocab.txt"
"""Name of the per-input vocabulary file inside the input's report directory."""


def auto_vocab_path(input_path: str) -> Path:
    """The vocabulary file that ``check quote`` always reads for *input_path*.

    ``.bibcc/INPUT/vocab.txt`` next to the input file: one term per line,
    loaded on top of ``--terms`` and ``--vocab-file``.  ``--interactive``
    adds the compounds you keep whole to it, so list a method-name compound
    such as ``CIP-Net`` here to keep it in one brace group for good.
    """
    return report_dir(input_path, create=False) / AUTO_VOCAB_NAME

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
    keep_case: bool = False,
) -> Set[str]:
    """Load vocabulary terms from a newline-delimited file (lower-cased unless *keep_case*).

    Blank lines and lines starting with ``#`` are ignored.
    """
    vocab: Set[str] = set()
    if not path.exists():
        log(f"⚠️  Vocab file '{path}' not found; skipping.")
        return vocab
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            term = line.strip()
            if term and not term.startswith("#"):
                vocab.add(term if keep_case else term.lower())
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
    vocab = _vocab_set(vocab_terms)
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


_SEPARATORS = ("-", "/")


def brace_compound_parts(tokens: List[str], needs: List[bool]) -> str:
    """Join compound *tokens* (parts and ``-`` or ``/``), bracing each run of parts that *needs* braces.

    *needs* is aligned with *tokens*; separators inside a run join its group,
    so ``SD - LoRA - Net`` with ``Net`` not needing braces gives ``{SD-LoRA}-Net``.
    """
    out: List[str] = []
    i, n = 0, len(tokens)
    while i < n:
        if needs[i] and tokens[i] not in _SEPARATORS:
            j = i
            while j + 2 < n and needs[j + 2]:
                j += 2
            out.append("{" + "".join(tokens[i : j + 1]) + "}")
            i = j + 1
        else:
            out.append(tokens[i])
            i += 1
    return "".join(out)


def _part_needs_braces(part: str) -> Optional[bool]:
    """Whether a compound part needs braces; None for parts without letters (``4``, ``1.5``)."""
    if not any(c.isalpha() for c in part):
        return None
    if any(c.isdigit() for c in part):
        return True
    if len(part) == 1:
        return part.isupper()
    return _classify_word(part, MIN_TERM_LENGTH) is not None


def split_compound(content: str, vocab: Set[str]) -> Optional[str]:
    """Re-braced form of the braced compound *content*, or None to keep it in one group.

    A compound stays whole when every part needs braces (a method name such
    as ``SD-LoRA``, ``R-CNN``, or ``GPT-4``), when no part does (a name such
    as ``Hamilton-Jacobi``), or when the compound itself is in *vocab*
    (lowercase), which is how a listed method name such as ``CODA-Prompt``
    keeps one brace group.  A part being in *vocab* doesn't keep the
    compound whole: ``CLIP-Based`` → ``{CLIP}-Based`` even when ``CLIP``
    is listed.  Otherwise only the parts that need braces keep them.
    """
    if content.lower() in vocab:
        return None
    tokens = re.split(r"([-/])", content)
    parts = tokens[::2]
    status = [_part_needs_braces(p) for p in parts]
    if True not in status or False not in status:
        return None
    needs: List[bool] = []
    for s in status:
        # A part without letters goes with the part before it: {GPT-4}-Based.
        needs.append(bool(needs and needs[-1]) if s is None else s)
    flags = [needs[k // 2] if k % 2 == 0 else False for k in range(len(tokens))]
    return brace_compound_parts(tokens, flags)


_BRACED_COMPOUND = re.compile(r"\{([^\s{}\\]*[-/][^\s{}\\]*)\}")


def _overbraced(title: str, vocab: Set[str]) -> Iterable[Tuple[re.Match, str]]:
    for m in _BRACED_COMPOUND.finditer(title):
        before = title[: m.start()]
        if before.count("{") != before.count("}"):
            continue  # inside a larger group, which protects it anyway
        if (m.start() and title[m.start() - 1].isalnum()) or (
            m.end() < len(title) and title[m.end()].isalnum()
        ):
            continue  # part of a longer word
        new = split_compound(m.group(1), vocab)
        if new is not None:
            yield m, new


def _vocab_set(vocab_terms: Optional[Iterable[str]]) -> Set[str]:
    return {t.lower() for t in (DEFAULT_VOCAB if vocab_terms is None else vocab_terms)}


def find_overbraced_compounds(
    title: str, vocab_terms: Optional[Iterable[str]] = None
) -> List[Tuple[str, str]]:
    """Return ``(group, suggestion)`` for compounds braced whole that only partly need it.

    For example, ``{CLIP-Based}`` gives ``{CLIP}-Based``.  For the rules, see
    :func:`split_compound`; *vocab_terms* defaults to ``DEFAULT_VOCAB``.
    """
    found: Dict[str, str] = {}
    for m, new in _overbraced(title, _vocab_set(vocab_terms)):
        found.setdefault(m.group(), new)
    return list(found.items())


def split_overbraced_compounds(title: str, vocab_terms: Optional[Iterable[str]] = None) -> str:
    """Replace each group that :func:`find_overbraced_compounds` reports with its suggestion."""
    pieces: List[str] = []
    last = 0
    for m, new in _overbraced(title, _vocab_set(vocab_terms)):
        pieces += [title[last : m.start()], new]
        last = m.end()
    return "".join(pieces) + title[last:]


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

    overbraced = 0
    for entry in bib_db.entries:
        title = entry.get("title")
        if not title:
            continue
        rows = find_unprotected_terms(title, entry.get("author", ""), vocab_terms, min_length)
        for group, suggestion in find_overbraced_compounds(title, vocab_terms):
            rows.append((group, f"Over-Braced: use {suggestion}"))
            overbraced += 1
        for word, reason in rows:
            log(f"{entry['ID']:<30} | {word:<20} | {reason}")
            protection_rows.append((entry["ID"], word, reason))

    log(SEPARATOR_LIGHT * SEPARATOR_WIDTH)
    if protection_rows:
        split = f" and {overbraced} over-braced compounds to split" if overbraced else ""
        log(f"⚠️  Found {len(protection_rows) - overbraced} terms to protect{split}.")
        if overbraced:
            log(f"   To keep a method-name compound whole, add it to {auto_vocab_path(input_path)} "
                "(one term per line), or pass it with --terms.")
            log("   To review each split one by one, pass --interactive.")
    else:
        log(f"✅ No unprotected terms in {len(bib_db.entries)} entries.")

    return protection_rows


def _remember_compound(content: str, vocab: Set[str], vocab_path: Path, log: Callable[[str], None]) -> None:
    """Keep the braced compound *content* whole for good: add it to *vocab* and *vocab_path*."""
    vocab.add(content.lower())
    if vocab_path.is_file():
        lines = {line.strip().lower() for line in vocab_path.read_text(encoding="utf-8").splitlines()}
        if content.lower() in lines:
            log(f"  📝 Kept whole; {content} is already in {vocab_path}.")
            return
    vocab_path.parent.mkdir(parents=True, exist_ok=True)
    with open(vocab_path, "a", encoding="utf-8") as f:
        f.write(content + "\n")
    log(f"  📝 Kept whole, and added to {vocab_path}; later runs leave it alone.")


def _review_compounds(
    base: str,
    findings: List[Tuple[re.Match, str]],
    entry_id: str,
    vocab: Set[str],
    vocab_path: Path,
    counts: Dict[str, int],
    log: Callable[[str], None],
) -> Tuple[str, bool]:
    """Review each over-braced compound of one title; return the new title and whether to quit.

    Each finding can be accepted (the split is applied), skipped (the
    compound stays whole this run), remembered (it stays whole and goes to
    *vocab_path*, so later runs leave it alone), edited (a custom
    replacement), or the review can stop, keeping the changes accepted so
    far.
    """
    pieces: List[str] = []
    last = 0
    for i, (m, suggestion) in enumerate(findings):
        log(f"\n--- {entry_id} ({i + 1}/{len(findings)}) ---")
        log(f"  Title:     {base}")
        log(f"  Compound:  {m.group()}")
        log(f"  Suggested: {suggestion}")
        while True:
            try:
                choice = input("  [a]ccept / [s]kip / [r]emember / [e]dit / [q]uit > ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                choice = "q"
            if choice in ("a", "accept"):
                pieces += [base[last : m.start()], suggestion]
                last = m.end()
                counts["accepted"] += 1
                log("  ✅ Accepted.")
                break
            if choice in ("s", "skip"):
                counts["skipped"] += 1
                log("  ⏭️  Skipped; kept whole this run.")
                break
            if choice in ("r", "remember"):
                _remember_compound(m.group(1), vocab, vocab_path, log)
                counts["remembered"] += 1
                break
            if choice in ("e", "edit"):
                try:
                    manual = input("  Enter the replacement: ").strip()
                except (EOFError, KeyboardInterrupt):
                    manual = ""
                if manual:
                    pieces += [base[last : m.start()], manual]
                    last = m.end()
                    counts["edited"] += 1
                    log("  ✏️  Custom replacement saved.")
                else:
                    counts["skipped"] += 1
                    log("  ⏭️  Empty input, skipped.")
                break
            if choice in ("q", "quit"):
                log("\n🛑 Quit. Applying accepted changes so far...")
                return "".join(pieces) + base[last:], True
            log("  Invalid choice. Use a/s/r/e/q.")
    return "".join(pieces) + base[last:], False


def apply_protection(
    input_path: str,
    terms: Iterable[str],
    vocab_terms: Optional[Iterable[str]] = None,
    interactive: bool = False,
    vocab_path: Optional[Path] = None,
    log: Optional[Callable[[str], None]] = None,
) -> List[Tuple[str, str, str]]:
    """Brace *terms* and split over-braced compounds in the titles of *input_path*.

    *terms* are matched case-sensitively, as given.  Compounds are split as
    :func:`split_overbraced_compounds` does with *vocab_terms* (default:
    ``DEFAULT_VOCAB``) plus *terms*, so a compound you list stays whole.
    When *interactive* is ``True``, each over-braced compound is reviewed
    one at a time (split, skip, edit, or keep whole and remember it in
    *vocab_path*, which defaults to :func:`auto_vocab_path` of *input_path*).
    Only the title values change, and the edit is verified before the file
    is written.  Returns ``(entry_id, old_title, new_title)`` for each title
    changed; nothing is written if the edit cannot be verified.
    """
    log = log or print
    terms = sorted({t for t in terms if t})
    vocab = _vocab_set(vocab_terms) | {t.lower() for t in terms}
    if vocab_path is None:
        vocab_path = auto_vocab_path(input_path)
    what = f"Bracing {len(terms)} terms and splitting" if terms else "Splitting"
    where = f"the titles of {input_path}"
    log(f"🔒 {what} over-braced compounds in {where}" + (", one by one" if interactive else "") + "...\n")
    text = read_bib(input_path)
    parser = bibtexparser.bparser.BibTexParser(common_strings=True)
    changed: List[Tuple[str, str, str]] = []
    counts = {"accepted": 0, "skipped": 0, "remembered": 0, "edited": 0}
    quit_now = False
    for entry in bibtexparser.loads(text, parser=parser).entries:
        title = entry.get("title")
        if not title:
            continue
        base = protect_terms(title, terms)
        if interactive:
            findings = list(_overbraced(base, vocab))
            if findings:
                base, quit_now = _review_compounds(
                    base, findings, entry["ID"], vocab, vocab_path, counts, log
                )
        else:
            base = split_overbraced_compounds(base, vocab)
        new = " ".join(base.split())
        if new != " ".join(title.split()):
            changed.append((entry["ID"], " ".join(title.split()), new))
        if quit_now:
            break
    if interactive:
        log(f"\n📊 Interactive summary: {counts['accepted']} accepted, {counts['edited']} edited, "
            f"{counts['skipped']} skipped, {counts['remembered']} remembered")
    if not changed:
        if interactive:
            log("✅ No title changed.")
        else:
            log("✅ The titles need no changes: the terms are already in braces, "
                "and no compound is over-braced.")
        return []
    try:
        new_text, _ = set_fields(text, {eid: {"title": new} for eid, _, new in changed})
    except BibEditError as e:
        log(f"❌ Could not apply the term protection safely: {e}")
        log("   Nothing was written.")
        return []
    write_bib(input_path, new_text)
    for eid, _, new in changed:
        log(f"{eid:<30} | {new}")
    log(SEPARATOR_LIGHT * SEPARATOR_WIDTH)
    log(f"✏️  Changed the braces in {len(changed)} titles of {input_path}.")
    return changed
