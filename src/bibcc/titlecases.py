"""
Title Case Transformation for BibTeX Entries.

This module provides APA-style title case transformation logic for BibTeX titles.
It handles:
- Stopword detection (articles, prepositions, conjunctions)
- Hyphenated compound word capitalization
- Brace-protected segment preservation
- Subtitle capitalization after colons/em dashes
- Acronym preservation (all-caps words)

Usage:
    from bibcc.titlecases import suggest_title_case, check_title_case

    # Get title case suggestion
    suggested = suggest_title_case("a study on machine learning")
    # -> "A Study on Machine Learning"

    # Check and optionally apply to bib file
    issues = check_title_case("input.bib", apply=True)
"""

import re
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional, Set, Tuple

import bibtexparser

from bibcc.bibedit import BibEditError, read_bib, set_fields, write_bib


@dataclass
class TitleCaseStyle:
    """
    Configuration for a title case style.

    Attributes:
        name: Style identifier (e.g., "apa")
        stopwords: Words to keep lowercase unless at start of title/subtitle
        min_length_capitalize: Minimum word length to always capitalize
        capitalize_last_word: Whether to always capitalize the last word
        hyphen_capitalize_all_parts: Whether to capitalize all parts of hyphenated words
        subtitle_delimiters: Characters that introduce subtitles (capitalize next word)
    """

    name: str
    stopwords: Set[str]
    min_length_capitalize: int = 4
    capitalize_last_word: bool = False  # APA does not require last word specifically
    hyphen_capitalize_all_parts: bool = True  # APA: Self-Report, Class-Incremental
    subtitle_delimiters: Optional[Set[str]] = (
        None  # e.g., ':' or '—' introduce subtitle
    )


APA_STOPWORDS = {
    "a",
    "an",
    "and",
    "as",
    "at",
    "but",
    "by",
    "for",
    "from",
    "in",
    "into",
    "nor",
    "of",
    "on",
    "onto",
    "or",
    "over",
    "per",
    "the",
    "to",
    "vs",
    "via",
    "with",
    "up",
    "down",
    "off",
}


STYLES: Dict[str, TitleCaseStyle] = {
    "apa": TitleCaseStyle(
        name="apa",
        stopwords=APA_STOPWORDS,
        min_length_capitalize=4,
        capitalize_last_word=False,
        hyphen_capitalize_all_parts=True,
        subtitle_delimiters={":", "—", "–", "—"},
    ),
    # Placeholder for future styles; extend as needed.
}


def get_style(name: Optional[str]) -> TitleCaseStyle:
    """Get a title case style by name, defaulting to APA."""
    if not name:
        return STYLES["apa"]
    return STYLES.get(name.lower(), STYLES["apa"])


# Backward-compat exposed default stopwords (APA)
DEFAULT_STOPWORDS = APA_STOPWORDS

# Common lowercase prefixes in hyphenated words that should stay lowercase
# unless they are at the start of the title / subtitle.
_LOWERCASE_PREFIXES: Set[str] = {
    "e",
    "re",
    "pre",
    "non",
    "self",
    "co",
    "multi",
    "cross",
    "semi",
    "anti",
    "de",
    "un",
    "sub",
    "inter",
    "intra",
    "ex",
    "mid",
    "over",
    "under",
    "out",
    "post",
    "meta",
}

# Known mixed-case words that should never be re-cased.
KNOWN_MIXED_CASE: Set[str] = {
    "iOS",
    "macOS",
    "iPhone",
    "iPad",
    "iPod",
    "eBay",
    "eBook",
    "pH",
    "mRNA",
    "tRNA",
    "rRNA",
    "dB",
    "MHz",
    "GHz",
    "kHz",
    "arXiv",
    "GitHub",
    "YouTube",
    "JavaScript",
    "TypeScript",
    "PyTorch",
    "TensorFlow",
    "ResNet",
    "ImageNet",
    "WordNet",
    "BibTeX",
    "LaTeX",
    "DeepLab",
    "OpenAI",
    "ChatGPT",
    "GPT",
}


def _split_tokens_preserve_space(text: str) -> List[str]:
    """Split text into tokens while preserving whitespace as separate elements."""
    return re.split(r"(\s+)", text)


