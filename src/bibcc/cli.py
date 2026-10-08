"""
BibCC — BibTeX Check & Complete CLI.

Unified command-line interface for the BibCC toolkit.  Every tool is exposed
as a subcommand so that the entire workflow can be driven from one entry point.

Subcommands:
    check      Quality checks (missing fields, title case, term protection, …)
    complete   Auto-fill missing BibTeX fields from templates
    add        Fetch papers by DOI, arXiv ID, or title into a staging .bib
    upgrade    Replace arXiv preprints with their published versions
    librarian  Align a PDF library with a .bib file (missing / extra / rename)
    scholar    Citation counts and title verification via external APIs
    compose    Merge per-folder .bib files into a single bibliography

Usage:
    bibcc check input.bib --fields month --title-case
    bibcc complete input.bib --output out.bib
    bibcc add 2501.13198 10.1109/TPAMI.2024.3429383 --against bibs/
    bibcc upgrade input.bib --in-place
    bibcc librarian missing input.bib papers.txt
    bibcc scholar cite input.bib
    bibcc scholar titles input.bib
    bibcc compose compose ./bibs combined.bib
"""

from __future__ import annotations

import importlib
import sys

from bibcc import __version__

TOOLS = {
    "check": "Quality checks: missing fields, title case, term protection, keys",
    "complete": "Auto-fill missing BibTeX fields from templates",
    "add": "Fetch papers by DOI, arXiv ID, or title into a staging .bib",
    "upgrade": "Replace arXiv preprints with their published versions",
    "librarian": "Align PDF library with .bib: missing / extra / rename",
    "scholar": "Citation counts and title verification via external APIs",
    "compose": "Merge per-folder .bib files into a single bibliography",
}

# Tools exposing build_parser() + run(args) vs. a self-parsing main().
_RUN_TOOLS = {
    "check": "bibcc.checker",
    "complete": "bibcc.completer",
    "add": "bibcc.adder",
    "upgrade": "bibcc.upgrader",
}
_MAIN_TOOLS = {
    "librarian": "bibcc.utils.librarian",
    "scholar": "bibcc.utils.scholar",
    "compose": "bibcc.utils.composer",
}


def _print_usage() -> None:
    """Print top-level usage information."""
    print("usage: bibcc <tool> [args ...]\n")
    print(f"BibCC {__version__} — BibTeX Check & Complete toolkit.\n")
    print("Available tools:")
    for name, desc in TOOLS.items():
        print(f"  {name:<12} {desc}")
    print("\nRun 'bibcc <tool> -h' for tool-specific help.")


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
