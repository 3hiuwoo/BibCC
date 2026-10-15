"""
Terms - manage the user and project protected-terms files.

``check quote`` keeps the terms of these files in {braces}: the user terms
file (``$BIBCC_TERMS``, else ``~/.config/bibcc/terms.txt``) for every
project, and a project terms file (``.bibcc-terms.txt``, committed with the
bibliography) for one project.  Shared lists to start from live in
``examples/terms/`` of the BibCC repository.

Usage:
    bibcc terms where bib/refs.bib
    bibcc terms list
    bibcc terms add CIP-Net Transformer-XL --scope project
    bibcc terms examples
    bibcc terms import miaa
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Callable, List, Optional

from bibcc.helptext import ENV_TERMS, HelpFormatter, epilog
from bibcc.logging_utils import Logger
from bibcc.terms import (
    PROJECT_TERMS_NAME,
    TERMS_ENV_VAR,
    USER_TERMS_DISPLAY,
    add_terms,
    load_terms,
    parse_terms,
    read_terms,
    terms_path,
)
from bibcc.utils.venuelib import EXAMPLES_PAGE_URL, example_names, read_source
from bibcc.venues import SCOPES, USER_SCOPE

KIND = "terms"
SUFFIX = ".txt"

TERMS_SCOPE_HELP = (
    f"Terms file to write to: 'user' (default; ${TERMS_ENV_VAR} or {USER_TERMS_DISPLAY}) or "
    f"'project' (the nearest {PROJECT_TERMS_NAME} in the directory of the .bib file or a parent "
    "directory; created next to the project venue library, or in the current directory, if "
    "there's none)."
)


def _target(scope: str, file: Optional[str], start: Optional[str]) -> Path:
    return Path(file).expanduser() if file else terms_path(scope, start=start, create=True)


def where(start: Optional[str], log: Callable[[str], None]) -> int:
    """Show which terms files a command run on *start* reads, and which one it writes."""
    target = Path(start or Path.cwd()).expanduser().resolve()
    log(f"🔤 Terms files for {target}")
    sources = load_terms(target)
    for source in sources:
        state = f"{len(source.terms)} terms" if source.exists else "not created yet"
        log(f"  {source.scope:<8} {source.path} ({state})")
    if len(sources) == 1:
        folder = target if target.is_dir() else target.parent
        log(f"  project  (none: no {PROJECT_TERMS_NAME} in {folder} or its parents)")
    log("\n✏️  terms add, terms import, and check quote --interactive write to the user file. To write "
        "to the project file instead, pass --scope project.")
    return 0


def list_terms(start: Optional[str], log: Callable[[str], None]) -> int:
    """Print every term with the scope of its file, tab-separated."""
    for source in load_terms(start):
        for term in source.terms:
            log(f"{term}\t{source.scope}")
    return 0


def add(terms: List[str], scope: str, file: Optional[str], log: Callable[[str], None]) -> int:
    path = _target(scope, file, None)
    added = add_terms(path, terms)
    if added:
        log(f"✅ Added {len(added)} terms to {path}: {', '.join(added)}")
    else:
        log(f"ℹ️  {path} already has every term.")
    return 0


def import_terms(source: str, scope: str, file: Optional[str], dry_run: bool,
                 log: Callable[[str], None]) -> int:
    """Add the terms of *source* that the target file lacks; returns the exit status."""
    try:
        text, origin = read_source(source, kind=KIND, suffix=SUFFIX)
    except (OSError, ValueError) as e:
        log(f"❌ {e}")
        return 1
    incoming = parse_terms(text)
    if not incoming:
        log(f"❌ {origin} has no terms.")
        return 1
    path = _target(scope, file, None)
    have = {t.casefold() for t in read_terms(path)}
    new = [t for t in incoming if t.casefold() not in have]
    log(f"📥 Importing {len(incoming)} terms from {origin}")
    log(f"   into {path}")
    log(f"\n➕ {len(new)} new, ⏭️  {len(incoming) - len(new)} already there")
    if dry_run:
        log("\n🧪 Dry run: nothing written.")
        return 0
    if new:
        add_terms(path, new)
        log(f"\n✅ Saved {path}")
    else:
        log("\nℹ️  Nothing new to import.")
    return 0


def examples(log: Callable[[str], None]) -> int:
    try:
        paths, names, origin = example_names(KIND, SUFFIX)
    except ValueError as e:
        log(f"❌ {e}")
        return 1
    rows = [(p.stem, f"{len(read_terms(p))} terms") for p in paths] + [(n, "") for n in names]
    log(f"📚 Example terms files ({origin}):")
    if not rows:
        log("  (none)")
    width = max((len(name) for name, _ in rows), default=0)
    for name, details in rows:
        log(f"  {name:<{width}}  {details}".rstrip())
    log("\nTo import one into your user terms file, run 'bibcc terms import NAME'.")
    log("To import it into the project terms file instead, add --scope project.")
    log(f"What each one covers: {EXAMPLES_PAGE_URL.format(kind=KIND)}")
    return 0


_DESCRIPTION = f"""\
Manage the protected terms that 'check quote' keeps in {{braces}}, such as
acronyms (CLIP), mixed-case names (LoRA), and method names (CIP-Net). Terms
live in two scopes, like the venue library:

  user     ${TERMS_ENV_VAR}, or else $XDG_CONFIG_HOME/bibcc/terms.txt
           ({USER_TERMS_DISPLAY}). Terms for all your projects.
  project  {PROJECT_TERMS_NAME}, the nearest one in the directory of the
           .bib file or a parent directory. Terms for one project; commit it with
           the bibliography.

