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
    bibcc venues providers
    bibcc venues import miaa
    bibcc venues import ./lab-venues.yaml --scope project
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

import yaml

from bibcc.families import PROVIDERS, builtin_families, registry
from bibcc.helptext import ENV_VENUES, SCOPE_HELP, HelpFormatter, epilog
from bibcc.logging_utils import Logger
from bibcc.scopes import EXAMPLES_PAGE_URL, VENUES, example_names, read_source
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
    merge_families,
    merge_records,
    open_library,
    user_library_path,
)


def list_examples() -> Tuple[List[Tuple[str, str]], str]:
    """``([(name, details)], where)`` for the example libraries, local checkout first."""
    paths, names, origin = example_names(VENUES)
    rows = []
    for path in paths:
        lib = VenueLibrary.load(path)
        details = f"{len(lib.journals)} journals, {len(lib.proceedings)} proceedings"
        if lib.families:
            details += f", {len(lib.families)} families"
        rows.append((path.stem, details))
    return rows + [(name, "") for name in names], origin


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
    log(f"  merged   {len(merged.journals)} journals, {len(merged.proceedings)} proceedings, "
        f"{len(merged.families)} families")
    if merged.overrides:
        log(f"\n🔀 The project library overrides {len(merged.overrides)} user field(s):")
        for c in merged.overrides:
            log(f"  🔸 {c.venue} · {c.name}: project '{c.kept}' (user '{c.other}')")
    log(f"\n✏️  complete --update-venues and venues import write to the user library. To write "
        f"to {project or PROJECT_LIBRARY_NAME} instead, pass --scope project.")
    if not len(merged):
        log("💡 No venues yet. To start from a shared profile (config, venues, and terms), run: "
            "bibcc config profile NAME. To list the shared libraries, run: bibcc venues examples")


_PROVIDER_DETAILS = ("acronym_aliases", "workshop_of", "pattern", "site", "interim_since", "blocked_by",
                     "manual_url")


def provider_rows(library: VenueLibrary) -> List[Dict[str, object]]:
    """The effective provider table: the built-in rows with *library*'s family records applied.

    Each row has the :class:`bibcc.families.Spec` keys and ``source``:
    ``built-in``, or the scopes of the family records that add or change
    the row (``built-in + project``, ``user``, and so on).
    """
    reg = registry(library)
    builtin = {spec.acronym.casefold() for spec in builtin_families()}
    lookup = reg._lookup
    overrides: Dict[str, List[str]] = {}
    for family in library.families:
        if family.acronym and family.routing:
            key = lookup.get(family.acronym.casefold(), family.acronym.casefold())
            origins = overrides.setdefault(key, [])
            for origin in (family.origin or "library").split("+"):
                if origin not in origins:
                    origins.append(origin)
    rows: List[Dict[str, object]] = []
    for key, spec in sorted(reg.specs.items(), key=lambda item: item[1].acronym.casefold()):
        parts = (["built-in"] if key in builtin else []) + overrides.get(key, [])
        row: Dict[str, object] = dict(vars(spec))
        row["source"] = " + ".join(parts) or "built-in"
        rows.append(row)
    return rows


