"""
BibTeX Quality Checker — CLI orchestrator.

This module provides the command-line interface that dispatches to individual
sub-checkers in the ``checkers`` package.  Each check is a subcommand:

- ``missing``: Missing field detection (for example, month and publisher)
- ``title``: Title case validation with APA-style rules
- ``quote``: Smart protection suggestions for technical terms and acronyms
- ``keys``: Citation key legibility
- ``fields``: Field names, field values, and duplicate papers
- ``editions``: Fields that other entries of the same venue have and an entry lacks
- ``official``: Differences from the official BibTeX, downloaded again
- ``venues``: Venue library completeness checking

Usage:
    bibcc check missing input.bib --fields month,publisher
    bibcc check title input.bib
    bibcc check quote input.bib --terms Gaussian,BERT
    bibcc check fields input.bib --against bib/
    bibcc check venues
"""

from __future__ import annotations

import argparse
import sys
import textwrap
from pathlib import Path
from typing import Callable, List, Optional

from bibcc.bibedit import BibEditError, read_bib, scan
from bibcc.checkers import (
    APPLY_ALL,
    DEFAULT_ENTRY_TYPES,
    DEFAULT_IGNORED_FIELDS,
    DEFAULT_JOURNAL_FIELDS,
    DEFAULT_PROCEEDINGS_FIELDS,
    DEFAULT_VOCAB,
    FIELDS_HEADER,
    MIN_TERM_LENGTH,
    SAME_YEAR,
    UNCHECKED_HEADER,
    VENUES_HEADER,
    apply_protection,
    auto_vocab_path,
    check_citation_keys,
    check_edition_fields,
    check_field_issues,
    check_missing_fields,
    check_official_fields,
    check_smart_protection,
    check_template_fields,
    check_title_case,
    get_style,
    load_vocab_file,
    trim_fields,
)
from bibcc.helptext import ENV_VENUES, VENUES_HELP, HelpFormatter, epilog
from bibcc.logging_utils import Logger, remove_report, report_dir, write_report
from bibcc.titlecases import STYLES
from bibcc.venues import PROJECT_LIBRARY_NAME, find_project_library, load_library, user_library_path


def parse_list_arg(raw: str) -> List[str]:
    """Parse a comma-separated string into a list of stripped items."""
    if not raw:
        return []
    return [item.strip() for item in raw.split(",") if item.strip()]


DESCRIPTION = """\
Run a quality check on a .bib file. Each check is a subcommand, so a run does
only the check you name. To run several checks, run the command once for each.
For the options of a check, run 'bibcc check CHECK -h'.

The checks never change the file, except title --apply, title --interactive,
quote --apply, and quote --interactive, which rewrite only the title values,
fields --apply,
which removes only the interim and empty fields that the check reports, and official
--apply, which adds only the fields you name from the official BibTeX. Only
the official check reaches the network. Empty entries
(BibCC's placeholders for papers without official BibTeX) have no fields to
check; each check lists them, and --strict counts them as findings. Reports go to
.bibcc/INPUT/ next to the input file (only when the check finds something; a
check that finds nothing removes its old report), and the log goes to
.bibcc/INPUT/logs/.

The venues check reads the venue library instead, and doesn't need an input
file."""

EXIT_STATUS = """\
0 if the check ran (with --strict, only if it found nothing), 1 with --strict
if the check found something or the file has empty entries, 2 on usage
errors."""

LOG_OUTPUT = (".bibcc/INPUT/logs/checker.log", "Everything printed to the terminal")


def _file_check(
    subparsers: argparse._SubParsersAction,
    name: str,
    summary: str,
    description: str,
    examples: List[tuple],
    report: tuple,
    more_reports: Optional[List[tuple]] = None,
) -> argparse.ArgumentParser:
    """Add the subcommand for a check of a .bib file, with INPUT and --strict."""
    parser = subparsers.add_parser(
        name,
        help=summary,
        description=description,
        epilog=epilog(examples=examples, outputs=[report, *(more_reports or []), LOG_OUTPUT],
                      exit_status=EXIT_STATUS),
        formatter_class=HelpFormatter,
    )
    parser.add_argument("input", type=str, metavar="INPUT", help="The .bib file to check.")
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit with status 1 if the check finds something or the file has empty entries.",
    )
    return parser


