"""
BibCC — BibTeX Check & Complete CLI.

Unified command-line interface for the BibCC toolkit.  Every tool is exposed
as a subcommand so that the entire workflow can be driven from one entry point.

Subcommands:
    check      Quality checks (missing fields, title case, term protection, …)
    complete   Auto-fill missing BibTeX fields from the venue library
    add        Download official BibTeX by DOI, arXiv ID, URL, or title
    upgrade    Replace preprints with the official BibTeX of their published versions
    format     Reformat .bib files consistently (aligned fields, braces, month macros)
    librarian  Align a PDF library with a .bib file (missing / extra / rename)
    scholar    Citation counts and title verification via external APIs
    compose    Merge per-folder .bib files into a single bibliography
    venues     Manage the user and project venue libraries

Usage:
    bibcc check input.bib --fields month --title-case
    bibcc complete input.bib --output out.bib
    bibcc add 2501.13198 10.1109/TPAMI.2024.3429383 --against bibs/
    bibcc upgrade input.bib --in-place
    bibcc upgrade --report-only bibs/
    bibcc format bibs/ --check
    bibcc librarian missing input.bib papers.txt
    bibcc scholar cite input.bib
    bibcc scholar titles input.bib
    bibcc compose compose ./bibs combined.bib
    bibcc venues import miaa
"""

from __future__ import annotations

import importlib
import sys

from bibcc import __version__
from bibcc.helptext import ENV_S2, ENV_VENUES, epilog

TOOLS = {
    "check": "Quality checks: missing fields, title case, braces, keys, field typos",
    "complete": "Fill missing venue fields from the venue library and report conflicts",
    "add": "Download official BibTeX by DOI, arXiv ID, URL, or title into a staging .bib",
    "upgrade": "Replace preprints with the official BibTeX of their published versions",
    "format": "Reformat .bib files consistently (aligned fields, braces, month macros)",
    "librarian": "Align a PDF library with a .bib file: missing / extra / rename",
    "scholar": "Google Scholar citation counts and title verification",
    "compose": "Merge the .bib files of a folder tree into one bibliography",
    "venues": "Manage the user and project venue libraries: where, init, import, examples",
}

# Tools exposing build_parser() + run(args) vs. a self-parsing main().
_RUN_TOOLS = {
    "check": "bibcc.checker",
    "complete": "bibcc.completer",
    "add": "bibcc.adder",
    "upgrade": "bibcc.upgrader",
    "format": "bibcc.formatter",
}
_MAIN_TOOLS = {
    "librarian": "bibcc.utils.librarian",
    "scholar": "bibcc.utils.scholar",
    "compose": "bibcc.utils.composer",
    "venues": "bibcc.utils.venuelib",
}


_OVERVIEW = """\
Commands that change a .bib file (complete, upgrade, format) only preview the
changes unless --output or --in-place is given, and write the preview as a
diff. Apart from format, which rewrites the layout, edits touch only the
fields they change. Every result is parsed again and verified before anything
is written. Reports go to a .bibcc/ folder next to the input file, and logs
to .bibcc/logs/.

add and upgrade download official BibTeX from the publisher or proceedings
site (IEEE Xplore, Springer, PMLR, NeurIPS, ICLR, ACL, IJCAI, OpenReview,
arXiv) after finding the paper through CrossRef, arXiv, OpenReview, and
Semantic Scholar. scholar titles and complete --online also go online; the
other commands work offline.

Venue fields come from your own venue library: the user library
(~/.config/bibcc/venues.yaml) merged with the project's .bibcc-venues.yaml.
BibCC ships none; start from scratch or from a shared one ('bibcc venues -h')."""


def usage_text() -> str:
    """Top-level help text."""
    commands = "\n".join(f"  {name:<12} {desc}" for name, desc in TOOLS.items())
    more = epilog(
        examples=[
            ("fetch new papers into added.bib, skipping those already in bib/",
             "bibcc add 2501.13198 10.1109/TPAMI.2024.3429383 --against bib/"),
            ("fill venue fields (publisher, ISSN, month, ...) from the venue library",
             "bibcc complete bib/topic.bib --in-place"),
            ("check titles, braces, keys, field typos, and duplicates",
             "bibcc check bib/topic.bib --title-case --quote --check-keys --check-fields"),
            ("replace preprints with their published versions", "bibcc upgrade bib/topic.bib --in-place"),
            ("only report which preprints have been published", "bibcc upgrade --report-only bib/"),
            ("give every file the same layout", "bibcc format bib/ --in-place"),
            ("merge the folder into one file for LaTeX", "bibcc compose compose bib/ references.bib"),
            ("start your venue library from a shared one", "bibcc venues import miaa"),
        ],
        env=[ENV_VENUES, ENV_S2],
    )
    return (
        "usage: bibcc [-h] [-V] <command> [args ...]\n\n"
        f"BibCC {__version__} — BibTeX Check & Complete: quality checks, field completion,\n"
        "fetching and upgrading papers, formatting, and PDF library alignment.\n\n"
        f"commands:\n{commands}\n\n"
        "options:\n"
        "  -h, --help     show this help message and exit\n"
        "  -V, --version  show the version and exit\n\n"
        f"{_OVERVIEW}\n\n"
        "Run 'bibcc <command> -h' for the options, output files, and examples of a command.\n\n"
        f"{more}"
    )


def _print_usage() -> None:
    """Print top-level usage information."""
    print(usage_text())


def main(argv: list[str] | None = None) -> None:
    """Parse the first positional arg as a tool name and delegate."""
    argv = list(sys.argv[1:] if argv is None else argv)

    if not argv or argv[0] in ("-h", "--help"):
        _print_usage()
        sys.exit(0)
    if argv[0] in ("-V", "--version"):
        print(f"bibcc {__version__}")
        sys.exit(0)

    tool = argv[0]
    if tool not in TOOLS:
        print(f"bibcc: unknown tool '{tool}'")
        _print_usage()
        sys.exit(1)

    # Delegated parsers read sys.argv, so present them their own argv.
    sys.argv = [f"bibcc {tool}"] + argv[1:]

    if tool in _RUN_TOOLS:
        module = importlib.import_module(_RUN_TOOLS[tool])
        args = module.build_parser().parse_args()
        module.run(args)
    else:
        importlib.import_module(_MAIN_TOOLS[tool]).main()


if __name__ == "__main__":
    main()
