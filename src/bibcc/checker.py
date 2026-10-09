"""
BibTeX Quality Checker — CLI orchestrator.

This module provides the command-line interface that dispatches to individual
sub-checkers in the ``checkers`` package:

- Missing field detection (e.g., month, publisher)
- Title case validation with APA-style rules
- Smart protection suggestions for technical terms and acronyms
- Venue library completeness checking
- Field names, field values, and duplicate papers

Usage:
    # Check for missing fields
    bibcc check input.bib --fields month,publisher

    # Check title case
    bibcc check input.bib --title-case

    # Suggest brace protection for terms
    bibcc check input.bib --quote --quote-terms Gaussian,BERT

    # Check field names/values and look for duplicates in other files
    bibcc check input.bib --check-fields --against bib/

    # Check venue library completeness
    bibcc check --check-venues
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import List

from bibcc.checkers import (
    DEFAULT_ENTRY_TYPES,
    DEFAULT_JOURNAL_FIELDS,
    DEFAULT_PROCEEDINGS_FIELDS,
    MIN_TERM_LENGTH,
    check_citation_keys,
    check_field_issues,
    check_missing_fields,
    check_smart_protection,
    check_template_fields,
    check_title_case,
    get_style,
    load_vocab_file,
)
from bibcc.helptext import ENV_VENUES, VENUES_HELP, HelpFormatter, epilog
from bibcc.logging_utils import Logger, get_output_dir, write_report
from bibcc.titlecases import STYLES
from bibcc.venues import default_library_path


def parse_list_arg(raw: str) -> List[str]:
    """Parse a comma-separated string into a list of stripped items."""
    if not raw:
        return []
    return [item.strip() for item in raw.split(",") if item.strip()]


DESCRIPTION = """\
Run quality checks on a .bib file. Each check has its own option, and any
number of checks can be combined in one run. Only the missing-fields check
(for month) runs by default.

The file is never changed, except by --title-apply and --title-interactive,
which rewrite only the title values. Reports are written to .bibcc/ next to
the input (only for checks that find something), and the log to
.bibcc/logs/.

