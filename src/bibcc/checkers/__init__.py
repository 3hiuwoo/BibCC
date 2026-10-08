"""
BibTeX Quality Checkers package.

Re-exports all checker functions for convenient access:
    from bibcc.checkers import check_missing_fields, check_smart_protection, ...
"""

from __future__ import annotations

from bibcc.checkers.citation_keys import VENUE_ABBREVIATIONS, check_citation_keys
from bibcc.checkers.missing_fields import DEFAULT_ENTRY_TYPES, check_missing_fields
from bibcc.checkers.smart_protection import (
    DEFAULT_VOCAB,
    check_smart_protection,
    load_vocab_file,
    parse_terms,
)
from bibcc.checkers.template_fields import (
    DEFAULT_JOURNAL_FIELDS,
    DEFAULT_PROCEEDINGS_FIELDS,
    VENUE_FIELD_OVERRIDES,
    check_template_fields,
)
from bibcc.checkers.title_case import DEFAULT_STOPWORDS, check_title_case, get_style

__all__ = [
    "DEFAULT_ENTRY_TYPES",
    "DEFAULT_JOURNAL_FIELDS",
    "DEFAULT_PROCEEDINGS_FIELDS",
    "DEFAULT_STOPWORDS",
    "DEFAULT_VOCAB",
    "VENUE_ABBREVIATIONS",
    "check_citation_keys",
    "check_missing_fields",
    "check_smart_protection",
    "check_template_fields",
    "check_title_case",
    "get_style",
    "load_vocab_file",
    "parse_terms",
]