def _has_internal_capitals(word: str) -> bool:
    """Check if a word has internal capitals (e.g., 'iOS', 'ResNet')."""
    if len(word) < 2:
        return False
    # Skip first character, check if any lowercase→uppercase transition exists
    for i in range(1, len(word)):
        if word[i].isupper() and i > 0 and word[i - 1].islower():
            return True
    return False


def _is_known_mixed_case(word: str) -> bool:
    """Check if word is a known mixed-case term (case-insensitive lookup)."""
    lower = word.lower()
    for known in KNOWN_MIXED_CASE:
        if known.lower() == lower:
            return True
    return False


def _get_known_mixed_case(word: str) -> Optional[str]:
    """Return the canonical form of a known mixed-case word, or None."""
    lower = word.lower()
    for known in KNOWN_MIXED_CASE:
        if known.lower() == lower:
            return known
    return None


def _titlecase_hyphenated(
    core: str,
    force_capitalize: bool,
    stopwords: Set[str],
    style: TitleCaseStyle,
) -> str:
    """Apply title case to a hyphenated word (e.g., 'self-report' -> 'Self-Report').

    Handles special cases:
    - Known lowercase prefixes (e-, re-, pre-, self-, etc.) stay lowercase
      unless the whole word is at a forced position (title start / subtitle).
    - Known mixed-case words within parts are preserved.
    - Acronyms (all-caps) within parts are preserved.
    """
    parts = core.split("-")
    cased_parts = []
    for i, part in enumerate(parts):
        lower_part = part.lower()
        clean_part = re.sub(r"[^A-Za-z0-9]", "", part)

        # Check for known mixed-case form
        known_form = _get_known_mixed_case(part)
        if known_form is not None:
            cased_parts.append(known_form)
            continue

        # Keep acronyms
        if part.isupper() and len(part) >= 2:
            cased_parts.append(part)
            continue

        # Preserve words with internal capitals (e.g., ResNet, BayesNet)
        if _has_internal_capitals(part):
            cased_parts.append(part)
            continue

        # First part follows the overall word's force/major rules
        if i == 0:
            part_major = force_capitalize
            part_major = part_major or (len(clean_part) >= style.min_length_capitalize)
            part_major = part_major or (lower_part not in stopwords)
        else:
            # Subsequent parts: check for lowercase prefixes
            if lower_part in _LOWERCASE_PREFIXES and not force_capitalize:
                cased_parts.append(lower_part)
                continue
            part_major = style.hyphen_capitalize_all_parts
            part_major = part_major or (len(clean_part) >= style.min_length_capitalize)
            part_major = part_major or (lower_part not in stopwords)

        if part_major:
            cased = part.capitalize()
        else:
            cased = lower_part
        cased_parts.append(cased)
    return "-".join(cased_parts)


def _titlecase_word(
    word: str,
    force_capitalize: bool,
    stopwords: Set[str],
    style: TitleCaseStyle,
) -> str:
    """Apply title case rules to a single word, preserving punctuation and acronyms.

    Handles slashes (encoder/decoder → Encoder/Decoder) and known mixed-case
    words by preserving their canonical form.
    """
    if not word:
        return word

    # Preserve leading/trailing punctuation
    match = re.match(r"(^[^A-Za-z0-9]*)(.*?)([^A-Za-z0-9]*$)", word)
    if not match:
        return word

    prefix, core, suffix = match.groups()
    if not core:
        return word

    # Check for known mixed-case form (e.g., iOS, macOS, PyTorch)
    known_form = _get_known_mixed_case(core)
    if known_form is not None:
        return f"{prefix}{known_form}{suffix}"

    lower_core = core.lower()
    clean_core = re.sub(r"[^A-Za-z0-9]", "", core)

    is_major = force_capitalize
    is_major = is_major or (len(clean_core) >= style.min_length_capitalize)
    is_major = is_major or (lower_core not in stopwords)

    # Handle slash-separated terms (e.g., encoder/decoder)
    if "/" in core:
        slash_parts = core.split("/")
        cased_slashes = []
        for j, sp in enumerate(slash_parts):
            sp_known = _get_known_mixed_case(sp)
            if sp_known is not None:
                cased_slashes.append(sp_known)
            elif sp.isupper() and len(sp) >= 2:
                cased_slashes.append(sp)
            elif _has_internal_capitals(sp):
                cased_slashes.append(sp)
            elif is_major or (j == 0 and force_capitalize):
                cased_slashes.append(sp.capitalize())
            else:
                cased_slashes.append(sp.lower())
        return f"{prefix}{'/'.join(cased_slashes)}{suffix}"

    if "-" in core:
        cased_core = _titlecase_hyphenated(core, is_major, stopwords, style)
    else:
        # Preserve words with internal capitals
        if _has_internal_capitals(core):
            cased_core = core
        elif core.isupper() and len(core) >= 2:
            cased_core = core  # keep acronyms
        elif is_major:
            cased_core = core.capitalize()
        else:
            cased_core = lower_core

    return f"{prefix}{cased_core}{suffix}"