def providers(start: Optional[str], venues: Optional[str], fmt: str, log: Callable[[str], None]) -> int:
    """Print the effective provider table; returns the exit status."""
    library = load_library(venues, start=start)
    rows = provider_rows(library)
    reg = registry(library)
    if fmt == "json":
        log(json.dumps({
            "families": rows,
            "doi_prefixes": reg.doi_prefixes,
            "blocked_doi_prefixes": reg.blocked_prefixes,
        }, indent=2, ensure_ascii=False))
        return 0
    log(f"🧭 Where BibCC finds the official BibTeX of each conference ({library.describe()})")
    log("")
    table = [("ACRONYM", "PROVIDER", "INTERIM", "SOURCE", "DETAILS")]
    for row in rows:
        details = []
        for key in _PROVIDER_DETAILS:
            value = row.get(key)
            if value:
                details.append(f"{key}: {', '.join(value) if isinstance(value, list) else value}")
        table.append((str(row["acronym"]), str(row["provider"] or "-"), str(row["interim"] or "-"),
                      str(row["source"]), "; ".join(details)))
    widths = [max(len(r[i]) for r in table) for i in range(4)]
    for r in table:
        log(("  " + "  ".join(f"{r[i]:<{widths[i]}}" for i in range(4)) + f"  {r[4]}").rstrip())
    log("\n🔗 DOI prefixes: " + ", ".join(f"{p} {name}" for p, name in reg.doi_prefixes.items()))
    log("⛔ Blocked DOI prefixes: " + ", ".join(f"{p} {name}" for p, name in reg.blocked_prefixes.items()))
    log("\nTo change a row or add a conference, give its family record in your venue library the "
        "keys to set (for example, provider: pmlr). For the keys, see 'bibcc venues providers -h'.")
    return 0


def init(scope: str, log: Callable[[str], None]) -> int:
    """Create an empty library in *scope*; returns the exit status."""
    found = find_project_library() if scope == PROJECT_SCOPE else None
    if scope == PROJECT_SCOPE and found is None:
        library = VenueLibrary.load(Path.cwd() / PROJECT_LIBRARY_NAME, scope=PROJECT_SCOPE)
    else:
        library = open_library(scope)
    if library.path.exists():
        log(f"ℹ️  The {scope} library already exists: {library.sources[0].describe(with_scope=False)}. "
            "Left unchanged.")
        return 0
    library.save()
    log(f"✅ Created the {scope} library {library.path}")
    if scope == PROJECT_SCOPE:
        log("   Commit it with your bibliography; it applies to every .bib file in this directory "
            "and its subdirectories.")
    log(f"   Fill it with: bibcc complete FILE.bib --update-venues{' --scope project' * (scope == PROJECT_SCOPE)}")
    log(f"   or start from a shared library: bibcc venues import NAME{' --scope project' * (scope == PROJECT_SCOPE)}")
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
        text, origin = read_source(source, VENUES)
        incoming = VenueLibrary.loads(text, where=origin)
    except (OSError, ValueError, yaml.YAMLError) as e:
        log(f"❌ {e}")
        return 1
    if not len(incoming):
        log(f"❌ {origin} has no journals, proceedings, or families records.")
        return 1
    target = open_library(scope, venues=venues, create=True)
    label = "library" if venues else f"{target.scope} library"
    log(f"📥 Importing {len(incoming.journals)} journals, {len(incoming.proceedings)} proceedings, "
        f"and {len(incoming.families)} families")
    log(f"   from {origin}")
    log(f"   into the {label} {target.path}")
    records = incoming.journals + incoming.proceedings
    counts, conflicts = merge_records(target, records, overwrite=overwrite)
    family_counts, family_conflicts = merge_families(target, incoming.families, overwrite=overwrite)
    counts = {k: counts[k] + family_counts[k] for k in counts}
    conflicts += family_conflicts
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
            log("   To take the incoming values instead, pass --overwrite.")
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
    log("\nTo import one into your user library, run 'bibcc venues import NAME'.")
    log("To import it into the project library instead, add --scope project.")
    log(f"What each one covers: {EXAMPLES_PAGE_URL.format(kind='venues')}")
    return 0


# ------------------------------------------------------------------ parser


