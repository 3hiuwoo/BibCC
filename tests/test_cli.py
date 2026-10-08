import pytest

from bibcc import __version__
from bibcc.cli import TOOLS, main


def test_usage_lists_every_tool(capsys):
    with pytest.raises(SystemExit) as exc:
        main([])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    for tool in TOOLS:
        assert tool in out


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