def suggest_title_case(
    title: str,
    stopwords: Optional[Set[str]] = None,
    style_name: str = "apa",
) -> str:
    """
    Convert a title to title case following the specified style.

    Preserves brace-protected segments (e.g., {BERT}) and handles
    subtitle capitalization after colons or em dashes.

    Args:
        title: The input title string (may contain LaTeX braces)
        stopwords: Custom stopwords to use (defaults to style's stopwords)
        style_name: Title case style to apply (default: "apa")

    Returns:
        The title converted to proper title case
    """
    style = get_style(style_name)
    stopwords = stopwords or style.stopwords

    # Protect braced segments (keep as-is)
    parts = []
    last = 0
    for m in re.finditer(r"\{.*?\}", title):
        if m.start() > last:
            parts.append(("text", title[last : m.start()]))
        parts.append(("braced", m.group()))
        last = m.end()
    if last < len(title):
        parts.append(("text", title[last:]))

    # Flatten tokens across all text segments to know first/last word positions
    word_positions: List[Tuple[int, str]] = []  # (global_index, word)
    for kind, segment in parts:
        if kind != "text":
            continue
        tokens = [t for t in _split_tokens_preserve_space(segment) if t.strip()]
        for tok in tokens:
            if tok.isspace() or not re.search(r"[A-Za-z0-9]", tok):
                continue
            word_positions.append((len(word_positions), tok))

    total_words = len(word_positions)

    def is_first_or_last(idx: int) -> bool:
        if idx == 0:
            return True
        if style.capitalize_last_word and idx == total_words - 1:
            return True
        return False

    # Rebuild with title-cased text parts
    rebuilt_parts: List[str] = []
    word_counter = 0
    prev_token_nonspace = ""
    for kind, segment in parts:
        if kind == "braced":
            rebuilt_parts.append(segment)
            continue
        tokens = _split_tokens_preserve_space(segment)
        new_tokens = []
        for tok in tokens:
            if tok.isspace() or not tok:
                new_tokens.append(tok)
                continue

            # APA: capitalize first word and word after subtitle delimiter (e.g., colon/em dash)
            prev_delim = bool(
                prev_token_nonspace.rstrip().endswith(
                    tuple(style.subtitle_delimiters or [])
                )
            )
            force = is_first_or_last(word_counter) or prev_delim

            new_tok = _titlecase_word(tok, force, stopwords, style)
            new_tokens.append(new_tok)
            prev_token_nonspace = tok
            word_counter += 1
        rebuilt_parts.append("".join(new_tokens))

    return "".join(rebuilt_parts)


