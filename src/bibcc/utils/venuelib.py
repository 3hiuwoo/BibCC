"""
Venues - manage the user and project venue libraries.

BibCC ships no venue library.  Each user builds their own: the user library
(``$BIBCC_VENUES``, else ``~/.config/bibcc/venues.yaml``) holds venues for
every project, and a project library (``.bibcc-venues.yaml``, committed with
the bibliography) holds venues for one project and wins where both define a
field.  Shared libraries to start from live in ``examples/venues/`` of the
BibCC repository.

Usage:
    bibcc venues where bib/refs.bib
    bibcc venues init --scope project
    bibcc venues examples
    bibcc venues import miaa
    bibcc venues import ./lab-venues.yaml --scope project
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path
from typing import Callable, List, Optional, Tuple

import yaml

import bibcc
from bibcc import sources
from bibcc.helptext import ENV_VENUES, REPO, SCOPE_HELP, HelpFormatter, epilog
from bibcc.logging_utils import Logger
from bibcc.venues import (
    LIBRARY_ENV_VAR,
    PROJECT_LIBRARY_NAME,
    PROJECT_SCOPE,
    SCOPES,
    USER_LIBRARY_DISPLAY,
    USER_SCOPE,
    VenueLibrary,
    find_project_library,
    load_library,
    merge_records,
    open_library,
    user_library_path,
)

EXAMPLES_BRANCH = "main"
EXAMPLE_RAW_URL = f"https://raw.githubusercontent.com/{REPO}/{EXAMPLES_BRANCH}/examples/venues/{{name}}.yaml"
EXAMPLES_API_URL = f"https://api.github.com/repos/{REPO}/contents/examples/venues?ref={EXAMPLES_BRANCH}"
EXAMPLES_PAGE_URL = f"https://github.com/{REPO}/tree/{EXAMPLES_BRANCH}/examples/venues"

_EXAMPLE_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*")


def local_examples_dir() -> Optional[Path]:
    """``examples/venues/`` of the checkout BibCC runs from, if it runs from one (editable install)."""
    folder = Path(bibcc.__file__).resolve().parents[2] / "examples" / "venues"
    return folder if folder.is_dir() else None


def read_source(source: str) -> Tuple[str, str]:
    """``(yaml text, where it came from)`` for a library file, URL, or example name."""
    path = Path(source).expanduser()
    if path.is_file():
        return path.read_text(encoding="utf-8"), str(path)
    if re.match(r"https?://", source):
        content, error = sources.fetch_url(source)
        if error:
            raise ValueError(f"could not download {source}: {error}")
        return content or "", source
    name = re.sub(r"\.ya?ml$", "", source)
    if not _EXAMPLE_NAME.fullmatch(name):
        raise ValueError(f"{source}: no such file, URL, or example library name")
    local = local_examples_dir()
    if local is not None and (local / f"{name}.yaml").is_file():
        example = local / f"{name}.yaml"
        return example.read_text(encoding="utf-8"), str(example)
    url = EXAMPLE_RAW_URL.format(name=name)
    content, error = sources.fetch_url(url)
    if error:
        raise ValueError(
            f"{source}: no such file, and no example library of that name ({url}: {error}). "
            "List them with: bibcc venues examples"
        )
    return content or "", url


def list_examples() -> Tuple[List[Tuple[str, str]], str]:
    """``([(name, details)], where)`` for the example libraries, local checkout first."""
    local = local_examples_dir()
    if local is not None:
        rows = []
        for path in sorted(local.glob("*.yaml")):
            lib = VenueLibrary.load(path)
            rows.append((path.stem, f"{len(lib.journals)} journals, {len(lib.proceedings)} proceedings"))
        return rows, str(local)
    data, error = sources.fetch_json(EXAMPLES_API_URL)
    if error or not isinstance(data, list):
        raise ValueError(f"could not list the example libraries ({error or 'unexpected answer'}); "
                         f"see {EXAMPLES_PAGE_URL}")
    rows = [(item["name"][: -len(".yaml")], "") for item in data
            if isinstance(item, dict) and str(item.get("name", "")).endswith(".yaml")]
    return sorted(rows), EXAMPLES_PAGE_URL


# ------------------------------------------------------------- subcommands


def where(start: Optional[str], log: Callable[[str], None]) -> None:
    """Show which libraries a command run on *start* reads, and which one it writes."""
    target = Path(start or Path.cwd()).expanduser().resolve()
    log(f"📦 Venue libraries for {target}")
    origin = f"${LIBRARY_ENV_VAR}" if os.environ.get(LIBRARY_ENV_VAR) else "default location"
    user_lib = VenueLibrary.load(user_library_path(), scope=USER_SCOPE)
    log(f"  user     {user_lib.sources[0].describe(with_scope=False)}  [{origin}]")
    project = find_project_library(target)
    if project is None:
        folder = target if target.is_dir() else target.parent
        log(f"  project  (none: no {PROJECT_LIBRARY_NAME} in {folder} or its parents)")
    else:
        project_lib = VenueLibrary.load(project, scope=PROJECT_SCOPE)
        log(f"  project  {project_lib.sources[0].describe(with_scope=False)}")
    merged = load_library(start=target)
    log(f"  merged   {len(merged.journals)} journals, {len(merged.proceedings)} proceedings")
    if merged.overrides:
        log(f"\n🔀 The project library overrides {len(merged.overrides)} user field(s):")
        for c in merged.overrides:
            log(f"  🔸 {c.venue} · {c.name}: project '{c.kept}' (user '{c.other}')")
    log(f"\n✏️  complete --update-venues and venues import write to the user library; pass "
        f"--scope project to write to {project or PROJECT_LIBRARY_NAME} instead.")
    if not len(merged):
        log("💡 No venues yet. Start from a shared library: bibcc venues examples")


def init(scope: str, log: Callable[[str], None]) -> int:
    """Create an empty library in *scope*; returns the exit status."""
    library = open_library(scope, create=True)
    if library.path.exists():
        log(f"ℹ️  The {scope} library already exists: {library.sources[0].describe(with_scope=False)}. "
            "Left unchanged.")
        return 0
    library.save()
    log(f"✅ Created the {scope} library {library.path}")
    if scope == PROJECT_SCOPE:
        log("   Commit it with your bibliography; it applies to every .bib file in this folder and below.")
    log(f"   Fill it with: bibcc complete <file.bib> --update-venues{' --scope project' * (scope == PROJECT_SCOPE)}")
    log(f"   or start from a shared library: bibcc venues import <name>{' --scope project' * (scope == PROJECT_SCOPE)}")
    return 0


def import_library(
    source: str,
    scope: str,
    venues: Optional[str],
    overwrite: bool,
    dry_run: bool,
    log: Callable[[str], None],
) -> int:
    """Merge the records of *source* into one library; returns the exit status."""
    try:
        text, origin = read_source(source)
        incoming = VenueLibrary.loads(text, where=origin)
    except (OSError, ValueError, yaml.YAMLError) as e:
        log(f"❌ {e}")
        return 1
    if not len(incoming):
        log(f"❌ {origin} has no journals or proceedings records.")
        return 1
    target = open_library(scope, venues=venues, create=True)
    label = "library" if venues else f"{target.scope} library"
    log(f"📥 Importing {len(incoming.journals)} journals and {len(incoming.proceedings)} proceedings")
    log(f"   from {origin}")
    log(f"   into the {label} {target.path}")
    records = incoming.journals + incoming.proceedings
    counts, conflicts = merge_records(target, records, overwrite=overwrite)
    log(f"\n➕ {counts['added']} added, 📝 {counts['updated']} updated, ⏭️  {counts['unchanged']} unchanged")
    if conflicts:
        verb = "replaced" if overwrite else "kept yours"
        log(f"\n⚠️  {len(conflicts)} field(s) differ ({verb}):")
        for c in conflicts:
            if overwrite:
                log(f"  🔸 {c.venue} · {c.name}: '{c.kept}' (was '{c.other}')")
            else:
                log(f"  🔸 {c.venue} · {c.name}: kept '{c.kept}' (incoming '{c.other}')")
        if not overwrite:
            log("   Pass --overwrite to take the incoming values instead.")
    if dry_run:
        log("\n🧪 Dry run: nothing written.")
        return 0
    if counts["added"] or counts["updated"] or not target.path.exists():
        target.save()
        log(f"\n✅ Saved {target.path}")
    else:
        log("\nℹ️  Nothing new to import.")
    return 0


def examples(log: Callable[[str], None]) -> int:
    """List the shared example libraries; returns the exit status."""
    try:
        rows, origin = list_examples()
    except ValueError as e:
        log(f"❌ {e}")
        return 1
    log(f"📚 Example venue libraries ({origin}):")
    if not rows:
        log("  (none)")
    width = max((len(name) for name, _ in rows), default=0)
    for name, details in rows:
        log(f"  {name:<{width}}  {details}".rstrip())
    log("\nImport one into your user library with 'bibcc venues import <name>',")
    log("or into the project library with 'bibcc venues import <name> --scope project'.")
    log(f"What each one covers: {EXAMPLES_PAGE_URL}")
    return 0


# ------------------------------------------------------------------ parser


_DESCRIPTION = f"""\
Manage the venue libraries 'complete', 'add', and 'upgrade' take venue fields
from. BibCC ships no library: you build your own, in two scopes.

  user     ${LIBRARY_ENV_VAR}, else $XDG_CONFIG_HOME/bibcc/venues.yaml
           ({USER_LIBRARY_DISPLAY}). Venues for all your projects.
  project  {PROJECT_LIBRARY_NAME}, the nearest one in the folder of the .bib
           file or a parent folder. Venues for one project; commit it with
           the bibliography.

