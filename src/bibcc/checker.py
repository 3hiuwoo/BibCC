"""
BibTeX Quality Checker — CLI orchestrator.

This module provides the command-line interface that dispatches to individual
sub-checkers in the ``checkers`` package.  Each check is a subcommand:

- ``missing``: Missing field detection (for example, month and publisher)
- ``title``: Title case validation with APA-style rules
- ``quote``: Smart protection suggestions for technical terms and acronyms
- ``keys``: Citation key legibility
- ``fields``: Field names, field values, and duplicate papers
- ``editions``: Fields of the venue's schema that an entry lacks, and schemas from the entries
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

from bibcc import cache
from bibcc.bibedit import BibEditError, read_bib, scan
from bibcc.checkers import (
    APPLY_ALL,
    DEFAULT_ENTRY_TYPES,
    DEFAULT_IGNORED_FIELDS,
    DEFAULT_JOURNAL_FIELDS,
    DEFAULT_PROCEEDINGS_FIELDS,
    DEFAULT_VOCAB,
    EDITION_FIELDS_HEADER,
    EDITION_SCHEMAS_HEADER,
    FIELDS_HEADER,
    MIN_TERM_LENGTH,
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
from bibcc.checkers.official_fields import OfficialCheck, apply_books
from bibcc.helptext import ENV_CACHE, ENV_VENUES, SCOPE_HELP, VENUES_HELP, HelpFormatter, epilog
from bibcc.logging_utils import Logger, remove_report, report_dir, write_report
from bibcc.missing_venues import write_missing_venues
from bibcc.schemas import Proposal, apply_proposals, missing_records
from bibcc.terms import load_terms, terms_path
from bibcc.titlecases import STYLES
from bibcc.utils.termlib import TERMS_SCOPE_HELP
from bibcc.venues import (
    PROJECT_LIBRARY_NAME,
    PROJECT_SCOPE,
    SCOPES,
    USER_LIBRARY_DISPLAY,
    USER_SCOPE,
    LibraryNotFound,
    VenueLibrary,
    find_project_library,
    load_library,
    open_library,
    user_library_path,
)


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
--apply, which adds only the fields you name from the official BibTeX. The
official and editions checks write the venue schemas they find into the venue
library only with --learn. Only the official check reaches the network. Empty entries
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
    env: Optional[List[tuple]] = None,
) -> argparse.ArgumentParser:
    """Add the subcommand for a check of a .bib file, with INPUT and --strict."""
    parser = subparsers.add_parser(
        name,
        help=summary,
        description=description,
        epilog=epilog(examples=examples, outputs=[report, *(more_reports or []), LOG_OUTPUT],
                      env=env or (), exit_status=EXIT_STATUS),
        formatter_class=HelpFormatter,
    )
    parser.add_argument("input", type=str, metavar="INPUT", help="The .bib file to check.")
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit with status 1 if the check finds something or the file has empty entries.",
    )
    return parser


def _learn_arguments(parser: argparse.ArgumentParser, what: str) -> None:
    parser.add_argument(
        "--learn",
        action="store_true",
        help=f"Write {what} into the venue library that --scope selects, or into --venues FILE. "
        "A schema whose journal or edition record is missing goes into "
        ".bibcc/INPUT/missing_venues.yaml.",
    )
    parser.add_argument("--scope", choices=SCOPES, default=None, help=SCOPE_HELP)


def _learn_target(args: argparse.Namespace, log: Callable[[str], None]) -> Optional[VenueLibrary]:
    """The library file that --learn writes to, or None (without --learn, or with no such library)."""
    if not args.learn:
        return None
    try:
        return open_library(args.scope or USER_SCOPE, venues=args.venues or None, start=args.input)
    except LibraryNotFound as e:
        log(f"❌ {e}")
        return None


def _save_learned(target: Optional[VenueLibrary], changed: int, log: Callable[[str], None],
                  what: str = "venue schemas") -> None:
    if target is None:
        return
    if changed:
        target.save()
        log(f"✅ Wrote {changed} {what} into {target.path}.")
    else:
        log(f"ℹ️  No new {what} to write into {target.path}.")


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
                ("Find the fields of their venue's schema that entries lack",
                 "bibcc check editions refs.bib"),
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
keep another compound whole, such as the method name {CIP-Net}, add it to
your terms ('bibcc terms add CIP-Net'), or list it with --terms or
--vocab-file.

The check always reads the user terms file ($BIBCC_TERMS, or else
~/.config/bibcc/terms.txt), the nearest .bibcc-terms.txt of the project, and
.bibcc/INPUT/vocab.txt, and --apply braces their terms. For details, see
'bibcc terms -h'.""",
        examples=[
            ("Report words to brace", "bibcc check quote refs.bib"),
            ("Report words to brace, with extra terms",
             "bibcc check quote refs.bib --terms Transformer,Adam"),
            ("Brace your own terms and split over-braced compounds, then report the rest",
             "bibcc check quote refs.bib --apply --terms LoRA,CLIP,Transformer-XL"),
            ("Review each compound split, and keep the method names whole",
             "bibcc check quote refs.bib --interactive"),
            ("Review the splits, and share the method names you keep with your coauthors",
             "bibcc check quote refs.bib --interactive --scope project"),
        ],
        report=(".bibcc/INPUT/smart_protection.txt", "Words that need {braces}, and over-braced compounds"),
    )
    quote_mode = quote.add_mutually_exclusive_group()
    quote_mode.add_argument(
        "--apply",
        action="store_true",
        help="Wrap your terms (the terms files, --terms, and --vocab-file) in braces wherever they "
        "appear in a title with the same case, split over-braced compounds, and then report what "
        "else needs braces. The built-in vocabulary and the other suggestions are never applied.",
    )
    quote_mode.add_argument(
        "--interactive",
        action="store_true",
        help="Review each over-braced compound one at a time: split it, skip it, edit the "
        "suggestion, or keep it whole and add it to the terms file that --scope selects, so that "
        "later runs leave it whole. Your terms are still braced, and the accepted changes are "
        "written to the input file.",
    )
    quote.add_argument("--scope", choices=SCOPES, default=None, help=TERMS_SCOPE_HELP)
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
        "are ignored. The terms files and .bibcc/INPUT/vocab.txt are always read, with or "
        "without this option.",
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
        summary="Report the fields of their venue's schema that entries lack.",
        description="""\
Check each entry of INPUT against its venue's schema: the per-paper fields
(such as pages, doi, and url) that the official BibTeX of every paper of the
venue has. The venue library holds the schemas, for a journal, for a family
of conference editions, or for one edition whose export differs. The check
reports two kinds of findings:

  missing          The entry lacks a field of its venue's schema. The
                   evidence names the schema and where it was learned from.
  default_missing  The entry's venue has no schema, and the entry lacks a
                   field of its publisher's default schema: the fields that
                   most of the library's schemas of the same publisher and
                   kind (journal or proceedings) share. The publisher comes
                   from the venue record, the entry, the venue name, or the
                   DOI prefix. A default is a guess: it never replaces a
                   venue's own schema, and --learn never writes it.

A journal article not yet in an issue (no volume) isn't expected to have a
volume, number, or pages.

For a venue without a schema, the check compares the entries of the venue
with one another, in INPUT and in the --against files, and proposes the
fields that most of them share (schema_lacks in edition_schemas.txt). It
reports no entry from that comparison alone. To write the proposals into the
venue library and check the entries against them, pass --learn. A proposal
for a journal or an edition that the library has no record of goes into
.bibcc/INPUT/missing_venues.yaml, with the record. A schema learned from
official BibTeX ('bibcc check official INPUT --learn') is more reliable,
because entries can share a lost field; the comparison is for venues whose
BibTeX BibCC can't download.

""" + textwrap.fill(
            f"The check ignores these fields: {', '.join(DEFAULT_IGNORED_FIELDS)}. To ignore more, "
            "pass --ignore-fields; to compare one of them anyway, pass --include-fields. It also "
            "leaves out entries with an interim (CVF or OpenReview) booktitle, entries built from "
            "metadata, and empty entries. With --strict, only missing findings count.",
            width=78,
        ),
        examples=[
            ("Check the entries against their venues' schemas", "bibcc check editions refs.bib"),
            ("Propose schemas from the entries in refs.bib and bib/",
             "bibcc check editions refs.bib --against bib/"),
            ("Write the proposed schemas into the project library, and check against them",
             "bibcc check editions refs.bib --against bib/ --learn --scope project"),
            ("Also compare the urldate field, and ignore abstract",
             "bibcc check editions refs.bib --include-fields urldate --ignore-fields abstract"),
        ],
        report=(".bibcc/INPUT/edition_fields.txt", "Fields of the venue's schema that entries lack"),
        more_reports=[
            (".bibcc/INPUT/edition_schemas.txt", "Schemas that the entries of each venue propose"),
            (".bibcc/INPUT/missing_venues.yaml",
             "With --learn, fill-in records for the schemas whose record the library lacks"),
        ],
        env=[ENV_VENUES],
    )
    editions.add_argument(
        "--against",
        action="append",
        default=[],
        metavar="PATH",
        help="Also compare with the entries in this .bib file or directory (searched "
        "recursively) when proposing schemas. Repeatable.",
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
    _learn_arguments(editions, "the proposed schemas (entry_fields)")
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
                 whitespace, accents, month spellings, and the form of a
                 name, First Last or Last, First, don't count).
  local_only     The entry has a field that the official BibTeX lacks, other
                 than citation and the fields that the venue library supplies.
  type           The entry types differ.

The venue summary says, for each venue and year, how many checked entries
the official BibTeX gives a field, and how many of them lack it
(entries_lack), and which fields every checked entry has and no official
BibTeX has (export_lacks). The summary also compares the venue library
records with the official values, and each venue's schema (the per-paper
fields that its official BibTeX has) with the downloaded BibTeX: schema_lacks
when the library has no schema for the venue, schema_differs when the schema
differs. To write those schemas into the venue library, pass --learn; 'bibcc
check editions' then checks entries against them. A schema whose journal or
edition record the library lacks goes into .bibcc/INPUT/missing_venues.yaml,
with the record's fields from the official BibTeX, so that one 'bibcc
complete INPUT --update-venues' adds both.

