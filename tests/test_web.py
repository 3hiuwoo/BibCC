"""The web workbench's command catalog stays in step with the CLI."""

import re
from pathlib import Path

from bibcc.surface import surface

COMMANDS_JS = Path(__file__).resolve().parent.parent / "web" / "commands.js"


def _flags_by_path():
    flags = {}

    def walk(command, path):
        here = [*path, command["name"]]
        flags[" ".join(here)] = {f for o in command.get("options", []) for f in o["flags"]}
        for sub in command.get("subcommands") or []:
            walk(sub, here)

    for command in surface()["commands"]:
        walk(command, [])
    return flags


def test_web_catalog_uses_only_real_commands_and_flags():
    flags = _flags_by_path()
    text = COMMANDS_JS.read_text(encoding="utf-8")
    blocks = re.findall(r'argv: \[([^\]]*)\],(.*?)\n  \},', text, re.S)
    assert blocks, "no commands found in web/commands.js"
    for argv_text, body in blocks:
        argv = [a.strip().strip('"') for a in argv_text.split(",")]
        path = " ".join(a for a in argv if not a.startswith("-") and not a.endswith(".bib"))
        if not path:  # --version
            continue
        assert path in flags, f"web/commands.js runs unknown command {path!r}"
        used = set(re.findall(r'(?:flag|neg): "([^"]+)"', body))
        assert used <= flags[path], f"{path}: unknown flags {sorted(used - flags[path])}"
