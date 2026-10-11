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
import sys
from pathlib import Path
from typing import List

from bibcc.bibedit import BibEditError, read_bib, scan
from bibcc.checkers import (
    DEFAULT_ENTRY_TYPES,
    DEFAULT_JOURNAL_FIELDS,
    DEFAULT_PROCEEDINGS_FIELDS,
    MIN_TERM_LENGTH,
    apply_protection,
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
from bibcc.logging_utils import Logger, remove_report, report_dir, write_report
from bibcc.titlecases import STYLES
from bibcc.venues import PROJECT_LIBRARY_NAME, find_project_library, user_library_path


def parse_list_arg(raw: str) -> List[str]:
    """Parse a comma-separated string into a list of stripped items."""
    if not raw:
        return []
    return [item.strip() for item in raw.split(",") if item.strip()]


DESCRIPTION = """\
Run quality checks on a .bib file. Each check has its own option, and you can
combine any number of checks in one run. By default, only the missing-fields
check (for month) runs.

The command never changes the file, except with --title-apply,
--title-interactive, and --quote-apply, which rewrite only the title values.
Empty entries (BibCC's placeholders for papers without official BibTeX) have
no fields to check; the command lists them, and --strict counts them as
findings. Reports go to
.bibcc/INPUT/ next to the input file (only for checks that find something;
a check that finds nothing removes its old report), and the log goes to
.bibcc/INPUT/logs/.

With --check-venues, the command checks the venue library instead, and you
don't need an input file."""

EXIT_STATUS = """\
0 if the checks ran (with --strict, only if they found nothing), 1 with
--strict if a check found something or the file has empty entries, 2 on usage
errors."""


def build_parser() -> argparse.ArgumentParser:
    """Build argument parser for BibTeX checker."""
    parser = argparse.ArgumentParser(
        description=DESCRIPTION,
        epilog=epilog(
            examples=[
                ("Report entries without a month (the default check)", "bibcc check refs.bib"),
                ("Require other fields, in articles only",
                 "bibcc check refs.bib --fields month,publisher --entry-types article"),
                ("Suggest Title Case, and then review the suggestions one by one",
                 "bibcc check refs.bib --title-case --title-interactive"),
                ("Suggest {braces} for acronyms and names, with extra terms",
                 "bibcc check refs.bib --quote --quote-terms Transformer,Adam"),
                ("Find field typos and malformed values, plus duplicates in bib/",
                 "bibcc check refs.bib --check-fields --against bib/"),
                ("Run every check on the file at once",
                 "bibcc check refs.bib --title-case --quote --check-keys --check-fields"),
                ("Brace your own terms in the titles, then report what else needs braces",
                 "bibcc check refs.bib --quote-apply --quote-terms LoRA,CLIP"),
                ("Fail (exit status 1) if any check finds something, for scripts",
                 "bibcc check refs.bib --fields '' --check-keys --check-fields --strict"),
                ("Check the venue library itself", "bibcc check --check-venues"),
            ],
            outputs=[
                (".bibcc/INPUT/missing_fields.txt", "Entries missing a required field"),
                (".bibcc/INPUT/title_case.txt", "Current and suggested titles"),
                (".bibcc/INPUT/smart_protection.txt", "Words that need {braces}"),
                (".bibcc/INPUT/citation_keys.txt", "Keys that don't follow METHOD_AUTHOR_VENUEYEAR"),
                (".bibcc/INPUT/field_issues.txt", "Unknown fields, bad values, and duplicates"),
                (".bibcc/INPUT/logs/checker.log", "Everything printed to the terminal"),
            ],
            exit_status=EXIT_STATUS,
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
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit with status 1 if a check finds something or the file has empty entries.",
    )

    missing = parser.add_argument_group("missing fields (runs by default)")
    missing.add_argument(
        "--fields",
        type=str,
        default="month",
        metavar="FIELDS",
        help="Comma-separated fields that every checked entry must have (default: month). "
        "To skip this check, pass --fields ''.",
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
        help="Suggest APA Title Case: capitalize words of four or more letters and all "
        "other major words; lowercase short articles, conjunctions, and prepositions; "
        "capitalize the first word, the word after a colon or dash, and both parts of "
        "hyphenated words; and leave text in {braces} alone.",
    )
    title.add_argument(
        "--title-apply",
        action="store_true",
        help="Apply all suggestions to the input file (implies --title-case).",
    )
    title.add_argument(
        "--title-interactive",
        action="store_true",
        help="Review each suggestion (accept, skip, edit, or quit), and write the accepted "
        "changes to the input file (implies --title-case).",
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
        "BibTeX styles might lowercase titles. Wrap words whose capitals matter\n"
        "(acronyms, mixed case such as LoRA, words with digits, and names such as\n"
        "Gaussian) in {braces}.",
    )
    quote.add_argument(
        "--quote",
        action="store_true",
        help="Report words to protect with {braces}.",
    )
    quote.add_argument(
        "--quote-apply",
        action="store_true",
        help="Wrap the --quote-terms and --quote-vocab-file terms in braces wherever they appear "
        "in a title with the same case, and then report what else needs braces (implies "
        "--quote). The built-in vocabulary and the other suggestions are never applied.",
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
        help="Don't use the built-in vocabulary of names (such as Gaussian, Bayesian, and Markov).",
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
        help="Check that keys follow METHOD_AUTHOR_VENUEYEAR (for example, "
        "GKEAL_Zhuang_CVPR2023) and that the year and venue in the key match the "
        "entry's year and venue.",
    )

    fields = parser.add_argument_group("field names, values, and duplicates")
    fields.add_argument(
        "--check-fields",
        action="store_true",
        help="Report unknown field names (typos such as 'volumn', which BibTeX silently "
        "ignores), malformed values (years, page ranges, DOIs, months, ISSNs, URLs, and empty "
        "values), and papers or keys that appear twice.",
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
        help="Instead of checking a .bib file, report venue library records that are missing "
        f"fields. Checks the user library and the nearest {PROJECT_LIBRARY_NAME} separately, "
        "or only --venues FILE.",
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
        if args.venues:
            targets = [("library", Path(args.venues))]
        else:
            targets = [("user library", user_library_path())]
            project = find_project_library(args.input or None)
            if project is not None:
                targets.append(("project library", project))
        with Logger("checker") as logger:
            journal_fields = parse_list_arg(args.journal_fields)
            proceedings_fields = parse_list_arg(args.proceedings_fields)
            for n, (label, venues_path) in enumerate(targets):
                if n:
                    logger.log("")
                if not venues_path.exists():
                    logger.log(f"ℹ️  No {label} yet ({venues_path}); see 'bibcc venues -h'.")
                    continue
                logger.log(f"📦 {label.capitalize()}: {venues_path}")
                check_template_fields(
                    venues_path,
                    journal_fields,
                    proceedings_fields,
                    log=logger.log,
                )
        return

    if not args.input:
        build_parser().error("give an input .bib file, or pass --check-venues to check the venue library")
    if not Path(args.input).is_file():
        build_parser().error(f"no such file: {args.input}")
    if args.quote_apply and not (args.quote_terms or args.quote_vocab_file):
        build_parser().error("--quote-apply needs terms: pass --quote-terms, --quote-vocab-file, or both")
    findings = 0

    # Create logger for bib file checking
    with Logger("checker", input_file=args.input) as logger:
        reports = report_dir(args.input)

        def save(kind: str, header: str, rows: List[str], label: str) -> None:
            nonlocal findings
            findings += len(rows)
            path = reports / kind
            if rows:
                write_report(path, header, rows)
                logger.log(f"\n📄 {label} report: {path}")
            else:
                remove_report(path)

        try:
            empty = [e.key for e in scan(read_bib(args.input)) if not e.fields]
        except BibEditError:
            empty = []
        if empty:
            findings += len(empty)
            logger.log(f"📭 {len(empty)} empty entries have no fields, so the checks skip them: {', '.join(empty)}")
            logger.log(f"   To fill them, paste their official BibTeX or run "
                       f"'bibcc add --retry --output {args.input}'.\n")

        required_fields = parse_list_arg(args.fields)
        entry_types = [
            t.lower() for t in parse_list_arg(args.entry_types) or DEFAULT_ENTRY_TYPES
        ]

        # Missing fields
        if required_fields:
            missing_rows = check_missing_fields(
                args.input, required_fields, entry_types, log=logger.log
            )
            save(
                "missing_fields.txt",
                "missing fields: entry_id\ttype\tyear\tfields",
                [f"{rid}\t{rtype}\t{ryear}\t{', '.join(rmiss)}" for rid, rtype, ryear, rmiss in missing_rows],
                "Missing fields",
            )

        # Title case
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
            applied = args.title_apply or args.title_interactive
            save(
                "title_case.txt",
                "title case: entry_id\tcurrent\tsuggested",
                [] if applied else [f"{eid}\t{current}\t{suggested}" for eid, current, suggested in titlecase_rows],
                "Title case",
            )

        # Citation key legibility
        if args.check_keys:
            logger.log("\n")
            key_rows = check_citation_keys(args.input, log=logger.log)
            save(
                "citation_keys.txt",
                "citation keys: entry_id\tissue_type\tdetail",
                [f"{eid}\t{issue_type}\t{detail}" for eid, issue_type, detail in key_rows],
                "Citation key",
            )

        # Field names, values, duplicates
        if args.check_fields:
            logger.log("\n")
            field_rows = check_field_issues(
                args.input,
                against=args.against,
                extra_fields=parse_list_arg(args.known_fields),
                log=logger.log,
            )
            save(
                "field_issues.txt",
                "field issues: entry_id\tissue_type\tdetail",
                [f"{eid}\t{kind}\t{detail}" for eid, kind, detail in field_rows],
                "Field issues",
            )

        # Smart protection
        if args.quote_apply:
            logger.log("\n")
            own_terms = set(parse_list_arg(args.quote_terms))
            if args.quote_vocab_file:
                own_terms |= load_vocab_file(Path(args.quote_vocab_file), log=logger.log, keep_case=True)
            apply_protection(args.input, own_terms, log=logger.log)
        if args.quote or args.quote_apply:
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
            save(
                "smart_protection.txt",
                "smart protection: entry_id\tword\treason",
                [f"{eid}\t{word}\t{reason}" for eid, word, reason in protection_rows],
                "Smart protection",
            )
    if args.strict and findings:
        sys.exit(1)


if __name__ == "__main__":
    parser = build_parser()
    args = parser.parse_args()
    run(args)
