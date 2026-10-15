"""Machine-readable dump of the BibCC command surface.

``bibcc surface`` prints a JSON document describing the commands, their
options, the report files BibCC writes, and the status, ``next``, and
``issue_type`` words its reports use. Tools and agent skills that track BibCC, such as a skill that
detects when a release changes a command or an option, read this document
instead of scraping the help pages.
"""

from __future__ import annotations

import argparse
import importlib
import json
from typing import Any, Dict, List

from bibcc import __version__
from bibcc.adder import STATUSES as ADD_STATUSES
from bibcc.checker import CHECK_NAMES
from bibcc.checkers.edition_fields import FIELD_STATUSES
from bibcc.checkers.official_fields import (
    DIFFERS,
    LOCAL_ONLY,
    TYPE,
    UPSTREAM_ONLY,
    VENUE_STATUSES,
)
from bibcc.cli import _MAIN_TOOLS, _RUN_TOOLS, TOOLS
from bibcc.helptext import DOCS_URL, REPO, HelpFormatter, epilog
from bibcc.logging_utils import REPORT_KINDS, TOOL_NAMES
from bibcc.official import NEXT_VALUES
from bibcc.schemas import SCHEMA_STATUSES
from bibcc.upgrader import PUBLISHED_STATUSES


def _default(action: argparse.Action) -> Any:
    """A JSON-safe form of an option's default value."""
    value = action.default
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, (list, tuple)):
        return [str(v) for v in value]
    return str(value)


def _options(parser: argparse.ArgumentParser) -> List[Dict[str, Any]]:
    """Every option and positional of *parser*, in help order."""
    options: List[Dict[str, Any]] = []
    for action in parser._actions:  # argparse exposes no public API for this
        if isinstance(action, argparse._SubParsersAction):
            continue
        if action.dest == argparse.SUPPRESS:
            continue
        options.append({
            "flags": list(action.option_strings),
            "dest": action.dest,
            "metavar": action.metavar,
            "help": (action.help or "").strip(),
            "default": _default(action),
            "required": bool(getattr(action, "required", False)),
            "choices": [str(c) for c in action.choices] if isinstance(action.choices, (list, tuple)) else None,
            "multiple": isinstance(action, argparse._AppendAction),
        })
    return options


def _subcommands(parser: argparse.ArgumentParser) -> List[Dict[str, Any]]:
    """The subcommands of *parser*, with their summary and options."""
    subs: List[Dict[str, Any]] = []
    for action in parser._actions:
        if not isinstance(action, argparse._SubParsersAction):
            continue
        summaries = {a.dest: (a.help or "").strip() for a in action._choices_actions}
        for name, sub in action.choices.items():
            subs.append({"name": name, "summary": summaries.get(name, ""), "options": _options(sub)})
    return subs


def _command(name: str) -> Dict[str, Any]:
    """One command's surface entry."""
    module = _RUN_TOOLS.get(name) or _MAIN_TOOLS[name]
    parser = importlib.import_module(module).build_parser()
    return {
        "name": name,
        "summary": TOOLS[name],
        "description": (parser.description or "").strip(),
        "options": _options(parser),
        "subcommands": _subcommands(parser),
    }


def surface() -> Dict[str, Any]:
    """The whole command surface as a plain dict, ready for ``json.dumps``."""
    return {
        "bibcc": __version__,
        "repository": REPO,
        "docs": DOCS_URL,
        "commands": [_command(name) for name in TOOLS],
        "reports": list(REPORT_KINDS),
        "tools": list(TOOL_NAMES),
        "status": {
            "next": list(NEXT_VALUES),
            "add": list(ADD_STATUSES),
            "check": list(CHECK_NAMES),
            "published": list(PUBLISHED_STATUSES),
        },
        # The issue_type words of the check reports, by report file.
        "issues": {
            "edition_fields.txt": list(FIELD_STATUSES),
            "edition_schemas.txt": list(SCHEMA_STATUSES),
            "official_fields.txt": [UPSTREAM_ONLY, DIFFERS, LOCAL_ONLY, TYPE],
            "official_venues.txt": list(VENUE_STATUSES),
        },
    }


DESCRIPTION = """\
Print the machine-readable command surface as JSON: every command and its
options, the report files BibCC writes, and the status, next, and issue_type
words its reports use. Tools and agent skills that track BibCC read this
document to detect when a release changes a command or an option.
"""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="bibcc surface",
        description=DESCRIPTION,
        epilog=epilog(
            examples=[
                ("Print the command surface as JSON", "bibcc surface"),
                ("Read only the running version", "bibcc surface | jq .bibcc"),
            ],
            notes="The output is stable JSON. Read the field you need instead of parsing "
                  "the help pages. The bibcc field names the running release.",
        ),
        formatter_class=HelpFormatter,
    )
    parser.add_argument(
        "--format", choices=("json", "text"), default="json",
        help="Output format: 'json' (default), or a short human-readable 'text' listing.",
    )
    return parser


def _text(data: Dict[str, Any]) -> str:
    lines = [f"bibcc {data['bibcc']}", "", "commands:"]
    for command in data["commands"]:
        lines.append(f"  {command['name']:<10} {command['summary']}")
        for sub in command["subcommands"]:
            lines.append(f"      {sub['name']:<8} {sub['summary']}")
    lines += ["", "reports: " + ", ".join(data["reports"]), "", "status:"]
    for kind, words in data["status"].items():
        lines.append(f"  {kind:<10} {', '.join(words)}")
    lines += ["", "issues:"]
    for report, words in data["issues"].items():
        lines.append(f"  {report:<20} {', '.join(words)}")
    return "\n".join(lines)


def main() -> None:
    """Print the command surface."""
    args = build_parser().parse_args()
    data = surface()
    print(_text(data) if args.format == "text" else json.dumps(data, indent=2, ensure_ascii=False))