With --check-venues, the venue library is checked instead, and no input file
is needed."""


def build_parser() -> argparse.ArgumentParser:
    """Build argument parser for BibTeX checker."""
    parser = argparse.ArgumentParser(
        description=DESCRIPTION,
        epilog=epilog(
            examples=[
                ("report entries without a month (the default check)", "bibcc check refs.bib"),
                ("require other fields, in articles only",
                 "bibcc check refs.bib --fields month,publisher --entry-types article"),
                ("suggest Title Case, then review the suggestions one by one",
                 "bibcc check refs.bib --title-case --title-interactive"),
                ("suggest {braces} for acronyms and names, with extra terms",
                 "bibcc check refs.bib --quote --quote-terms Transformer,Adam"),
                ("field typos and malformed values, plus duplicates in bib/",
                 "bibcc check refs.bib --check-fields --against bib/"),
                ("run every check on the file at once",
                 "bibcc check refs.bib --title-case --quote --check-keys --check-fields"),
                ("check the venue library itself", "bibcc check --check-venues"),
            ],
            outputs=[
                (".bibcc/<input>.missing_fields.txt", "entries missing a required field"),
                (".bibcc/<input>.title_case.txt", "current and suggested titles"),
                (".bibcc/<input>.smart_protection.txt", "words that need {braces}"),
                (".bibcc/<input>.citation_keys.txt", "keys not following METHOD_AUTHOR_VENUEYEAR"),
                (".bibcc/<input>.field_issues.txt", "unknown fields, bad values, duplicates"),
                (".bibcc/logs/<input>.checker.log", "everything printed to the terminal"),
            ],
            env=[ENV_VENUES],
        ),
        formatter_class=HelpFormatter,
    )
    parser.add_argument(
        "input",
        type=str,
        nargs="?",  # Make optional for --check-venues mode
        default="",
        help="The .bib file to check (not needed with --check-venues).",
    )

    missing = parser.add_argument_group("missing fields (runs by default)")
    missing.add_argument(
        "--fields",
        type=str,
        default="month",
        metavar="FIELDS",
        help="Comma-separated fields every checked entry must have (default: month). "
        "Pass --fields '' to skip this check.",
    )
    missing.add_argument(
        "--entry-types",
        type=str,
        default=",".join(DEFAULT_ENTRY_TYPES),
        metavar="TYPES",
        help=f"Comma-separated entry types to check (default: {','.join(DEFAULT_ENTRY_TYPES)}).",
    )

    title = parser.add_argument_group("title case")
    title.add_argument(
        "--title-case",
        action="store_true",
        help="Suggest APA Title Case: words of four or more letters and all other "
        "major words capitalized, short articles, conjunctions, and prepositions "
        "lowercase, the first word and the word after a colon or dash capitalized, "
        "both parts of hyphenated words capitalized, and text in {braces} left alone.",
    )
    title.add_argument(
        "--title-apply",
        action="store_true",
        help="Apply all suggestions to the input file (implies --title-case).",
    )
    title.add_argument(
        "--title-interactive",
        action="store_true",
        help="Review each suggestion: accept, skip, edit, or quit; accepted changes are "
        "written to the input file (implies --title-case).",
    )
    title.add_argument(
        "--title-style",
        type=str,
        default="apa",
        choices=sorted(STYLES),
        help="Title case rules to use (default: apa).",
    )
    title.add_argument(
        "--extra-stopwords",
        type=str,
        default="",
        metavar="WORDS",
        help="Comma-separated extra words to keep lowercase.",
    )

    quote = parser.add_argument_group(
        "term protection",
        "BibTeX styles may lowercase titles. Words whose capitals matter (acronyms,\n"
        "mixed case such as LoRA, words with digits, names such as Gaussian) must be\n"
        "wrapped in {braces}.",
    )
    quote.add_argument(
        "--quote",
        action="store_true",
        help="Report words that should be protected with {braces}.",
    )
    quote.add_argument(
        "--quote-terms",
        type=str,
        default="",
        metavar="TERMS",
        help="Comma-separated extra terms to protect, in addition to the built-in vocabulary.",
    )
    quote.add_argument(
        "--quote-vocab-file",
        type=str,
        default=None,
        metavar="FILE",
        help="Text file with one extra term to protect per line.",
    )
    quote.add_argument(
        "--quote-no-default",
        action="store_true",
        help="Do not use the built-in vocabulary of names (Gaussian, Bayesian, Markov, ...).",
    )
    quote.add_argument(
        "--protection-min-length",
        type=int,
        default=MIN_TERM_LENGTH,
        metavar="N",
        help="Shortest acronym, mixed-case, or digit-bearing word to report "
        f"(default: {MIN_TERM_LENGTH}).",
    )

    keys = parser.add_argument_group("citation keys")
    keys.add_argument(
        "--check-keys",
        action="store_true",
        help="Check that keys follow METHOD_AUTHOR_VENUEYEAR (e.g. GKEAL_Zhuang_CVPR2023), "
        "and that the year and venue in the key match the entry's year and venue.",
    )

    fields = parser.add_argument_group("field names, values, and duplicates")
    fields.add_argument(
        "--check-fields",
        action="store_true",
        help="Report unknown field names (typos such as 'volumn', which BibTeX silently "
        "ignores), malformed values (years, page ranges, DOIs, months, ISSNs, URLs, empty "
        "values), and the same paper or key appearing twice.",
    )
    fields.add_argument(
        "--known-fields",
        type=str,
        default="",
        metavar="FIELDS",
        help="Comma-separated extra field names to accept as known.",
    )
    fields.add_argument(
        "--against",
        action="append",
        default=[],
        metavar="PATH",
        help="Also look for duplicates in this .bib file or directory (searched "
        "recursively). Repeatable.",
    )

    venues = parser.add_argument_group("venue library")
    venues.add_argument(
        "--check-venues",
        "--check-templates",
        dest="check_venues",
        action="store_true",
        help="Report venue library records missing fields, instead of checking a .bib file.",
    )
    venues.add_argument(
        "--venues",
        type=str,
        default="",
        metavar="FILE",
        help=VENUES_HELP,
    )
    venues.add_argument(
        "--journal-fields",
        type=str,
        default=",".join(DEFAULT_JOURNAL_FIELDS),
        metavar="FIELDS",
        help=f"Fields every journal record should have (default: {','.join(DEFAULT_JOURNAL_FIELDS)}).",
    )
    venues.add_argument(
        "--proceedings-fields",
        type=str,
        default=",".join(DEFAULT_PROCEEDINGS_FIELDS),
        metavar="FIELDS",
        help="Fields every proceedings record should have "
        f"(default: {','.join(DEFAULT_PROCEEDINGS_FIELDS)}).",
    )

    return parser


def run(args: argparse.Namespace) -> None:
    """Run checker with parsed arguments."""
    # Venue library checking mode
    if args.check_venues:
        venues_path = Path(args.venues) if args.venues else default_library_path()
        log_dir = get_output_dir() / "logs"
        with Logger("checker", input_file=venues_path, log_dir=log_dir) as logger:
            journal_fields = parse_list_arg(args.journal_fields)
            proceedings_fields = parse_list_arg(args.proceedings_fields)
            check_template_fields(
                venues_path,
                journal_fields,
                proceedings_fields,
                log=logger.log,
            )
        return

    if not args.input:
        build_parser().error("an input .bib file is required unless --check-venues is used")

    report_dir = get_output_dir(args.input)
    base_name = Path(args.input).name

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
                report_path = report_dir / f"{base_name}.missing_fields.txt"
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
                report_path = report_dir / f"{base_name}.title_case.txt"
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
                report_path = report_dir / f"{base_name}.citation_keys.txt"
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

        # Field names, values, duplicates
        if args.check_fields:
            logger.log("\n")
            field_rows = check_field_issues(
                args.input,
                against=args.against,
                extra_fields=parse_list_arg(args.known_fields),
                log=logger.log,
            )
            if field_rows:
                report_path = report_dir / f"{base_name}.field_issues.txt"
                rows = [f"{eid}\t{kind}\t{detail}" for eid, kind, detail in field_rows]
                write_report(
                    report_path,
                    "field issues: entry_id\tissue_type\tdetail",
                    rows,
                )
                logger.log(f"\n📄 Field issues report: {report_path}")

        # Smart protection
        protection_rows = []
        if args.quote:
            logger.log("\n")
            extra_vocab: List[str] = []
            if args.quote_vocab_file:
                extra_vocab.extend(
                    load_vocab_file(Path(args.quote_vocab_file), log=logger.log)
                )
            extra_vocab.extend(parse_list_arg(args.quote_terms))
            protection_rows = check_smart_protection(
                args.input,
                extra_vocab,
                use_default_vocab=not args.quote_no_default,
                min_length=args.protection_min_length,
                log=logger.log,
            )
            if protection_rows:
                report_path = report_dir / f"{base_name}.smart_protection.txt"
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