_DESCRIPTION = f"""\
Manage the venue libraries that 'complete', 'add', and 'upgrade' take venue
fields from. BibCC doesn't ship a library: you build your own, in two scopes.

  user     ${LIBRARY_ENV_VAR}, or else $XDG_CONFIG_HOME/bibcc/venues.yaml
           ({USER_LIBRARY_DISPLAY}). Venues for all your projects.
  project  {PROJECT_LIBRARY_NAME}, the nearest one in the directory of the
           .bib file or a parent directory. Venues for one project; commit it with
           the bibliography.

Commands read both libraries, merged: a venue defined in both gets the
project's value for every field that both define, and the other fields of
both. Commands write only one scope (the user library, unless you pass
--scope project), and they log which file they write. --venues FILE uses
that one file instead of both.

Shared libraries (for example, the MIAA lab's library, 'miaa') live in
examples/venues/ of the BibCC repository. 'import' merges one into your user
or project library; where the values differ, it keeps yours unless you pass
--overwrite."""


def build_parser() -> argparse.ArgumentParser:
    """Build parser with the venues subcommands."""
    parser = argparse.ArgumentParser(
        description=_DESCRIPTION,
        epilog=epilog(
            examples=[
                ("Show which libraries apply to this file, and which one commands write to",
                 "bibcc venues where bib/refs.bib"),
                ("Start a project library in the current directory", "bibcc venues init --scope project"),
                ("List the shared libraries", "bibcc venues examples"),
                ("Show where BibCC finds each conference's official BibTeX", "bibcc venues providers"),
                ("Start your user library from the MIAA lab's library", "bibcc venues import miaa"),
                ("Merge a colleague's file into the project library",
                 "bibcc venues import ~/lab-venues.yaml --scope project"),
            ],
            env=[ENV_VENUES],
        ),
        formatter_class=HelpFormatter,
    )
    subparsers = parser.add_subparsers(dest="command", required=True, metavar="SUBCOMMAND")

    p_where = subparsers.add_parser(
        "where",
        help="Show the user and project libraries that apply, and which one commands write to.",
        description="Show the user library, the project library that applies to PATH (the\n"
        "nearest .bibcc-venues.yaml in its directory or a parent directory), their sizes,\n"
        "the fields that the project overrides, and which library commands write to.",
        epilog=epilog(
            examples=[
                ("Show the libraries for the current directory", "bibcc venues where"),
                ("Show the libraries for a .bib file elsewhere", "bibcc venues where ~/papers/survey/bib/refs.bib"),
            ],
            env=[ENV_VENUES],
        ),
        formatter_class=HelpFormatter,
    )
    p_where.add_argument("path", nargs="?", default=None, metavar="PATH",
                         help="A .bib file or directory (default: the current directory).")

    p_init = subparsers.add_parser(
        "init",
        help="Create an empty user or project library.",
        description="Create an empty venue library: the user library, or with --scope project a\n"
        f"{PROJECT_LIBRARY_NAME} in the current directory (your project root). The command\n"
        "leaves an existing library unchanged.",
        epilog=epilog(
            examples=[
                ("Create the user library", "bibcc venues init"),
                ("Create a project library here", "bibcc venues init --scope project"),
            ],
            outputs=[(f"{USER_LIBRARY_DISPLAY} or ./{PROJECT_LIBRARY_NAME}", "The new library")],
            env=[ENV_VENUES],
        ),
        formatter_class=HelpFormatter,
    )
    p_init.add_argument("--scope", choices=SCOPES, default=USER_SCOPE, help=SCOPE_HELP)

    p_import = subparsers.add_parser(
        "import",
        help="Merge a shared library (file, URL, or example name) into yours.",
        description="Merge the records of SOURCE into the user library (default), the project\n"
        "library (--scope project; if there's none, a new one goes next to the project's\n"
        "other BibCC files, or in the current directory), or the file that --venues\n"
        "names. The command adds records that are new to the library. For a venue that\n"
        "the library already has, it adds missing fields, aliases, and interim\n"
        "booktitles; for fields that differ, it keeps and reports your value, unless\n"
        "you pass --overwrite.\n\n"
        "SOURCE is a library file, an http(s) URL, or the name of a library in\n"
        "examples/venues/ of the BibCC repository (see 'bibcc venues examples'). The\n"
        "command reads an example library from your checkout when BibCC runs from one,\n"
        "and otherwise downloads it.",
        epilog=epilog(
            examples=[
                ("Start your user library from the MIAA lab's library", "bibcc venues import miaa"),
                ("Preview what a library would add to the project library",
                 "bibcc venues import miaa --scope project --dry-run"),
                ("Let a curated file win over your values",
                 "bibcc venues import ~/lab-venues.yaml --overwrite"),
                ("Refresh an example library from your user library (for maintainers)",
                 f"bibcc venues import {USER_LIBRARY_DISPLAY} --venues examples/venues/miaa.yaml"),
            ],
            outputs=[(f"{USER_LIBRARY_DISPLAY}, {PROJECT_LIBRARY_NAME}, or --venues FILE",
                      "The library that the command writes")],
            exit_status="0 on success (also when nothing is new), 1 if BibCC can't read SOURCE,\n"
            "2 on usage errors.",
            env=[ENV_VENUES],
        ),
        formatter_class=HelpFormatter,
    )
    p_import.add_argument("source", metavar="SOURCE",
                          help="Library file, http(s) URL, or example library name (for example, miaa).")
    target = p_import.add_mutually_exclusive_group()
    target.add_argument("--scope", choices=SCOPES, default=None, help=SCOPE_HELP)
    target.add_argument("--venues", default="", metavar="FILE",
                        help="Write to this library file instead of a scope.")
    p_import.add_argument("--overwrite", action="store_true",
                          help="Where a field differs, take the value of SOURCE (default: keep yours).")
    p_import.add_argument("--dry-run", action="store_true",
                          help="Report what would change without writing anything.")

    p_providers = subparsers.add_parser(
        "providers",
        help="Show where BibCC finds each conference's official BibTeX.",
        description="Show the provider table that 'add', 'upgrade', and 'check official' use: for\n"
        "each conference family, where its published BibTeX comes from (the provider),\n"
        "where it comes from before the proceedings are out (the interim source), and\n"
        "whether the row is built in or set by a family record of your venue libraries.\n\n"
        "To change a row, or to add a conference, give the family record in your venue\n"
        "library an acronym and the keys to set:\n\n"
        f"  provider         {', '.join(PROVIDERS)}\n"
        "  site             The proceedings site, for provider proceedings\n"
        "  interim          cvf or openreview\n"
        "  interim_since    The first year whose interim BibTeX isn't the official one\n"
        "  acronym_aliases  Other spellings of the acronym\n"
        "  pattern          A regular expression that names the family in a booktitle\n"
        "  workshop_of      The family whose booktitle, with \"workshop\", names this one\n"
        "  blocked_by       Who blocks downloads, for provider blocked\n"
        "  manual_url       Where to get the BibTeX by hand",
        epilog=epilog(
            examples=[
                ("Show the table for the current directory", "bibcc venues providers"),
                ("Show it as JSON", "bibcc venues providers --format json"),
            ],
            env=[ENV_VENUES],
        ),
        formatter_class=HelpFormatter,
    )
    p_providers.add_argument("path", nargs="?", default=None, metavar="PATH",
                             help="A .bib file or directory, to find the project library "
                             "(default: the current directory).")
    p_providers.add_argument("--venues", default="", metavar="FILE",
                             help="Apply only the family records of this library file.")
    p_providers.add_argument("--format", choices=("text", "json"), default="text",
                             help="Output format: 'text' (default) or 'json'.")

    subparsers.add_parser(
        "examples",
        help="List the shared example libraries.",
        description="List the venue libraries in examples/venues/ of the BibCC repository (your\n"
        "checkout when BibCC runs from one, or else GitHub), ready for\n"
        "'bibcc venues import'.",
        epilog=epilog(examples=[("List the example libraries", "bibcc venues examples")]),
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
        elif args.command == "providers":
            status = providers(args.path, args.venues or None, args.format, logger.log)
        else:
            status = examples(logger.log)
    sys.exit(status)


if __name__ == "__main__":
    main()
