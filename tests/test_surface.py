import json

import pytest

from bibcc import __version__
from bibcc.cli import TOOLS, main
from bibcc.logging_utils import REPORT_KINDS
from bibcc.surface import surface


def test_surface_lists_every_command():
    data = surface()
    assert [c["name"] for c in data["commands"]] == list(TOOLS)


def test_surface_reports_version_reports_and_status():
    data = surface()
    assert data["bibcc"] == __version__
    assert data["reports"] == list(REPORT_KINDS)
    assert set(data["status"]) == {"next", "add", "check", "published"}
    assert "by hand" in data["status"]["next"]
    assert "official" in data["status"]["add"]
    assert data["issues"]["edition_fields.txt"] == ["missing", "default_missing"]
    assert {"schema_lacks", "export_lacks", "books_lack"} <= set(data["issues"]["official_venues.txt"])


def test_surface_check_subcommands_and_options():
    check = next(c for c in surface()["commands"] if c["name"] == "check")
    assert {s["name"] for s in check["subcommands"]} == {
        "missing", "title", "quote", "keys", "fields", "editions", "official", "venues"}
    add = next(c for c in surface()["commands"] if c["name"] == "add")
    flags = {f for o in add["options"] for f in o["flags"]}
    assert "--against" in flags and "--output" in flags


def test_surface_prints_json(capsys):
    main(["surface"])
    data = json.loads(capsys.readouterr().out)
    assert data["bibcc"] == __version__
    assert any(c["name"] == "surface" for c in data["commands"])


def test_surface_text_format(capsys):
    main(["surface", "--format", "text"])
    out = capsys.readouterr().out
    assert "commands:" in out and "reports:" in out and "status:" in out


def test_surface_help_runs(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["surface", "-h"])
    assert exc.value.code == 0
    assert "examples:" in capsys.readouterr().out
