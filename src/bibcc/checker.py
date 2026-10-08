"""
BibTeX Quality Checker — CLI orchestrator.

This module provides the command-line interface that dispatches to individual
sub-checkers in the ``checkers`` package:

- Missing field detection (e.g., month, publisher)
- Title case validation with APA-style rules
- Smart protection suggestions for technical terms and acronyms
- Template completeness checking

Usage:
    # Check for missing fields
    python checker.py input.bib --fields month,publisher

    # Check title case
    python checker.py input.bib --title-case

    # Suggest brace protection for terms
    python checker.py input.bib --quote --quote-terms Gaussian,BERT

    # Check template completeness
    python checker.py --check-templates
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import List

from bibcc.checkers import (
    DEFAULT_ENTRY_TYPES,
    DEFAULT_JOURNAL_FIELDS,
    DEFAULT_PROCEEDINGS_FIELDS,
    check_citation_keys,
    check_missing_fields,
    check_smart_protection,
    check_template_fields,
    load_vocab_file,
    parse_terms,
)
from bibcc.checkers.title_case import check_title_case, get_style
from bibcc.logging_utils import Logger, get_repo_dir, write_report


def parse_list_arg(raw: str) -> List[str]:
    """Parse a comma-separated string into a list of stripped items."""
    if not raw:
        return []
    return [item.strip() for item in raw.split(",") if item.strip()]


def build_parser() -> argparse.ArgumentParser:
    """Build argument parser for BibTeX checker."""
    parser = argparse.ArgumentParser(
        description="Unified checker for BibTeX: missing fields, title case, and smart protection."
    )
    parser.add_argument(
        "input",
        type=str,
        nargs="?",  # Make optional for --check-templates mode
        default="",
        help="Path to the input BibTeX (.bib) file",
    )
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
        "--title-apply",
        action="store_true",
        help="Apply Title Case suggestions in-place (implies --title-case).",
    )
    parser.add_argument(
        "--title-interactive",
        action="store_true",
        help="Interactive mode: review each suggestion one-by-one (implies --title-case).",
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
    parser.add_argument(
        "--protection-min-length",
        type=int,
        default=3,
        help="Minimum word length for mixed-case / acronym detection (default: 3).",
    )
    parser.add_argument(
        "--check-keys",
        action="store_true",
        help="Check citation key legibility (METHOD_AUTHOR_VENUEYEAR convention).",
    )
    parser.add_argument(
        "--check-templates",
        action="store_true",
        help="Check templates.py for missing fields instead of a bib file.",
    )
    parser.add_argument(
        "--templates-path",
        type=str,
        default=str(Path(__file__).parent / "templates.py"),
        help="Path to templates.py file (default: the bundled templates.py).",
    )
    parser.add_argument(
        "--journal-fields",
        type=str,
        default=",".join(DEFAULT_JOURNAL_FIELDS),
        help=f"Comma-separated fields to check in journal templates (default: {','.join(DEFAULT_JOURNAL_FIELDS)}).",
    )
    parser.add_argument(
        "--proceedings-fields",
        type=str,
        default=",".join(DEFAULT_PROCEEDINGS_FIELDS),
        help=f"Comma-separated fields to check in proceedings templates (default: {','.join(DEFAULT_PROCEEDINGS_FIELDS)}).",
    )

    return parser


def run(args: argparse.Namespace) -> None:
    """Run checker with parsed arguments."""
    # All outputs go to repo directory
    repo_dir = get_repo_dir()
    base_name = Path(args.input).name if args.input else "templates.py"

    # Template checking mode
    if args.check_templates:
        with Logger("checker", input_file=args.templates_path) as logger:
            journal_fields = parse_list_arg(args.journal_fields)
            proceedings_fields = parse_list_arg(args.proceedings_fields)
            check_template_fields(
                Path(args.templates_path),
                journal_fields,
                proceedings_fields,
                log=logger.log,
            )
        return

    # Create logger for bib file checking
    with Logger("checker", input_file=args.input) as logger:
        required_fields = parse_list_arg(args.fields)
        entry_types = [
            t.lower() for t in parse_list_arg(args.entry_types) or DEFAULT_ENTRY_TYPES
        ]

        # Missing fields
        missing_rows = []
        if required_fields:
            missing_rows = check_missing_fields(
                args.input, required_fields, entry_types, log=logger.log
            )
            if missing_rows:
                report_path = repo_dir / f"{base_name}.missing_fields.txt"
                rows = [
                    f"{rid}\t{rtype}\t{ryear}\t{', '.join(rmiss)}"
                    for rid, rtype, ryear, rmiss in missing_rows
                ]
                write_report(
                    report_path,
                    "missing fields: entry_id\ttype\tyear\tfields",
                    rows,
                )
                logger.log(f"\n📄 Missing fields report: {report_path}")

        # Title case
        titlecase_rows = []
        if args.title_case or args.title_apply or args.title_interactive:
            logger.log("\n")
            style = get_style(args.title_style)
            stopwords = set(style.stopwords)
            stopwords.update([s.lower() for s in parse_list_arg(args.extra_stopwords)])
            titlecase_rows = check_title_case(
                args.input,
                stopwords,
                style.name,
                apply=args.title_apply,
                interactive=args.title_interactive,
                log=logger.log,
            )
            if titlecase_rows and not args.title_apply and not args.title_interactive:
                report_path = repo_dir / f"{base_name}.title_case.txt"
                rows = [
                    f"{eid}\t{current}\t{suggested}"
                    for eid, current, suggested in titlecase_rows
                ]
                write_report(
                    report_path,
                    "title case: entry_id\tcurrent\tsuggested",
                    rows,
                )
                logger.log(f"\n📄 Title case report: {report_path}")

        # Citation key legibility
        key_rows = []
        if args.check_keys:
            logger.log("\n")
            key_rows = check_citation_keys(args.input, log=logger.log)
            if key_rows:
                report_path = repo_dir / f"{base_name}.citation_keys.txt"
                rows = [
                    f"{eid}\t{issue_type}\t{detail}"
                    for eid, issue_type, detail in key_rows
                ]
                write_report(
                    report_path,
                    "citation keys: entry_id\tissue_type\tdetail",
                    rows,
                )
                logger.log(f"\n📄 Citation key report: {report_path}")

        # Smart protection
        protection_rows = []
        if args.quote:
            logger.log("\n")
            extra_vocab: List[str] = []
            if args.quote_vocab_file:
                extra_vocab.extend(load_vocab_file(Path(args.quote_vocab_file)))
            extra_vocab.extend(parse_terms(args.quote_terms))
            protection_rows = check_smart_protection(
                args.input,
                extra_vocab,
                use_default_vocab=not args.quote_no_default,
                min_length=args.protection_min_length,
                log=logger.log,
            )
            if protection_rows:
                report_path = repo_dir / f"{base_name}.smart_protection.txt"
                rows = [
                    f"{eid}\t{word}\t{reason}" for eid, word, reason in protection_rows
                ]
                write_report(
                    report_path,
                    "smart protection: entry_id\tword\treason",
                    rows,
                )
                logger.log(f"\n📄 Smart protection report: {report_path}")


if __name__ == "__main__":
    parser = build_parser()
    args = parser.parse_args()
    run(args)
