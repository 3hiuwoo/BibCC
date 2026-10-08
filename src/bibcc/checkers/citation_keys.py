"""
Citation key legibility checker for BibTeX entries.

Validates that citation keys follow the ``METHOD_AUTHOR_VENUEYEAR`` convention
(e.g., ``PLAN_Wang_ICCV2025``, ``MG-CLIP_Huang_ICCV2025``).

The expected format is::

    {METHOD}_{AUTHOR}_{ABBREV}{YEAR}

where METHOD may contain alphanumeric characters, hyphens, and ``+``,
AUTHOR is alphabetic (optionally with ``'`` or ``-``), and ABBREV is a venue
abbreviation immediately followed by a four-digit year.

Usage:
    from bibcc.checkers.citation_keys import check_citation_keys

    rows = check_citation_keys("refs.bib", log=print)
"""

from __future__ import annotations

import re
from typing import Callable, Dict, List, Optional, Set, Tuple

import bibtexparser

# Regex for expected citation key format: METHOD_AUTHOR_VENUEYEAR
# METHOD: alphanumeric + hyphens + plus (at least 1 char)
# AUTHOR: alphabetic + apostrophe + hyphen (at least 1 char)
# VENUE: uppercase alpha abbreviation (at least 1 char)
# YEAR: exactly 4 digits
_KEY_PATTERN = re.compile(
    r"^(?P<method>[A-Za-z0-9+\-]+)_(?P<author>[A-Za-z][A-Za-z'\-]*)_(?P<venue>[A-Z][A-Za-z]*)(?P<year>\d{4})$"
)

# Known venue abbreviations mapped from common full names
# This is used to verify the VENUE part against the actual booktitle/journal
VENUE_ABBREVIATIONS: Dict[str, Set[str]] = {
    # Top-tier CV conferences
    "CVPR": {"cvpr", "ieee/cvf conference on computer vision and pattern recognition"},
    "ICCV": {"iccv", "ieee/cvf international conference on computer vision"},
    "ECCV": {
        "eccv",
        "european conference on computer vision",
        "computer vision -- eccv",
    },
    # ML conferences
    "NeurIPS": {
        "neurips",
        "neural information processing systems",
        "advances in neural information processing systems",
    },
    "ICML": {"icml", "international conference on machine learning"},
    "ICLR": {"iclr", "international conference on learning representations"},
    "AAAI": {"aaai", "aaai conference on artificial intelligence"},
    # Multimedia
    "MM": {"acm multimedia", "acm international conference on multimedia"},
    # Web
    "WWW": {"www", "web conference", "acm on web conference"},
    # NLP
    "ACL": {
        "acl",
        "association for computational linguistics",
        "annual meeting of the association for computational linguistics",
    },
    "EMNLP": {"emnlp", "empirical methods in natural language processing"},
    "NAACL": {"naacl", "north american chapter"},
    # Data mining / KDD
    "KDD": {"kdd", "knowledge discovery and data mining", "sigkdd"},
    # Speech
    "Interspeech": {"interspeech"},
    # Journal abbreviations
    "TIP": {"ieee transactions on image processing"},
    "TPAMI": {"ieee transactions on pattern analysis and machine intelligence"},
    "TMM": {"ieee transactions on multimedia"},
    "TNNLS": {"ieee transactions on neural networks and learning systems"},
    "TCSVT": {"ieee transactions on circuits and systems for video technology"},
    "TGRS": {"ieee transactions on geoscience and remote sensing"},
    "TOMM": {"acm transactions on multimedia computing"},
    "TKDD": {"acm transactions on knowledge discovery from data"},
    "TKDE": {"ieee transactions on knowledge and data engineering"},
    "PR": {"pattern recognition"},
    "IJCV": {"international journal of computer vision"},
    "ESWA": {"expert systems with applications"},
    "ASOC": {"applied soft computing"},
    "IPM": {"information processing"},
    "NC": {"neurocomputing"},
    "INS": {"information sciences"},
    "KBS": {"knowledge-based systems"},
    "NEUNET": {"neural networks"},
    "AIR": {"artificial intelligence review"},
    "TMLR": {"transactions on machine learning research"},
    "NATCOMM": {"nature communications"},
    "IJFS": {"international journal of fuzzy systems"},
    "SP": {"signal processing"},
    "SPL": {"ieee signal processing letters"},
}


