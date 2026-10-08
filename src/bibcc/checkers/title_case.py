"""
Title case checker wrapper.

Re-exports the title case checking functions from titlecases.py so that
all checker imports come from the ``checkers`` package uniformly.

Usage:
    from bibcc.checkers.title_case import check_title_case, get_style

    issues = check_title_case("refs.bib", style_name="apa")
"""

from __future__ import annotations

from bibcc.titlecases import DEFAULT_STOPWORDS, check_title_case, get_style

__all__ = [
    "DEFAULT_STOPWORDS",
    "check_title_case",
    "get_style",
]
