"""
BibTeX Quality Checkers package.

Re-exports the checker entry points used by ``bibcc check``:
    from bibcc.checkers import check_missing_fields, check_smart_protection, ...
"""

from __future__ import annotations

from bibcc.checkers.citation_keys import check_citation_keys
from bibcc.checkers.edition_fields import DEFAULT_IGNORED_FIELDS, check_edition_fields
from bibcc.checkers.edition_fields import FIELDS_HEADER as EDITION_FIELDS_HEADER
from bibcc.checkers.edition_fields import SCHEMAS_HEADER as EDITION_SCHEMAS_HEADER
from bibcc.checkers.field_issues import check_field_issues, trim_fields
from bibcc.checkers.missing_fields import DEFAULT_ENTRY_TYPES, check_missing_fields
from bibcc.checkers.official_fields import (
    APPLY_ALL,
    FIELDS_HEADER,
    UNCHECKED_HEADER,
    VENUES_HEADER,
    check_official_fields,
)
from bibcc.checkers.smart_protection import (
    DEFAULT_VOCAB,
    MIN_TERM_LENGTH,
    apply_protection,
    auto_vocab_path,
    check_smart_protection,
    load_vocab_file,
)
from bibcc.checkers.template_fields import (
    DEFAULT_JOURNAL_FIELDS,
    DEFAULT_PROCEEDINGS_FIELDS,
    check_edition_consistency,
    check_template_fields,
)
from bibcc.checkers.title_case import check_title_case, get_style

__all__ = [
    "APPLY_ALL",
    "FIELDS_HEADER",
    "UNCHECKED_HEADER",
    "VENUES_HEADER",
    "DEFAULT_ENTRY_TYPES",
    "DEFAULT_IGNORED_FIELDS",
    "DEFAULT_JOURNAL_FIELDS",
    "DEFAULT_PROCEEDINGS_FIELDS",
    "DEFAULT_VOCAB",
    "EDITION_FIELDS_HEADER",
    "EDITION_SCHEMAS_HEADER",
    "MIN_TERM_LENGTH",
    "apply_protection",
    "auto_vocab_path",
    "check_citation_keys",
    "check_edition_consistency",
    "check_edition_fields",
    "check_field_issues",
    "check_missing_fields",
    "check_official_fields",
    "check_smart_protection",
    "check_template_fields",
    "check_title_case",
    "get_style",
    "load_vocab_file",
    "trim_fields",
]