Proceedings published as several books (the LNCS volumes of ECCV or MICCAI)
export their chapters without the volume and part. When the entries of one
book, named by the ISBN in their chapter DOIs, agree on a volume or part
that the record's books table lacks, the summary says so (books_lack), and
--learn writes it there. 'bibcc complete' then fills it in by DOI, and this
check no longer reports it as local_only.

BibCC keeps each downloaded BibTeX for 30 days, so a second run reads it from
the cache. To download everything again, pass --refresh.

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
            ("Learn the venue schemas from the official BibTeX", "bibcc check official refs.bib --learn"),
        ],
        report=(".bibcc/INPUT/official_fields.txt", "Differences from the official BibTeX, for each entry"),
        more_reports=[
            (".bibcc/INPUT/official_venues.txt", "The same, for each venue and year, and for the venue library"),
            (".bibcc/INPUT/official_unchecked.txt", "Entries that couldn't be compared, with what to do next"),
            (".bibcc/INPUT/missing_venues.yaml",
             "With --learn, fill-in records for the schemas whose record the library lacks"),
        ],
        env=[ENV_VENUES, ENV_CACHE],
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
    official.add_argument(
        "--refresh",
        action="store_true",
        help="Download every official BibTeX again instead of reading the cache, and update the cache.",
    )
    _learn_arguments(official, "the schemas of the official BibTeX (entry_fields) and the book fields (books)")
    official.add_argument("--venues", type=str, default="", metavar="FILE", help=VENUES_HELP)

    # --- venues ---
    venues = subparsers.add_parser(
        "venues",
        help="Check the venue library for missing and inconsistent fields.",
        description=f"""\
Report venue library records that are missing fields, and fields that one
edition of a conference defines and another lacks. The check reads the user
library and the nearest {PROJECT_LIBRARY_NAME} separately, only the one that
--scope names, or only --venues FILE (a .bibcc/INPUT/missing_venues.yaml
fill-in file works too).

It also lists the values that every published edition of a conference
shares, such as the publisher and ISSN of CVPR. A family record holds them
once for every edition. To move them there, pass --apply: the check creates
the family records that are missing (with the provider table's acronym when
the table knows the conference), adds the shared values, and removes them
from the editions, so no edition's fields change. An edition whose value
differs only in braces or case keeps it.""",
        epilog=epilog(
            examples=[
                ("Check the user and project libraries", "bibcc check venues"),
                ("Check a fill-in file before you merge it",
                 "bibcc check venues --venues .bibcc/refs.bib/missing_venues.yaml"),
                ("Move the values every edition shares into family records, in the project library",
                 "bibcc check venues --scope project --apply"),
            ],
            outputs=[
                (f"{USER_LIBRARY_DISPLAY}, {PROJECT_LIBRARY_NAME}, or --venues FILE",
                 "The libraries that --apply rewrites"),
                (".bibcc/logs/checker.log", "Everything printed to the terminal"),
            ],
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
    venues.add_argument(
        "--scope",
        choices=SCOPES,
        default=None,
        help="Check only this library: 'user' or 'project' (default: both).",
    )
    venues.add_argument(
        "--apply",
        action="store_true",
        help="Move the values that every edition of a conference shares into its family record, "
        "creating the record when it's missing, and save each library the check reads.",
    )

    return parser


def _run_venues(args: argparse.Namespace) -> None:
    if args.venues and args.scope:
        build_parser().error("--venues already names the library; drop --scope")
    if args.venues:
        targets = [("library", Path(args.venues))]
    else:
        targets = []
        if args.scope in (None, USER_SCOPE):
            targets.append(("user library", user_library_path()))
        project = find_project_library(args.path or None)
        if project is not None and args.scope in (None, PROJECT_SCOPE):
            targets.append(("project library", project))
        elif args.scope == PROJECT_SCOPE:
            build_parser().error(f"no {PROJECT_LIBRARY_NAME} in {Path(args.path or '.').resolve()} "
                                 "or its parent directories")
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
                apply=args.apply,
            )


def _learn_official(result: OfficialCheck, target: Optional[VenueLibrary], log: Callable[[str], None]) -> None:
    if not result.proposals and not result.books:
        return
    if target is None:
        log("   To write these venue schemas (entry_fields) and book fields into the venue library, "
            "run with --learn.")
        return
    log(f"\n🧠 Writing the venue schemas and book fields into {target.path}...")
    schemas = apply_proposals(target, result.proposals, log)
    books = apply_books(target, result.books, log)
    if schemas or books:
        target.save()
        log(f"✅ Wrote {schemas} venue schemas and {books} book fields into {target.path}.")
    else:
        log(f"ℹ️  No new venue schemas and book fields to write into {target.path}.")


def _write_schema_records(args: argparse.Namespace, proposals: List[Proposal], label: str,
                          target: Optional[VenueLibrary], library: VenueLibrary,
                          log: Callable[[str], None]) -> None:
    """With --learn, put the schemas whose journal or edition record is missing into missing_venues.yaml."""
    records = missing_records(proposals, label)
    if target is None or not records:
        return
    if args.venues:
        where = f" --venues {args.venues}"
    elif args.scope and args.scope != USER_SCOPE:
        where = f" --scope {args.scope}"
    else:
        where = ""
    rerun = f"bibcc complete {args.input} --in-place --update-venues{where}"
    path = report_dir(args.input) / "missing_venues.yaml"
    counts = write_missing_venues(path, records, library, rerun)
    log(f"\n📝 {counts['new'] + counts['schemas']} venue records with a schema but no library record "
        f"are in {path}.")
    log(f"   To add the records and their schemas, fill in the fields, and then run: {rerun}")


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
    for source in load_terms(args.input):
        if source.terms:
            log(f"🔤 {len(source.terms)} terms from the {source.scope} terms file {source.path}")
        file_terms |= set(source.terms)
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
            vocab_path=terms_path(args.scope or USER_SCOPE, start=args.input, create=True),
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
    target = _learn_target(args, log)
    result = check_edition_fields(
        args.input,
        load_library(args.venues or None, start=args.input),
        against=args.against,
        ignore_fields=parse_list_arg(args.ignore_fields),
        include_fields=parse_list_arg(args.include_fields),
        learn=target,
        log=log,
    )
    _save_learned(target, result.learned, log)
    _write_schema_records(args, result.proposals, "from bib", target,
                          load_library(args.venues or None, start=args.input), log)
    save("edition_fields.txt", EDITION_FIELDS_HEADER, ["\t".join(row) for row in result.fields], "Edition fields",
         result.missing)
    save("edition_schemas.txt", EDITION_SCHEMAS_HEADER, ["\t".join(row) for row in result.schemas],
         "Edition schemas", 0)


def _check_official(args: argparse.Namespace, log: Callable[[str], None], save: Save) -> None:
    target = _learn_target(args, log)
    if args.refresh:
        cache.refresh()
    library = load_library(args.venues or None, start=args.input)
    result = check_official_fields(
        args.input,
        library,
        ids=parse_list_arg(args.ids),
        local=args.local,
        offline=args.offline,
        apply=parse_list_arg(args.apply),
        ignore_fields=parse_list_arg(args.ignore_fields),
        delay=args.delay,
        log=log,
    )
    _learn_official(result, target, log)
    _write_schema_records(args, result.proposals, "from official BibTeX", target, library, log)
    save("official_fields.txt", FIELDS_HEADER, ["\t".join(r) for r in result.fields],
         "Official fields", result.strict_findings)
    save("official_venues.txt", VENUES_HEADER, ["\t".join(r) for r in result.venues], "Official venues", 0)
    save("official_unchecked.txt", UNCHECKED_HEADER, ["\t".join(r) for r in result.unchecked],
         "Unchecked entries", 0)


CHECK_NAMES = ("missing", "title", "quote", "keys", "fields", "editions", "official", "venues")
"""Every ``bibcc check`` subcommand, in help order."""

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
    if getattr(args, "scope", None) and args.check == "quote" and not args.interactive:
        build_parser().error("--scope only applies with --interactive")
    if getattr(args, "scope", None) and args.check != "quote" and not args.learn:
        build_parser().error("--scope only applies with --learn")
    if getattr(args, "scope", None) and getattr(args, "venues", None):
        build_parser().error("--venues already names the library to write; drop --scope")
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