def _match_venue_abbreviation(
    abbrev: str,
    booktitle: Optional[str],
    journal: Optional[str],
) -> Optional[str]:
    """Check if a venue abbreviation matches the actual booktitle or journal.

    Returns a mismatch reason string if there's a problem, or None if OK.
    """
    venue_text = (booktitle or journal or "").lower()
    if not venue_text:
        return None  # Can't verify without venue info

    known = VENUE_ABBREVIATIONS.get(abbrev)
    if known is None:
        return None  # Unknown abbreviation — can't verify

    for keyword in known:
        if keyword in venue_text:
            return None  # Match found
    venue_display = (booktitle or journal or "")[:60]
    return f"abbreviation '{abbrev}' does not match venue '{venue_display}'"


def check_citation_keys(
    input_path: str,
    log: Optional[Callable[[str], None]] = None,
) -> List[Tuple[str, str, str]]:
    """Check citation key legibility against METHOD_AUTHOR_VENUEYEAR convention.

    Args:
        input_path: Path to the BibTeX file.
        log: Optional logging callback; falls back to ``print``.

    Returns:
        List of ``(entry_id, issue_type, detail)`` tuples where issue_type is
        one of ``"format"``, ``"venue_mismatch"``, or ``"year_mismatch"``.
    """
    log = log or print
    log(f"🔑 Checking citation key legibility in {input_path}...\n")

    try:
        with open(input_path, "r", encoding="utf-8") as f:
            parser = bibtexparser.bparser.BibTexParser(common_strings=True)
            bib_db = bibtexparser.load(f, parser=parser)
    except FileNotFoundError:
        log(f"❌ Error: File '{input_path}' not found.")
        return []

    issues: List[Tuple[str, str, str]] = []

    log(f"{'ID':<45} | {'Issue':<18} | Detail")
    log("-" * 110)

    for entry in bib_db.entries:
        entry_id = entry.get("ID", "")
        match = _KEY_PATTERN.match(entry_id)

        if not match:
            detail = f"expected METHOD_AUTHOR_VENUEYEAR, got '{entry_id}'"
            log(f"{entry_id:<45} | {'format':<18} | {detail}")
            issues.append((entry_id, "format", detail))
            continue

        # Validate year matches entry year
        key_year = match.group("year")
        entry_year = entry.get("year", "").strip()
        if entry_year and key_year != entry_year:
            detail = f"key year={key_year} but entry year={entry_year}"
            log(f"{entry_id:<45} | {'year_mismatch':<18} | {detail}")
            issues.append((entry_id, "year_mismatch", detail))

        # Validate venue abbreviation matches booktitle/journal
        abbrev = match.group("venue")
        booktitle = entry.get("booktitle")
        journal = entry.get("journal")
        venue_issue = _match_venue_abbreviation(abbrev, booktitle, journal)
        if venue_issue:
            log(f"{entry_id:<45} | {'venue_mismatch':<18} | {venue_issue}")
            issues.append((entry_id, "venue_mismatch", venue_issue))

    log("-" * 110)
    total = len(bib_db.entries)
    if not issues:
        log(f"✅ All {total} citation keys follow the convention.")
    else:
        format_count = sum(1 for _, t, _ in issues if t == "format")
        venue_count = sum(1 for _, t, _ in issues if t == "venue_mismatch")
        year_count = sum(1 for _, t, _ in issues if t == "year_mismatch")
        parts = []
        if format_count:
            parts.append(f"format: {format_count}")
        if venue_count:
            parts.append(f"venue mismatch: {venue_count}")
        if year_count:
            parts.append(f"year mismatch: {year_count}")
        log(
            f"⚠️  Found {len(issues)} issues in {total} entries. Breakdown -> {'; '.join(parts)}"
        )

    return issues
