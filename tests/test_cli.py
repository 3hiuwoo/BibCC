import argparse
import importlib

import pytest

from bibcc import __version__
from bibcc.cli import _MAIN_TOOLS, _RUN_TOOLS, TOOLS, main
from bibcc.helptext import DOCS_URL


def _parsers():
    """(name, parser) for every command and subcommand."""
    for tool, module in sorted({**_RUN_TOOLS, **_MAIN_TOOLS}.items()):
        parser = importlib.import_module(module).build_parser()
        yield tool, parser
        for action in parser._actions:
            if isinstance(action, argparse._SubParsersAction):
                for name, sub in action.choices.items():
                    yield f"{tool} {name}", sub


PARSERS = list(_parsers())


def test_usage_lists_every_tool(capsys):
    with pytest.raises(SystemExit) as exc:
        main([])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    for tool in TOOLS:
        assert tool in out


def test_usage_explains_conventions_and_environment(capsys):
    with pytest.raises(SystemExit):
        main(["--help"])
    out = capsys.readouterr().out
    for text in ("--in-place", ".bibcc/", "examples:", "BIBCC_VENUES", "S2_API_KEY", DOCS_URL):
        assert text in out


@pytest.mark.parametrize("name,parser", PARSERS, ids=[name for name, _ in PARSERS])
def test_help_is_self_contained(name, parser):
    text = parser.format_help()
    assert parser.description, f"{name} has no description"
    assert "examples:\n" in text and f"bibcc {name}" in text, f"{name} has no examples"
    assert DOCS_URL in text
    for action in parser._actions:
        if not isinstance(action, argparse._SubParsersAction):
            assert action.help, f"{name}: {action.option_strings or action.dest} has no help"


@pytest.mark.parametrize(
    "argv", [["librarian", "missing", "-h"], ["scholar", "titles", "-h"], ["compose", "compose", "-h"]]
)
def test_subcommand_help_runs(argv, capsys):
    with pytest.raises(SystemExit) as exc:
        main(argv)
    assert exc.value.code == 0
    assert "examples:" in capsys.readouterr().out


def test_version(capsys):
    with pytest.raises(SystemExit):
        main(["--version"])
    assert __version__ in capsys.readouterr().out


def test_unknown_tool_exits_nonzero(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["nope"])
    assert exc.value.code == 1


@pytest.mark.parametrize("tool", sorted(TOOLS))
def test_every_tool_has_help(tool, capsys):
    with pytest.raises(SystemExit) as exc:
        main([tool, "-h"])
    assert exc.value.code == 0
    assert "usage" in capsys.readouterr().out.lower()