def check_title_case(
    input_path: str,
    stopwords: Optional[Set[str]] = None,
    style_name: str = "apa",
    apply: bool = False,
    interactive: bool = False,
    log: Optional[Callable[[str], None]] = None,
) -> List[Tuple[str, str, str]]:
    """Check title case and return list of (entry_id, current_title, suggested_title).

    When *interactive* is ``True``, each suggestion is shown one at a time and
    the user can accept, skip, manually edit, or quit.  Accepted changes are
    applied at the end.
    """
    log = log or print
    style = get_style(style_name)
    stopwords = stopwords or set(style.stopwords)

    try:
        with open(input_path, "r", encoding="utf-8") as f:
            parser = bibtexparser.bparser.BibTexParser(common_strings=True)
            bib_db = bibtexparser.load(f, parser=parser)
    except FileNotFoundError:
        log(f"❌ Error: File '{input_path}' not found.")
        return []

    if not apply and not interactive:
        log(f"📝 Checking Title Case for {input_path}\n")
        log(f"{'ID':<40} | {'Issue':<40} | Suggestion")
        log("-" * 95)

    issues = 0
    changed: List[Tuple[str, str, str]] = []  # (ID, old, new)
    # Stats for interactive mode
    accepted = 0
    skipped = 0
    edited = 0

    for entry in bib_db.entries:
        title = entry.get("title")
        if not title:
            continue

        suggestion = suggest_title_case(title, stopwords, style_name)

        # Compare ignoring extra whitespace
        normalized_orig = " ".join(title.split())
        normalized_sugg = " ".join(suggestion.split())

        if normalized_orig != normalized_sugg:
            issues += 1

            if interactive:
                entry_id = entry.get("ID", "")
                log(f"\n--- [{issues}] {entry_id} ---")
                log(f"  Current:   {title}")
                log(f"  Suggested: {suggestion}")
                while True:
                    try:
                        choice = (
                            input("  [a]ccept / [s]kip / [e]dit / [q]uit > ")
                            .strip()
                            .lower()
                        )
                    except (EOFError, KeyboardInterrupt):
                        choice = "q"
                    if choice in ("a", "accept"):
                        entry["title"] = suggestion
                        changed.append((entry_id, title, suggestion))
                        accepted += 1
                        log("  ✅ Accepted.")
                        break
                    elif choice in ("s", "skip"):
                        skipped += 1
                        log("  ⏭️  Skipped.")
                        break
                    elif choice in ("e", "edit"):
                        try:
                            manual = input("  Enter new title: ").strip()
                        except (EOFError, KeyboardInterrupt):
                            log("  ⏭️  Skipped.")
                            skipped += 1
                            break
                        if manual:
                            entry["title"] = manual
                            changed.append((entry_id, title, manual))
                            edited += 1
                            log("  ✏️  Custom title saved.")
                        else:
                            log("  ⏭️  Empty input, skipped.")
                            skipped += 1
                        break
                    elif choice in ("q", "quit"):
                        log("\n🛑 Quit. Applying accepted changes so far...")
                        break
                    else:
                        log("  Invalid choice. Use a/s/e/q.")
                if choice in ("q", "quit"):
                    break
            elif apply:
                entry["title"] = suggestion
                changed.append((entry.get("ID", ""), title, suggestion))
            else:
                log(f"{entry.get('ID', ''):<40} | {title:<40} | {suggestion}")
                changed.append((entry.get("ID", ""), title, suggestion))

    # Apply changes to file (for apply or interactive mode with accepted changes)
    if apply or (interactive and changed):
        # bibtexparser drops the continuation indent of multi-line values,
        # so write titles back as a single line.
        changed_map = {eid: {"title": " ".join(new.split())} for eid, _, new in changed}
        text = read_bib(input_path)
        try:
            new_text, applied = set_fields(text, changed_map)
        except BibEditError as e:
            log(f"❌ Could not apply title changes safely: {e}")
            log("   Nothing was written.")
            return changed
        replacements = len(applied)
        if new_text != text:
            write_bib(input_path, new_text)

        if interactive:
            log(
                f"\n📊 Interactive summary: {accepted} accepted, {edited} edited, {skipped} skipped"
            )
            if replacements:
                log(f"✏️  Applied {replacements} title changes to {input_path}.")
            else:
                log("ℹ️  No changes applied.")
        elif replacements == 0:
            log("✅ No title-case updates needed; file left unchanged.")
        else:
            log(
                f"✏️  Applied title-case suggestions to {input_path} ({replacements} titles updated)."
            )
    elif not interactive:
        log("-" * 95)
        if issues == 0:
            log(
                "✅ All titles already appear to be in Title Case (with stopword handling)."
            )
        else:
            log(f"⚠️  Found {issues} titles that could be normalized.")

    return changed
