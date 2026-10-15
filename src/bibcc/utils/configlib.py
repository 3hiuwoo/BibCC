"""
Config - manage the user and project config files.

The user config (``$BIBCC_CONFIG``, else ``~/.config/bibcc/config.yaml``)
holds settings for every project, and a project config (``.bibcc.yaml``,
committed with the bibliography) holds the settings of one project and wins
where both set a key.  Shared configs to start from live in
``examples/config/`` of the BibCC repository.

Usage:
    bibcc config where bib/refs.bib
    bibcc config init --scope project
    bibcc config examples
    bibcc config import miaa --scope project
"""

from __future__ import annotations

import argparse
import os
import re
import sys
import textwrap
from pathlib import Path
from typing import Any, Callable, List, Optional, Tuple

import bibcc
from bibcc import sources
from bibcc.adder import FIELD_ORDER
from bibcc.config import (
    CONFIG_ENV_VAR,
    FILE_SCOPE,
    FORMAT_SETTINGS,
    HEADER,
    OTHER_FIELDS,
    PROJECT_CONFIG_NAME,
    PROJECT_SCOPE,
    SCOPES,
    SECTIONS,
    USER_CONFIG_DISPLAY,
    USER_SCOPE,
    ConfigError,
    ConfigFile,
    config_path,
    field_order_yaml,
    find_project_config,
    load_config,
    merge,
    merge_into,
    parse_yaml,
    user_config_path,
)
from bibcc.helptext import ENV_CONFIG, REPO, HelpFormatter, epilog
from bibcc.logging_utils import Logger

EXAMPLES_BRANCH = "main"
EXAMPLE_RAW_URL = f"https://raw.githubusercontent.com/{REPO}/{EXAMPLES_BRANCH}/examples/config/{{name}}.yaml"
EXAMPLES_API_URL = f"https://api.github.com/repos/{REPO}/contents/examples/config?ref={EXAMPLES_BRANCH}"
EXAMPLES_PAGE_URL = f"https://github.com/{REPO}/tree/{EXAMPLES_BRANCH}/examples/config"

_EXAMPLE_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*")

SCOPE_HELP = (
    f"Config file to write to: 'user' (default; ${CONFIG_ENV_VAR} or {USER_CONFIG_DISPLAY}) or "
    f"'project' (the nearest {PROJECT_CONFIG_NAME} in the current directory or a parent directory, "
    "or a new one in the current directory)."
)


# ---------------------------------------------------------------- sources


def local_examples_dir() -> Optional[Path]:
    """``examples/config/`` of the checkout BibCC runs from, if it runs from one (editable install)."""
    folder = Path(bibcc.__file__).resolve().parents[2] / "examples" / "config"
    return folder if folder.is_dir() else None


def read_source(source: str) -> Tuple[str, str]:
    """``(yaml text, where it came from)`` for a config file, URL, or example name."""
    path = Path(source).expanduser()
    if path.is_file():
        return path.read_text(encoding="utf-8"), str(path)
    if re.match(r"https?://", source):
        content, error = sources.fetch_url(source)
        if error:
            raise ConfigError(f"could not download {source}: {error}")
        return content or "", source
    name = re.sub(r"\.ya?ml$", "", source)
    if not _EXAMPLE_NAME.fullmatch(name):
        raise ConfigError(f"{source}: no such file, URL, or example config name")
    local = local_examples_dir()
    if local is not None and (local / f"{name}.yaml").is_file():
        example = local / f"{name}.yaml"
        return example.read_text(encoding="utf-8"), str(example)
    url = EXAMPLE_RAW_URL.format(name=name)
    content, error = sources.fetch_url(url)
    if error:
        raise ConfigError(
            f"{source}: no such file, and no example config of that name ({url}: {error}). "
            "List them with: bibcc config examples"
        )
    return content or "", url


def _summary(data: dict) -> str:
    parts = [f"{name} ({len(keys)} setting{'s' * (len(keys) != 1)})" for name, keys in data.items()]
    return ", ".join(parts) or "empty"


def list_examples() -> Tuple[List[Tuple[str, str]], str]:
    """``([(name, details)], where)`` for the example configs, local checkout first."""
    local = local_examples_dir()
    if local is not None:
        rows = []
        for path in sorted(local.glob("*.yaml")):
            try:
                details = _summary(parse_yaml(path.read_text(encoding="utf-8"), str(path)))
            except ConfigError as e:
                details = f"unreadable: {e}"
            rows.append((path.stem, details))
        return rows, str(local)
    data, error = sources.fetch_json(EXAMPLES_API_URL)
    if error or not isinstance(data, list):
        raise ConfigError(f"could not list the example configs ({error or 'unexpected answer'}); "
                          f"see {EXAMPLES_PAGE_URL}")
    rows = [(item["name"][: -len(".yaml")], "") for item in data
            if isinstance(item, dict) and str(item.get("name", "")).endswith(".yaml")]
    return sorted(rows), EXAMPLES_PAGE_URL