Commands read both, merged: a venue defined in both gets the project's value
for every field both define, and the other fields of both. They write one
scope only, the user library unless --scope project is given, and say which
file they write. --venues FILE uses that one file instead of both.

Shared libraries (for example the MIAA lab's, 'miaa') live in examples/venues/
of the BibCC repository. 'import' merges one into your user or project library;
your values are kept where they differ unless --overwrite is given."""


def build_parser() -> argparse.ArgumentParser:
    """Build parser with the venues subcommands."""
    parser = argparse.ArgumentParser(
        description=_DESCRIPTION,
        epilog=epilog(
            examples=[
                ("which libraries apply to this file, and which one is written",
                 "bibcc venues where bib/refs.bib"),
                ("start a project library in the current folder", "bibcc venues init --scope project"),
                ("list the shared libraries", "bibcc venues examples"),
                ("start your user library from the MIAA lab's", "bibcc venues import miaa"),
                ("merge a colleague's file into the project library",
                 "bibcc venues import ~/lab-venues.yaml --scope project"),
            ],
            env=[ENV_VENUES],
        ),
        formatter_class=HelpFormatter,
    )
    subparsers = parser.add_subparsers(dest="command", required=True, metavar="SUBCOMMAND")

    p_where = subparsers.add_parser(
        "where",
        help="Show the user and project libraries that apply, and which one is written.",
        description="Show the user library, the project library that applies to PATH (the\n"
        "nearest .bibcc-venues.yaml above it), their sizes, the fields the project\n"
        "overrides, and which library commands write to.",
        epilog=epilog(
            examples=[
                ("for the current folder", "bibcc venues where"),
                ("for a .bib file elsewhere", "bibcc venues where ~/papers/survey/bib/refs.bib"),
            ],
            env=[ENV_VENUES],
        ),
        formatter_class=HelpFormatter,
    )
    p_where.add_argument("path", nargs="?", default=None, metavar="PATH",
                         help="A .bib file or folder (default: the current folder).")

    p_init = subparsers.add_parser(
        "init",
        help="Create an empty user or project library.",
        description="Create an empty venue library: the user library, or with --scope project a\n"
        f"{PROJECT_LIBRARY_NAME} in the current folder (your project root). An existing\n"
        "library is left unchanged.",
        epilog=epilog(
            examples=[
                ("create the user library", "bibcc venues init"),
                ("create a project library here", "bibcc venues init --scope project"),
            ],
            outputs=[(f"{USER_LIBRARY_DISPLAY} or ./{PROJECT_LIBRARY_NAME}", "the new library")],
            env=[ENV_VENUES],
        ),
        formatter_class=HelpFormatter,
    )
    p_init.add_argument("--scope", choices=SCOPES, default=USER_SCOPE, help=SCOPE_HELP)

    p_import = subparsers.add_parser(
        "import",
        help="Merge a shared library (file, URL, or example name) into yours.",
        description="Merge the records of SOURCE into the user library (default), the project\n"
        "library (--scope project; created in the current folder if there is none), or\n"
        "the file given with --venues. Records new to it are added; for a venue it\n"
        "already has, missing fields, aliases, and interim booktitles are added and\n"
        "the fields that differ keep your value (reported) unless --overwrite.\n\n"
        "SOURCE is a library file, an http(s) URL, or the name of a library in\n"
        "examples/venues/ of the BibCC repository (see 'bibcc venues examples'),\n"
        "read from your checkout when BibCC runs from one, else downloaded.",
        epilog=epilog(
            examples=[
                ("start your user library from the MIAA lab's", "bibcc venues import miaa"),
                ("preview what a library would add to the project library",
                 "bibcc venues import miaa --scope project --dry-run"),
                ("let a curated file win over your values",
                 "bibcc venues import ~/lab-venues.yaml --overwrite"),
                ("refresh an example library from your user library (maintainers)",
                 f"bibcc venues import {USER_LIBRARY_DISPLAY} --venues examples/venues/miaa.yaml"),
            ],
            outputs=[("the library written", f"{USER_LIBRARY_DISPLAY}, {PROJECT_LIBRARY_NAME}, or --venues FILE")],
            exit_status="0 on success (also when nothing is new), 1 if SOURCE cannot be read,\n"
            "2 on usage errors.",
            env=[ENV_VENUES],
        ),
        formatter_class=HelpFormatter,
    )
    p_import.add_argument("source", metavar="SOURCE",
                          help="Library file, http(s) URL, or example library name (e.g. miaa).")
    target = p_import.add_mutually_exclusive_group()
    target.add_argument("--scope", choices=SCOPES, default=None, help=SCOPE_HELP)
    target.add_argument("--venues", default="", metavar="FILE",
                        help="Write to this library file instead of a scope.")
    p_import.add_argument("--overwrite", action="store_true",
                          help="Where a field differs, take the value of SOURCE (default: keep yours).")
    p_import.add_argument("--dry-run", action="store_true",
                          help="Report what would change without writing anything.")

    subparsers.add_parser(
        "examples",
        help="List the shared example libraries.",
        description="List the venue libraries in examples/venues/ of the BibCC repository (your\n"
        "checkout when BibCC runs from one, else GitHub), ready for 'bibcc venues import'.",
        epilog=epilog(examples=[("list them", "bibcc venues examples")]),
        formatter_class=HelpFormatter,
    )
    return parser


def main() -> None:
    """CLI entry point."""
    args = build_parser().parse_args()
    # These commands only print summaries, so no log file (and no .bibcc/ folder) is written.
    with Logger("venues", enabled=False) as logger:
        if args.command == "where":
            where(args.path, logger.log)
            status = 0
        elif args.command == "init":
            status = init(args.scope, logger.log)
        elif args.command == "import":
            status = import_library(args.source, args.scope or USER_SCOPE, args.venues or None,
                                    args.overwrite, args.dry_run, logger.log)
        else:
            status = examples(logger.log)
    sys.exit(status)


if __name__ == "__main__":
    main()