'check quote' reads both files on top of its built-in vocabulary of names,
and with --apply it braces their terms. A terms file has one term per line,
with the case that titles use; blank lines and # comments are ignored.

Shared lists (for example, the MIAA lab's terms, 'miaa') live in
examples/terms/ of the BibCC repository. 'import' adds the terms of one that
your file lacks."""


def _scope_arguments(parser: argparse.ArgumentParser) -> None:
    target = parser.add_mutually_exclusive_group()
    target.add_argument("--scope", choices=SCOPES, default=None, help=TERMS_SCOPE_HELP)
    target.add_argument("--file", default="", metavar="FILE",
                        help="Write to this terms file instead of a scope.")


def build_parser() -> argparse.ArgumentParser:
    """Build parser with the terms subcommands."""
    parser = argparse.ArgumentParser(
        description=_DESCRIPTION,
        epilog=epilog(
            examples=[
                ("Show which terms files apply to this file", "bibcc terms where bib/refs.bib"),
                ("Keep a method name whole in every project", "bibcc terms add CIP-Net"),
                ("Share terms with your coauthors", "bibcc terms add Transformer-XL --scope project"),
                ("Start your user terms from the MIAA lab's list", "bibcc terms import miaa"),
            ],
            env=[ENV_TERMS],
        ),
        formatter_class=HelpFormatter,
    )
    subparsers = parser.add_subparsers(dest="command", required=True, metavar="SUBCOMMAND")

    p_where = subparsers.add_parser(
        "where",
        help="Show the user and project terms files that apply, and which one commands write to.",
        description=f"Show the user terms file and the project terms file that applies to PATH\n"
        f"(the nearest {PROJECT_TERMS_NAME} in its directory or a parent directory), with\n"
        "the number of terms in each.",
        epilog=epilog(examples=[("Show the terms files for the current directory", "bibcc terms where")],
                      env=[ENV_TERMS]),
        formatter_class=HelpFormatter,
    )
    p_where.add_argument("path", nargs="?", default=None, metavar="PATH",
                         help="A .bib file or directory (default: the current directory).")

    p_list = subparsers.add_parser(
        "list",
        help="Print every term, with the scope of its file.",
        description="Print every term of the user and project terms files that apply to PATH, one\n"
        "per line, followed by a tab and the scope (user or project).",
        epilog=epilog(examples=[("Print the terms that apply here", "bibcc terms list")], env=[ENV_TERMS]),
        formatter_class=HelpFormatter,
    )
    p_list.add_argument("path", nargs="?", default=None, metavar="PATH",
                        help="A .bib file or directory (default: the current directory).")

    p_add = subparsers.add_parser(
        "add",
        help="Add terms to the user or project terms file.",
        description="Add each TERM that the file lacks (ignoring case) to the user terms file, the\n"
        "project terms file (--scope project), or --file FILE. To keep a hyphenated\n"
        "method name such as CIP-Net in one brace group, add the whole compound.",
        epilog=epilog(
            examples=[
                ("Keep two method names whole", "bibcc terms add CIP-Net Transformer-XL"),
                ("Add a term for this project only", "bibcc terms add SD-LoRA --scope project"),
            ],
            outputs=[(f"{USER_TERMS_DISPLAY}, {PROJECT_TERMS_NAME}, or --file FILE", "The terms file")],
            env=[ENV_TERMS],
        ),
        formatter_class=HelpFormatter,
    )
    p_add.add_argument("terms", nargs="+", metavar="TERM", help="A term, with the case that titles use.")
    _scope_arguments(p_add)

    p_import = subparsers.add_parser(
        "import",
        help="Add the terms of a shared list (file, URL, or example name) to yours.",
        description="Add the terms of SOURCE that the user terms file (default), the project terms\n"
        "file (--scope project), or --file FILE lacks.\n\n"
        "SOURCE is a terms file, an http(s) URL, or the name of a list in\n"
        "examples/terms/ of the BibCC repository (see 'bibcc terms examples'). The\n"
        "command reads an example list from your checkout when BibCC runs from one, and\n"
        "otherwise downloads it.",
        epilog=epilog(
            examples=[
                ("Start your user terms from the MIAA lab's list", "bibcc terms import miaa"),
                ("Preview what the list would add to the project file",
                 "bibcc terms import miaa --scope project --dry-run"),
            ],
            outputs=[(f"{USER_TERMS_DISPLAY}, {PROJECT_TERMS_NAME}, or --file FILE", "The terms file")],
            exit_status="0 on success (also when nothing is new), 1 if BibCC can't read SOURCE,\n"
            "2 on usage errors.",
            env=[ENV_TERMS],
        ),
        formatter_class=HelpFormatter,
    )
    p_import.add_argument("source", metavar="SOURCE",
                          help="Terms file, http(s) URL, or example list name (for example, miaa).")
    _scope_arguments(p_import)
    p_import.add_argument("--dry-run", action="store_true",
                          help="Report what would change without writing anything.")

    subparsers.add_parser(
        "examples",
        help="List the shared example terms files.",
        description="List the terms files in examples/terms/ of the BibCC repository (your checkout\n"
        "when BibCC runs from one, or else GitHub), ready for 'bibcc terms import'.",
        epilog=epilog(examples=[("List the example terms files", "bibcc terms examples")]),
        formatter_class=HelpFormatter,
    )
    return parser


def main() -> None:
    """CLI entry point."""
    args = build_parser().parse_args()
    # These commands only print summaries, so no log file (and no .bibcc/ folder) is written.
    with Logger("terms", enabled=False) as logger:
        if args.command == "where":
            status = where(args.path, logger.log)
        elif args.command == "list":
            status = list_terms(args.path, logger.log)
        elif args.command == "add":
            status = add(args.terms, args.scope or USER_SCOPE, args.file or None, logger.log)
        elif args.command == "import":
            status = import_terms(args.source, args.scope or USER_SCOPE, args.file or None, args.dry_run,
                                  logger.log)
        else:
            status = examples(logger.log)
    sys.exit(status)


if __name__ == "__main__":
    main()