# ------------------------------------------------------------- rendering


def show_value(key: str, value: Any) -> str:
    """A setting's value as the config file would write it, on one line."""
    if key == "field_order":
        if value is None:
            return f"the order that add uses: {', '.join(FIELD_ORDER)}, {OTHER_FIELDS}"
        order = list(value)
        return ", ".join(order + ([] if OTHER_FIELDS in order else [OTHER_FIELDS]))
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def template() -> str:
    """The text of a new config file: every format: setting, commented out, at its default."""
    lines = [HEADER, "format:"]
    for key, setting in FORMAT_SETTINGS.items():
        lines += textwrap.wrap(setting.help, 88, initial_indent="  # ", subsequent_indent="  # ")
        if key == "field_order":
            order = ", ".join(field_order_yaml(FIELD_ORDER)["first"])
            lines.append("  # field_order:")
            lines += textwrap.wrap(f"first: [{order}]", 88, initial_indent="  #   ",
                                   subsequent_indent="  #     ")
            lines.append("  #   last: []")
        else:
            lines.append(f"  # {key}: {show_value(key, setting.default)}")
    return "\n".join(lines) + "\n"


# ------------------------------------------------------------- subcommands


def where(start: Optional[str], log: Callable[[str], None]) -> int:
    """Show which config files a command run on *start* reads, and the settings they give."""
    target = Path(start or Path.cwd()).expanduser().resolve()
    log(f"⚙️  Config files for {target}")
    origin = f"${CONFIG_ENV_VAR}" if os.environ.get(CONFIG_ENV_VAR) else "default location"
    user = user_config_path()
    log(f"  user     {user}{'' if user.is_file() else ' (none yet)'}  [{origin}]")
    project = find_project_config(target)
    if project is None:
        folder = target if target.is_dir() else target.parent
        log(f"  project  (none: no {PROJECT_CONFIG_NAME} in {folder} or its parents)")
    else:
        log(f"  project  {project}")
    try:
        config = load_config(start=target)
    except ConfigError as e:
        log(f"\n❌ {e}")
        return 1
    for name, settings in SECTIONS.items():
        values = config.section(name)
        log(f"\n{name}:")
        width = max(len(key) for key in settings)
        for key, setting in settings.items():
            value = values.get(key, setting.default)
            log(f"  {key:<{width}}  {show_value(key, value)}  [{config.origin(name, key)}]")
    for warning in config.warnings:
        log(f"⚠️  {warning}")
    log(f"\n✏️  init and import write to the user config. To write to "
        f"{project or PROJECT_CONFIG_NAME} instead, pass --scope project.")
    if not config.present:
        log("💡 No config files yet. Start from a shared config: bibcc config examples")
    return 0


def init(scope: str, log: Callable[[str], None]) -> int:
    """Create a config file in *scope*, with every setting commented out; returns the exit status."""
    path = config_path(scope, create=True)
    if path.exists():
        log(f"ℹ️  The {scope} config already exists: {path}. Left unchanged.")
        return 0
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(template(), encoding="utf-8")
    log(f"✅ Created the {scope} config {path}")
    log("   It lists every setting, commented out at its default; uncomment the ones to change.")
    if scope == PROJECT_SCOPE:
        log("   Commit it with your bibliography; it applies to every .bib file in this directory "
            "and its subdirectories.")
    log(f"   Or start from a shared config: bibcc config import NAME{' --scope project' * (scope == PROJECT_SCOPE)}")
    return 0