def build_parser() -> argparse.ArgumentParser:
    """Build argument parser for BibTeX checker."""
    parser = argparse.ArgumentParser(
        description=DESCRIPTION,
        epilog=epilog(
            examples=[
                ("Report entries without a month", "bibcc check missing refs.bib"),
                ("Suggest Title Case, and then review the suggestions one by one",
                 "bibcc check title refs.bib --interactive"),
                ("Suggest {braces} for acronyms and names, with extra terms",
                 "bibcc check quote refs.bib --terms Transformer,Adam"),
                ("Check that keys follow METHOD_AUTHOR_VENUEYEAR", "bibcc check keys refs.bib"),
                ("Find field typos and malformed values, plus duplicates in bib/",
                 "bibcc check fields refs.bib --against bib/"),
                ("Find fields that other entries of the same venue have",
                 "bibcc check editions refs.bib --against bib/"),
                ("Compare the entries with their official BibTeX", "bibcc check official refs.bib"),
                ("Check the venue library itself", "bibcc check venues"),
            ],
            exit_status=EXIT_STATUS,
            env=[ENV_VENUES],
        ),
        formatter_class=HelpFormatter,
    )
    subparsers = parser.add_subparsers(dest="check", required=True, metavar="CHECK")

    # --- missing ---
    missing = _file_check(
        subparsers,
        "missing",
        summary="Report entries that lack required fields (default: month).",
        description="""\
Report the entries of INPUT that lack one of the required fields. An entry
without a month isn't reported when its venue library record has month: none,
which means that the venue's entries have no month: a conference held across
two months, or a journal without monthly issues.""",
        examples=[
            ("Report entries without a month", "bibcc check missing refs.bib"),
            ("Require other fields, in articles only",
             "bibcc check missing refs.bib --fields month,publisher --entry-types article"),
        ],
        report=(".bibcc/INPUT/missing_fields.txt", "Entries missing a required field"),
    )
    missing.add_argument(
        "--fields",
        type=str,
        default="month",
        metavar="FIELDS",
        help="Comma-separated fields that every checked entry must have (default: month).",
    )
    missing.add_argument(
        "--entry-types",
        type=str,
        default=",".join(DEFAULT_ENTRY_TYPES),
        metavar="TYPES",
        help=f"Comma-separated entry types to check (default: {','.join(DEFAULT_ENTRY_TYPES)}).",
    )
    missing.add_argument("--venues", type=str, default="", metavar="FILE", help=VENUES_HELP)

    # --- title ---
    title = _file_check(
        subparsers,
        "title",
        summary="Suggest Title Case for the titles, and optionally apply it.",
        description="""\
Suggest Title Case for the titles of INPUT. With APA rules, the check
capitalizes words of four or more letters and all other major words;
lowercases short articles, conjunctions, and prepositions; capitalizes the
first word, the word after a colon or dash, and both parts of hyphenated
words; and leaves text in {braces} alone.""",
        examples=[
            ("Report the suggestions", "bibcc check title refs.bib"),
            ("Review each suggestion, and write the accepted ones",
             "bibcc check title refs.bib --interactive"),
            ("Apply every suggestion", "bibcc check title refs.bib --apply"),
        ],
        report=(".bibcc/INPUT/title_case.txt", "Current and suggested titles"),
    )
    title_mode = title.add_mutually_exclusive_group()
    title_mode.add_argument(
        "--apply",
        action="store_true",
        help="Apply all suggestions to the input file.",
    )
    title_mode.add_argument(
        "--interactive",
        action="store_true",
        help="Review each suggestion (accept, skip, edit, or quit), and write the accepted "
        "changes to the input file.",
    )
    title.add_argument(
        "--style",
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

    # --- quote ---
    quote = _file_check(
        subparsers,
        "quote",
        summary="Report words that need {braces}, and compounds braced as a whole.",
        description="""\
BibTeX styles might lowercase titles. Report the words in the titles of INPUT
whose capitals matter (acronyms, mixed case such as LoRA, words with digits,
and names such as Gaussian) and that aren't in {braces} yet.

The check also reports hyphenated or slashed compounds braced as a whole when
only some parts need braces: {CLIP-Based} should be {CLIP}-Based, so that
styles can still lowercase "Based". A compound stays whole when every part
needs braces, as in method names such as {SD-LoRA}, {R-CNN}, and {GPT-4}. To
keep another compound whole, such as the method name {CIP-Net}, list it with
--terms or --vocab-file, or add it to .bibcc/INPUT/vocab.txt (one term per
line), which the check always reads.""",
        examples=[
            ("Report words to brace", "bibcc check quote refs.bib"),
            ("Report words to brace, with extra terms",
             "bibcc check quote refs.bib --terms Transformer,Adam"),
            ("Brace your own terms and split over-braced compounds, then report the rest",
             "bibcc check quote refs.bib --apply --terms LoRA,CLIP,Transformer-XL"),
            ("Review each compound split, and keep the method names whole",
             "bibcc check quote refs.bib --interactive"),
        ],
        report=(".bibcc/INPUT/smart_protection.txt", "Words that need {braces}, and over-braced compounds"),
    )
    quote_mode = quote.add_mutually_exclusive_group()
    quote_mode.add_argument(
        "--apply",
        action="store_true",
        help="Wrap the --terms and --vocab-file terms in braces wherever they appear in a title "
        "with the same case, split over-braced compounds, and then report what else needs "
        "braces. The built-in vocabulary and the other suggestions are never applied.",
    )
    quote_mode.add_argument(
        "--interactive",
        action="store_true",
        help="Review each over-braced compound one at a time: split it, skip it, edit the "
        "suggestion, or keep it whole and add it to .bibcc/INPUT/vocab.txt, so that later "
        "runs leave it whole. The --terms and --vocab-file terms are still braced, and "
        "the accepted changes are written to the input file.",
    )
    quote.add_argument(
        "--terms",
        type=str,
        default="",
        metavar="TERMS",
        help="Comma-separated extra terms to protect, in addition to the built-in vocabulary.",
    )
    quote.add_argument(
        "--vocab-file",
        type=str,
        default=None,
        metavar="FILE",
        help="Text file with one extra term to protect per line; blank lines and # comments "
        "are ignored. .bibcc/INPUT/vocab.txt is always read, with or without this option.",
    )
    quote.add_argument(
        "--no-default",
        action="store_true",
        help="Don't use the built-in vocabulary of names (such as Gaussian, Bayesian, and Markov).",
    )
    quote.add_argument(
        "--min-length",
        type=int,
        default=MIN_TERM_LENGTH,
        metavar="N",
        help="Shortest acronym, mixed-case, or digit-bearing word to report "
        f"(default: {MIN_TERM_LENGTH}).",
    )

    # --- keys ---
    _file_check(
        subparsers,
        "keys",
        summary="Check that citation keys follow METHOD_AUTHOR_VENUEYEAR.",
        description="""\
Check that the keys of INPUT follow METHOD_AUTHOR_VENUEYEAR (for example,
GKEAL_Zhuang_CVPR2023), and that the author, year, and venue in each key
match the entry's first author, year, and venue.""",
        examples=[
            ("Check the keys", "bibcc check keys refs.bib"),
            ("Fail (exit status 1) on a bad key, for scripts", "bibcc check keys refs.bib --strict"),
        ],
        report=(".bibcc/INPUT/citation_keys.txt", "Keys that don't follow METHOD_AUTHOR_VENUEYEAR"),
    )

    # --- fields ---
    fields = _file_check(
        subparsers,
        "fields",
        summary="Report unknown field names, malformed values, and duplicate papers.",
        description="""\
Report unknown field names in INPUT (typos such as 'volumn', which BibTeX
silently ignores), malformed values (years, page ranges, DOIs, months, ISSNs,
URLs, and empty values), and papers or keys that appear twice.

The check also reports interim fields (issue type interim_field): fields that
only an interim or preprint version of a paper has, left in an entry whose
BibTeX now comes from somewhere else. For example, IEEE Xplore BibTeX for a
CVPR paper has no url, so a CVF Open Access url in it is left over from the
CVF entry. The check looks for CVF Open Access, OpenReview, and arXiv URLs,
the arXiv fields (eprint, archiveprefix, and primaryclass), and arXiv notes.

To remove the interim fields and the empty fields (empty_value, such as the
volume = {} that IEEE Xplore exports), pass --apply.

It also reports conference papers exported as @article (issue type
conference_article), such as AAAI's BibTeX, whose journal names the
proceedings. To make them @inproceedings, with that name as the booktitle,
run 'bibcc complete'.""",
        examples=[
            ("Find field typos and malformed values", "bibcc check fields refs.bib"),
            ("Also look for duplicates in bib/", "bibcc check fields refs.bib --against bib/"),
            ("Accept extra field names", "bibcc check fields refs.bib --known-fields code,pdf"),
            ("Remove interim and empty fields, then report the rest", "bibcc check fields refs.bib --apply"),
        ],
        report=(".bibcc/INPUT/field_issues.txt", "Unknown fields, bad values, interim fields, and duplicates"),
    )
    fields.add_argument(
        "--apply",
        action="store_true",
        help="Remove the interim fields and the empty fields from the input file, and then report "
        "what's left. Other findings are never changed.",
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

    # --- editions ---
    editions = _file_check(
        subparsers,
        "editions",
        summary="Report fields that other entries of the same venue have and an entry lacks.",
        description="""\
Compare each entry of INPUT with the other entries of its venue, in every
edition (year), and report the fields that the entry lacks and the others
have. The official BibTeX of a venue usually has the same fields every year,
so a gap is either a lost field or a change of the venue's BibTeX. The check
reports two kinds of findings:

  same_year    Most other entries of the same venue and year have the field,
               so the entry is probably incomplete.
  other_years  Few or none of this year's entries have the field, but most
               other years do. The venue might have changed its BibTeX.

To compare with more entries, add your other .bib files with --against; the
check reports only the entries of INPUT. When the venue library has the
venue, the evidence says whether the library supplies the missing field.

""" + textwrap.fill(
            f"The check ignores these fields: {', '.join(DEFAULT_IGNORED_FIELDS)}. To ignore more, "
            "pass --ignore-fields; to compare one of them anyway, pass --include-fields. It also "
            "leaves out entries with an interim (CVF or OpenReview) booktitle, entries built from "
            "metadata, and empty entries. With --strict, only same_year findings count.",
            width=78,
        ),
        examples=[
            ("Compare the entries with each other", "bibcc check editions refs.bib"),
            ("Also compare them with the entries in bib/", "bibcc check editions refs.bib --against bib/"),
            ("Also compare the urldate field, and ignore abstract",
             "bibcc check editions refs.bib --include-fields urldate --ignore-fields abstract"),
        ],
        report=(".bibcc/INPUT/edition_fields.txt", "Fields that other entries of the venue have"),
    )
    editions.add_argument(
        "--against",
        action="append",
        default=[],
        metavar="PATH",
        help="Also compare with the entries in this .bib file or directory (searched "
        "recursively). Repeatable.",
    )
    editions.add_argument(
        "--ignore-fields",
        type=str,
        default="",
        metavar="FIELDS",
        help="Comma-separated fields to ignore, in addition to the default ones.",
    )
    editions.add_argument(
        "--include-fields",
        type=str,
        default="",
        metavar="FIELDS",
        help="Comma-separated fields to compare even though the check ignores them by default "
        "(for example, urldate).",
    )
    editions.add_argument("--venues", type=str, default="", metavar="FILE", help=VENUES_HELP)

    # --- official ---
    official = _file_check(
        subparsers,
        "official",
        summary="Compare the entries with their official BibTeX, downloaded again.",
        description="""\
Download the official BibTeX of each entry of INPUT again, the same way 'bibcc
add' does, and compare it with the entry field by field. Use it to find the
fields that your entries lost, and to add them back with --apply. The check
needs network access; to wait between downloads, set --delay.

The check reports four kinds of findings for each entry:

  upstream_only  The official BibTeX has a field that the entry lacks.
  differs        Both have the field, with different values (braces, case,
                 whitespace, accents, and month spellings don't count).
  local_only     The entry has a field that the official BibTeX lacks, other
                 than citation and the fields that the venue library supplies.
  type           The entry types differ.

The venue summary says, for each venue and year, how many checked entries
the official BibTeX gives a field, and how many of them lack it. The summary
also compares the venue library records with the official values.

For the publishers that BibCC can't download from (AAAI, ACM, and Elsevier),
get the official BibTeX yourself, save it in a directory, and pass it with
--local. An entry matches a local entry by citation key, file name, DOI, or
title. With --offline, the check uses only the --local files.

The check skips preprints, interim (CVF or OpenReview) entries, and entries
built from metadata, because 'bibcc upgrade' replaces them. With --strict,
only upstream_only, differs, and type findings count.""",
        examples=[
            ("Compare every entry with its official BibTeX", "bibcc check official refs.bib"),
            ("Add the official day and series fields that entries lack",
             "bibcc check official refs.bib --apply day,series"),
            ("Use the BibTeX you saved by hand for the blocked publishers",
             "bibcc check official refs.bib --local exports/"),
            ("Compare two entries only", "bibcc check official refs.bib --ids A_Doe_ICML2025,B_Li_CVPR2025"),
        ],
        report=(".bibcc/INPUT/official_fields.txt", "Differences from the official BibTeX, for each entry"),
        more_reports=[
            (".bibcc/INPUT/official_venues.txt", "The same, for each venue and year, and for the venue library"),
            (".bibcc/INPUT/official_unchecked.txt", "Entries that couldn't be compared, with what to do next"),
        ],
    )
    official.add_argument(
        "--apply",
        type=str,
        default="",
        metavar="FIELDS",
        help=f"Comma-separated fields to add to the entries that lack them, with the official value "
        f"('{APPLY_ALL}': every upstream_only field). Writes INPUT.",
    )
    official.add_argument(
        "--ids",
        type=str,
        default="",
        metavar="KEYS",
        help="Comma-separated citation keys to check (default: every entry).",
    )
    official.add_argument(
        "--local",
        action="append",
        default=[],
        metavar="PATH",
        help="A .bib file or directory of official BibTeX that you got yourself; matching entries "
        "are compared with it instead of a download. Repeatable.",
    )
    official.add_argument(
        "--offline",
        action="store_true",
        help="Download nothing; compare only the entries that match the --local files.",
    )
    official.add_argument(
        "--ignore-fields",
        type=str,
        default="",
        metavar="FIELDS",
        help="Comma-separated fields not to compare.",
    )
    official.add_argument(
        "--delay",
        type=float,
        default=1.0,
        metavar="SECONDS",
        help="Seconds to wait between downloads (default: 1).",
    )
    official.add_argument("--venues", type=str, default="", metavar="FILE", help=VENUES_HELP)

    # --- venues ---
    venues = subparsers.add_parser(
        "venues",
        help="Check the venue library for missing and inconsistent fields.",
        description=f"""\
Report venue library records that are missing fields, and fields that one
edition of a conference defines and another lacks. The check reads the user
library and the nearest {PROJECT_LIBRARY_NAME} separately, or only
--venues FILE (a .bibcc/INPUT/missing_venues.yaml fill-in file works too).""",
        epilog=epilog(
            examples=[
                ("Check the user and project libraries", "bibcc check venues"),
                ("Check a fill-in file before you merge it",
                 "bibcc check venues --venues .bibcc/refs.bib/missing_venues.yaml"),
            ],
            outputs=[(".bibcc/logs/checker.log", "Everything printed to the terminal")],
            env=[ENV_VENUES],
        ),
        formatter_class=HelpFormatter,
    )
    venues.add_argument(
        "path",
        type=str,
        nargs="?",
        default="",
        metavar="PATH",
        help=f"Look for {PROJECT_LIBRARY_NAME} from this file or directory "
        "(default: the current directory).",
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


def _run_venues(args: argparse.Namespace) -> None:
    if args.venues:
        targets = [("library", Path(args.venues))]
    else:
        targets = [("user library", user_library_path())]
        project = find_project_library(args.path or None)
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


# save(report name, header, rows, label, findings to count; default: one per row)
Save = Callable[..., None]


def _check_missing(args: argparse.Namespace, log: Callable[[str], None], save: Save) -> None:
    entry_types = [t.lower() for t in parse_list_arg(args.entry_types) or DEFAULT_ENTRY_TYPES]
    rows = check_missing_fields(args.input, parse_list_arg(args.fields), entry_types, log=log,
                                library=load_library(args.venues or None, start=args.input))
    save(
        "missing_fields.txt",
        "missing fields: entry_id\ttype\tyear\tfields",
        [f"{rid}\t{rtype}\t{ryear}\t{', '.join(rmiss)}" for rid, rtype, ryear, rmiss in rows],
        "Missing fields",
    )


def _check_title(args: argparse.Namespace, log: Callable[[str], None], save: Save) -> None:
    style = get_style(args.style)
    stopwords = set(style.stopwords)
    stopwords.update([s.lower() for s in parse_list_arg(args.extra_stopwords)])
    rows = check_title_case(
        args.input,
        stopwords,
        style.name,
        apply=args.apply,
        interactive=args.interactive,
        log=log,
    )
    save(
        "title_case.txt",
        "title case: entry_id\tcurrent\tsuggested",
        [] if args.apply or args.interactive
        else [f"{eid}\t{current}\t{suggested}" for eid, current, suggested in rows],
        "Title case",
    )


def _check_quote(args: argparse.Namespace, log: Callable[[str], None], save: Save) -> None:
    auto_vocab = auto_vocab_path(args.input)

    def _auto_vocab(keep_case: bool = False) -> List[str]:
        if not auto_vocab.is_file():
            return []
        return load_vocab_file(auto_vocab, log=log, keep_case=keep_case)

    file_terms = (
        load_vocab_file(Path(args.vocab_file), log=log, keep_case=True) if args.vocab_file else set()
    )
    cli_vocab: List[str] = [t.lower() for t in file_terms]
    cli_vocab.extend(parse_list_arg(args.terms))
    if args.apply or args.interactive:
        auto_terms = set(_auto_vocab(keep_case=True))
        own_terms = set(parse_list_arg(args.terms)) | file_terms | auto_terms
        vocab = (set(DEFAULT_VOCAB) if not args.no_default else set()) | set(cli_vocab)
        vocab |= {t.lower() for t in auto_terms}
        apply_protection(
            args.input,
            own_terms,
            vocab_terms=vocab,
            interactive=args.interactive,
            vocab_path=Path(args.vocab_file) if args.vocab_file else auto_vocab,
            log=log,
        )
        log("\n")
    # Read the auto vocabulary after --interactive, which may have added to it.
    extra_vocab = list(cli_vocab)
    extra_vocab.extend(_auto_vocab())
    rows = check_smart_protection(
        args.input,
        extra_vocab,
        use_default_vocab=not args.no_default,
        min_length=args.min_length,
        log=log,
    )
    save(
        "smart_protection.txt",
        "smart protection: entry_id\tword\treason",
        [f"{eid}\t{word}\t{reason}" for eid, word, reason in rows],
        "Smart protection",
    )


def _check_keys(args: argparse.Namespace, log: Callable[[str], None], save: Save) -> None:
    rows = check_citation_keys(args.input, log=log)
    save(
        "citation_keys.txt",
        "citation keys: entry_id\tissue_type\tdetail",
        [f"{eid}\t{issue_type}\t{detail}" for eid, issue_type, detail in rows],
        "Citation key",
    )


def _check_fields(args: argparse.Namespace, log: Callable[[str], None], save: Save) -> None:
    if args.apply:
        trim_fields(args.input, log=log)
    rows = check_field_issues(
        args.input,
        against=args.against,
        extra_fields=parse_list_arg(args.known_fields),
        log=log,
    )
    save(
        "field_issues.txt",
        "field issues: entry_id\tissue_type\tdetail",
        [f"{eid}\t{kind}\t{detail}" for eid, kind, detail in rows],
        "Field issues",
    )


def _check_editions(args: argparse.Namespace, log: Callable[[str], None], save: Save) -> None:
    rows = check_edition_fields(
        args.input,
        against=args.against,
        library=load_library(args.venues or None, start=args.input),
        ignore_fields=parse_list_arg(args.ignore_fields),
        include_fields=parse_list_arg(args.include_fields),
        log=log,
    )
    save(
        "edition_fields.txt",
        "edition fields: entry_id\tvenue\tyear\tfield\tissue_type\tevidence",
        ["\t".join(row) for row in rows],
        "Edition fields",
        sum(row[4] == SAME_YEAR for row in rows),
    )


def _check_official(args: argparse.Namespace, log: Callable[[str], None], save: Save) -> None:
    result = check_official_fields(
        args.input,
        load_library(args.venues or None, start=args.input),
        ids=parse_list_arg(args.ids),
        local=args.local,
        offline=args.offline,
        apply=parse_list_arg(args.apply),
        ignore_fields=parse_list_arg(args.ignore_fields),
        delay=args.delay,
        log=log,
    )
    save("official_fields.txt", FIELDS_HEADER, ["\t".join(r) for r in result.fields],
         "Official fields", result.strict_findings)
    save("official_venues.txt", VENUES_HEADER, ["\t".join(r) for r in result.venues], "Official venues", 0)
    save("official_unchecked.txt", UNCHECKED_HEADER, ["\t".join(r) for r in result.unchecked],
         "Unchecked entries", 0)


_FILE_CHECKS = {
    "missing": _check_missing,
    "title": _check_title,
    "quote": _check_quote,
    "keys": _check_keys,
    "fields": _check_fields,
    "editions": _check_editions,
    "official": _check_official,
}


def run(args: argparse.Namespace) -> None:
    """Run checker with parsed arguments."""
    if args.check == "venues":
        _run_venues(args)
        return

    if not Path(args.input).is_file():
        build_parser().error(f"no such file: {args.input}")
    if args.check == "missing" and not parse_list_arg(args.fields):
        build_parser().error("--fields needs at least one field name")
    findings = 0

    with Logger("checker", input_file=args.input) as logger:
        reports = report_dir(args.input)

        def save(kind: str, header: str, rows: List[str], label: str, count: Optional[int] = None) -> None:
            nonlocal findings
            findings += len(rows) if count is None else count
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
            logger.log(f"📭 {len(empty)} empty entries have no fields, so the check skips them: {', '.join(empty)}")
            logger.log(f"   To fill them, paste their official BibTeX or run "
                       f"'bibcc add --retry --output {args.input}'.\n")

        _FILE_CHECKS[args.check](args, logger.log, save)
    if args.strict and findings:
        sys.exit(1)


if __name__ == "__main__":
    parser = build_parser()
    args = parser.parse_args()
    run(args)
