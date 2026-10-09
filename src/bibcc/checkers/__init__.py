"""
BibTeX Quality Checkers package.

Re-exports the checker entry points used by ``bibcc check``:
    from bibcc.checkers import check_missing_fields, check_smart_protection, ...
"""

from __future__ import annotations

from bibcc.checkers.citation_keys import check_citation_keys
from bibcc.checkers.field_issues import check_field_issues
from bibcc.checkers.missing_fields import DEFAULT_ENTRY_TYPES, check_missing_fields
from bibcc.checkers.smart_protection import MIN_TERM_LENGTH, check_smart_protection, load_vocab_file
from bibcc.checkers.template_fields import (
    DEFAULT_JOURNAL_FIELDS,
    DEFAULT_PROCEEDINGS_FIELDS,
    check_template_fields,
)
from bibcc.checkers.title_case import check_title_case, get_style

__all__ = [
    "DEFAULT_ENTRY_TYPES",
    "DEFAULT_JOURNAL_FIELDS",
    "DEFAULT_PROCEEDINGS_FIELDS",
    "MIN_TERM_LENGTH",
    "check_citation_keys",
    "check_field_issues",
    "check_missing_fields",
    "check_smart_protection",
    "check_template_fields",
    "check_title_case",
    "get_style",
    "load_vocab_file",
]