def import_config(
    source: str,
    scope: str,
    config: Optional[str],
    overwrite: bool,
    dry_run: bool,
    log: Callable[[str], None],
) -> int:
    """Merge the settings of *source* into one config file; returns the exit status."""
    try:
        text, origin = read_source(source)
        incoming = parse_yaml(text, origin)
        checked = merge([ConfigFile(FILE_SCOPE, Path(origin), incoming)])
        target_path = Path(config).expanduser() if config else config_path(scope, create=True)
        target = ConfigFile.load(target_path, FILE_SCOPE if config else scope)
    except (OSError, ConfigError) as e:
        log(f"❌ {e}")
        return 1
    if not any(incoming.values()):
        log(f"❌ {origin} has no settings.")
        return 1
    label = "config" if config else f"{scope} config"
    log(f"📥 Importing {_summary(incoming)}")
    log(f"   from {origin}")
    log(f"   into the {label} {target.path}")
    for warning in checked.warnings:
        log(f"⚠️  {warning}")
    counts, differ = merge_into(target, incoming, overwrite)
    log(f"\n➕ {counts['added']} added, 📝 {counts['updated']} updated, ⏭️  {counts['unchanged']} unchanged")
    if differ:
        verb = "replaced" if overwrite else "kept yours"
        log(f"\n⚠️  {len(differ)} setting(s) differ ({verb}):")
        for key, kept, other in differ:
            name = key.split(".", 1)[1]
            if overwrite:
                log(f"  🔸 {key}: {show_value(name, kept)} (was {show_value(name, other)})")
            else:
                log(f"  🔸 {key}: kept {show_value(name, kept)} (incoming {show_value(name, other)})")
        if not overwrite:
            log("   To take the incoming values instead, pass --overwrite.")
    if dry_run:
        log("\n🧪 Dry run: nothing written.")
        return 0
    if counts["added"] or counts["updated"] or not target.exists:
        try:
            merge([target])  # never save a file that commands can't read
        except ConfigError as e:
            log(f"❌ {e}")
            return 1
        target.save()
        log(f"\n✅ Saved {target.path}")
    else:
        log("\nℹ️  Nothing new to import.")
    return 0


def examples(log: Callable[[str], None]) -> int:
    """List the shared example configs; returns the exit status."""
    try:
        rows, origin = list_examples()
    except ConfigError as e:
        log(f"❌ {e}")
        return 1
    log(f"📚 Example configs ({origin}):")
    if not rows:
        log("  (none)")
    width = max((len(name) for name, _ in rows), default=0)
    for name, details in rows:
        log(f"  {name:<{width}}  {details}".rstrip())
    log("\nTo import one into your user config, run 'bibcc config import NAME'.")
    log("To import it into the project config instead, add --scope project.")
    log(f"What each one sets: {EXAMPLES_PAGE_URL}")
    return 0


# ------------------------------------------------------------------ parser


def _settings_table() -> str:
    width = max(len(key) for key in FORMAT_SETTINGS)
    return "\n".join(
        textwrap.fill(s.help, 80, initial_indent=f"  {key:<{width}}  ", subsequent_indent=" " * (width + 4))
        for key, s in FORMAT_SETTINGS.items()
    )


_DESCRIPTION = f"""\
Manage the config files that hold your settings. Like the venue library, a
config lives in two scopes:

  user     ${CONFIG_ENV_VAR}, or else $XDG_CONFIG_HOME/bibcc/config.yaml
           ({USER_CONFIG_DISPLAY}). Settings for all your projects.
  project  {PROJECT_CONFIG_NAME}, the nearest one in the directory of the .bib
           file or a parent directory. Settings for one project; commit it with
           the bibliography so that everyone formats the same way.

Commands read both files: where both set a key, the project's value wins, and
an option that you pass on the command line wins over both. Each command
reads its own section. This release reads the format: section, which 'bibcc
format' uses:

{_settings_table()}

A field order such as

  format:
    sort_fields: true
    field_order:
      first: [title, author, year, month, booktitle, journal]
      last: [citation]

puts the first fields at the top, every field that it doesn't list (a new
field included) after them in source order, and the last fields at the
bottom. Field names that aren't known BibTeX fields are reported, and a key
that this release doesn't know is reported and ignored.

Shared configs (for example, the MIAA lab's config, 'miaa') live in
examples/config/ of the BibCC repository. 'import' merges one into your user
or project config; where the values differ, it keeps yours unless you pass
--overwrite."""


def build_parser() -> argparse.ArgumentParser:
    """Build parser with the config subcommands."""
    parser = argparse.ArgumentParser(
        description=_DESCRIPTION,
        epilog=epilog(
            examples=[
                ("Show which config files apply to this file, and the settings they give",
                 "bibcc config where bib/refs.bib"),
                ("Start a project config in the current directory", "bibcc config init --scope project"),
                ("List the shared configs", "bibcc config examples"),
                ("Give the project the MIAA lab's format settings", "bibcc config import miaa --scope project"),
            ],
            env=[ENV_CONFIG],
        ),
        formatter_class=HelpFormatter,
    )
    subparsers = parser.add_subparsers(dest="command", required=True, metavar="SUBCOMMAND")

    p_where = subparsers.add_parser(
        "where",
        help="Show the user and project config files that apply, and the settings they give.",
        description=f"Show the user config, the project config that applies to PATH (the nearest\n"
        f"{PROJECT_CONFIG_NAME} in its directory or a parent directory), and the value of every\n"
        "setting with where it comes from: default, user, or project.",
        epilog=epilog(
            examples=[
                ("Show the settings for the current directory", "bibcc config where"),
                ("Show the settings for a .bib file elsewhere", "bibcc config where ~/papers/survey/bib/refs.bib"),
            ],
            exit_status="0 on success, 1 if a config file is invalid.",
            env=[ENV_CONFIG],
        ),
        formatter_class=HelpFormatter,
    )
    p_where.add_argument("path", nargs="?", default=None, metavar="PATH",
                         help="A .bib file or directory (default: the current directory).")

    p_init = subparsers.add_parser(
        "init",
        help="Create a user or project config that lists every setting.",
        description="Create a config file: the user config, or with --scope project a\n"
        f"{PROJECT_CONFIG_NAME} in the current directory (your project root). The file lists\n"
        "every setting, commented out at its default. The command leaves an existing\n"
        "file unchanged.",
        epilog=epilog(
            examples=[
                ("Create the user config", "bibcc config init"),
                ("Create a project config here", "bibcc config init --scope project"),
            ],
            outputs=[(f"{USER_CONFIG_DISPLAY} or ./{PROJECT_CONFIG_NAME}", "The new config file")],
            env=[ENV_CONFIG],
        ),
        formatter_class=HelpFormatter,
    )
    p_init.add_argument("--scope", choices=SCOPES, default=USER_SCOPE, help=SCOPE_HELP)

    p_import = subparsers.add_parser(
        "import",
        help="Merge a shared config (file, URL, or example name) into yours.",
        description="Merge the settings of SOURCE into the user config (default), the project\n"
        "config (--scope project; created in the current directory if there's none), or\n"
        "the file that --config names. The command adds the settings that the file\n"
        "lacks. For a setting that differs, it keeps and reports your value, unless you\n"
        "pass --overwrite. It checks SOURCE first and imports nothing from a file with\n"
        "an invalid value. The file is rewritten, so comments other than the header\n"
        "aren't kept.\n\n"
        "SOURCE is a config file, an http(s) URL, or the name of a config in\n"
        "examples/config/ of the BibCC repository (see 'bibcc config examples'). The\n"
        "command reads an example config from your checkout when BibCC runs from one,\n"
        "and otherwise downloads it.",
        epilog=epilog(
            examples=[
                ("Give the project the MIAA lab's format settings", "bibcc config import miaa --scope project"),
                ("Preview what a config would change in your user config", "bibcc config import miaa --dry-run"),
                ("Let a lab file win over your values", "bibcc config import ~/lab-config.yaml --overwrite"),
            ],
            outputs=[(f"{USER_CONFIG_DISPLAY}, {PROJECT_CONFIG_NAME}, or --config FILE",
                      "The config file that the command writes")],
            exit_status="0 on success (also when nothing is new), 1 if BibCC can't read SOURCE\n"
            "or it has an invalid value, 2 on usage errors.",
            env=[ENV_CONFIG],
        ),
        formatter_class=HelpFormatter,
    )
    p_import.add_argument("source", metavar="SOURCE",
                          help="Config file, http(s) URL, or example config name (for example, miaa).")
    target = p_import.add_mutually_exclusive_group()
    target.add_argument("--scope", choices=SCOPES, default=None, help=SCOPE_HELP)
    target.add_argument("--config", default="", metavar="FILE",
                        help="Write to this config file instead of a scope.")
    p_import.add_argument("--overwrite", action="store_true",
                          help="Where a setting differs, take the value of SOURCE (default: keep yours).")
    p_import.add_argument("--dry-run", action="store_true",
                          help="Report what would change without writing anything.")

    subparsers.add_parser(
        "examples",
        help="List the shared example configs.",
        description="List the configs in examples/config/ of the BibCC repository (your checkout\n"
        "when BibCC runs from one, or else GitHub), ready for 'bibcc config import'.",
        epilog=epilog(examples=[("List the example configs", "bibcc config examples")]),
        formatter_class=HelpFormatter,
    )
    return parser


def main() -> None:
    """CLI entry point."""
    args = build_parser().parse_args()
    # These commands only print summaries, so no log file (and no .bibcc/ folder) is written.
    with Logger("config", enabled=False) as logger:
        if args.command == "where":
            status = where(args.path, logger.log)
        elif args.command == "init":
            status = init(args.scope, logger.log)
        elif args.command == "import":
            status = import_config(args.source, args.scope or USER_SCOPE, args.config or None,
                                   args.overwrite, args.dry_run, logger.log)
        else:
            status = examples(logger.log)
    sys.exit(status)


if __name__ == "__main__":
    main()
