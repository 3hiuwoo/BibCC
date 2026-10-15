from pathlib import Path

import pytest
import yaml

from bibcc.cli import main
from bibcc.config import (
    OTHER_FIELDS,
    ConfigError,
    ConfigFile,
    load_config,
    merge,
    parse_field_order,
    user_config_path,
)
from bibcc.formatter import FormatOptions, format_text
from bibcc.utils.configlib import template

EXAMPLE_CONFIGS = Path(__file__).parent.parent / "examples" / "config"

MESSY = "@misc{k, citation = {3}, zeta = {z}, year = {2020}, title = {T}, author = {A}}\n"


def _names(text: str) -> list:
    return [line.split("=")[0].strip() for line in text.splitlines()[1:-1]]


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


# ------------------------------------------------------------ field order


def test_field_order_first_and_last_put_other_fields_between():
    order = parse_field_order({"first": ["title", "author"], "last": ["citation"]})
    assert order == ("title", "author", OTHER_FIELDS, "citation")
    out = format_text(MESSY, FormatOptions(sort_fields=True, field_order=order))
    assert _names(out) == ["title", "author", "zeta", "year", "citation"]


def test_field_order_list_form_and_trailing_slot():
    assert parse_field_order("Title, author, *, citation") == ("title", "author", "*", "citation")
    assert parse_field_order(["title", "*"]) == ("title",)
    assert parse_field_order({"first": ["title"]}) == ("title",)


@pytest.mark.parametrize("value", [
    ["title", "title"],
    ["*", "title", "*"],
    {"first": ["title"], "last": ["title"]},
    {"first": ["*"]},
    {"middle": ["x"]},
    "",
    3,
])
def test_invalid_field_orders_are_rejected(value):
    if value == "":
        assert parse_field_order(value) == ()
        return
    with pytest.raises(ConfigError):
        parse_field_order(value)


def test_from_settings_defaults_match_format_options():
    assert FormatOptions.from_settings({}) == FormatOptions()
    options = FormatOptions.from_settings({"indent": "tab", "align": False, "keep_quotes": True})
    assert (options.indent, options.align, options.braces) == ("\t", False, False)


# ---------------------------------------------------------------- loading


def test_project_config_wins_over_user_config(tmp_path: Path):
    _write(user_config_path(), "format:\n  indent: 4\n  sort_fields: true\n")
    _write(tmp_path / ".bibcc.yaml", "format:\n  indent: 3\n")
    config = load_config(start=tmp_path / "bib" / "refs.bib")
    assert config.section("format") == {"indent": 3, "sort_fields": True}
    assert config.origin("format", "indent") == "project"
    assert config.origin("format", "sort_fields") == "user"
    assert config.origin("format", "align") == "default"
    assert [f.scope for f in config.present] == ["user", "project"]


def test_unknown_keys_sections_and_fields_warn(tmp_path: Path):
    path = _write(tmp_path / "c.yaml",
                  "format:\n  sortfields: true\n  field_order: [title, volumn]\nvocab:\n  x: 1\n")
    config = load_config(path)
    text = "\n".join(config.warnings)
    assert "format.sortfields isn't a setting" in text
    assert "'volumn', which isn't a known field; did you mean 'volume'?" in text
    assert "doesn't read a vocab: section" in text
    assert config.section("format") == {"field_order": ("title", "volumn")}


@pytest.mark.parametrize("text", [
    "format:\n  indent: wide\n",
    "format:\n  sort_fields: yes please\n",
    "format:\n  blank_lines: -1\n",
    "format: [1, 2]\n",
    "- just a list\n",
    "format: {indent: 2\n",
])
def test_invalid_config_files_raise(tmp_path: Path, text):
    path = _write(tmp_path / "c.yaml", text)
    with pytest.raises(ConfigError):
        load_config(path)


def test_template_lists_every_setting_and_reads_as_empty():
    text = template()
    assert yaml.safe_load(text) == {"format": None}
    assert merge([ConfigFile("user", Path("t"), {"format": {}})]).warnings == []
    for key in ("sort_fields", "field_order", "indent", "drop_empty"):
        assert f"# {key}:" in text
    assert all(len(line) <= 92 for line in text.splitlines())


def test_miaa_example_reads_cleanly_and_keeps_citation_last():
    config = load_config(EXAMPLE_CONFIGS / "miaa.yaml")
    assert config.warnings == []
    format_settings = config.section("format")
    assert format_settings["sort_fields"] is True
    assert format_settings["field_order"][-2:] == (OTHER_FIELDS, "citation")


# ---------------------------------------------------------------- format


def test_format_reads_the_nearest_project_config_for_each_file(tmp_path: Path):
    _write(tmp_path / "a" / ".bibcc.yaml",
           "format:\n  sort_fields: true\n  field_order: {first: [title, author], last: [citation]}\n")
    _write(tmp_path / "b" / ".bibcc.yaml", "format:\n  indent: tab\n")
    a = _write(tmp_path / "a" / "bib" / "x.bib", MESSY)
    b = _write(tmp_path / "b" / "y.bib", MESSY)
    main(["format", str(a), str(b), "--in-place"])
    assert _names(a.read_text()) == ["title", "author", "zeta", "year", "citation"]
    assert b.read_text().splitlines()[1].startswith("\tcitation")


def test_command_line_options_win_over_the_config(tmp_path: Path):
    _write(tmp_path / ".bibcc.yaml", "format:\n  sort_fields: true\n  align: false\n")
    bib = _write(tmp_path / "x.bib", MESSY)
    main(["format", str(bib), "--in-place", "--no-sort-fields", "--align"])
    assert _names(bib.read_text())[0] == "citation"
    assert "  zeta     = {z}," in bib.read_text()


def test_no_config_and_config_file(tmp_path: Path):
    _write(tmp_path / ".bibcc.yaml", "format:\n  sort_fields: true\n")
    bib = _write(tmp_path / "x.bib", MESSY)
    main(["format", str(bib), "--in-place", "--no-config"])
    assert _names(bib.read_text())[0] == "citation"
    other = _write(tmp_path / "other.yaml", "format:\n  sort_fields: true\n  field_order: [year]\n")
    main(["format", str(bib), "--in-place", "--config", str(other)])
    assert _names(bib.read_text())[0] == "year"


def test_invalid_config_file_option_is_a_usage_error(tmp_path: Path):
    bib = _write(tmp_path / "x.bib", MESSY)
    bad = _write(tmp_path / "bad.yaml", "format:\n  indent: wide\n")
    with pytest.raises(SystemExit) as exc:
        main(["format", str(bib), "--config", str(bad)])
    assert exc.value.code == 2


def test_invalid_project_config_fails_its_files(tmp_path: Path, capsys):
    _write(tmp_path / ".bibcc.yaml", "format:\n  indent: wide\n")
    bib = _write(tmp_path / "x.bib", MESSY)
    with pytest.raises(SystemExit) as exc:
        main(["format", str(bib), "--in-place"])
    assert exc.value.code == 1
    assert bib.read_text() == MESSY
    assert "format.indent must be" in capsys.readouterr().out


def test_field_order_option_takes_the_slot(tmp_path: Path):
    bib = _write(tmp_path / "x.bib", MESSY)
    main(["format", str(bib), "--in-place", "--sort-fields", "--field-order", "title,*,citation"])
    assert _names(bib.read_text()) == ["title", "zeta", "year", "author", "citation"]


# --------------------------------------------------------- config command


def _run(argv) -> int:
    with pytest.raises(SystemExit) as exc:
        main(argv)
    return exc.value.code


def test_config_import_init_and_where(tmp_path: Path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    project = tmp_path / ".bibcc.yaml"
    assert _run(["config", "import", "miaa", "--scope", "project", "--dry-run"]) == 0
    assert not project.exists()

    assert _run(["config", "import", "miaa", "--scope", "project"]) == 0
    assert load_config(project).section("format")["sort_fields"] is True

    mine = _write(tmp_path / "mine.yaml", "format:\n  indent: 4\n")
    _run(["config", "import", str(mine), "--scope", "project"])
    assert "kept 2 (incoming 4)" in capsys.readouterr().out
    assert load_config(project).section("format")["indent"] == 2
    _run(["config", "import", str(mine), "--scope", "project", "--overwrite"])
    assert load_config(project).section("format")["indent"] == 4

    assert _run(["config", "init"]) == 0
    assert user_config_path().read_text() == template()

    capsys.readouterr()
    assert _run(["config", "where", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "indent             4  [project]" in out
    assert "trailing_comma     false  [project]" in out


def test_config_import_rejects_invalid_source(tmp_path: Path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    bad = _write(tmp_path / "bad.yaml", "format:\n  indent: wide\n")
    assert _run(["config", "import", str(bad)]) == 1
    assert not user_config_path().exists()


def test_config_import_keeps_the_target_comments(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    target = tmp_path / "lab.yaml"
    original = (EXAMPLE_CONFIGS / "miaa.yaml").read_text()
    target.write_text(original)
    mine = _write(tmp_path / "mine.yaml", "format:\n  indent: 4\n  field_order: [title, '*', citation]\n")
    assert _run(["config", "import", str(mine), "--config", str(target), "--overwrite"]) == 0

    text = target.read_text()
    assert text.startswith("# MIAA lab config")
    assert "  # Publisher extras keep their place" in text
    changed = [line for line in text.splitlines() if line not in original.splitlines()]
    assert changed == ["  field_order: [title, '*', citation]", "  indent: 4"]
    assert load_config(target).section("format")["field_order"] == ("title", OTHER_FIELDS, "citation")


def test_config_import_fills_the_settings_that_init_commented_out(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert _run(["config", "init"]) == 0
    assert _run(["config", "import", "miaa"]) == 0
    text = user_config_path().read_text()
    assert "# Field indent: a number of spaces, or tab.\n  indent: 2\n" in text
    assert "  # indent:" not in text and "  #   first:" not in text
    assert load_config(user_config_path()).section("format")["sort_fields"] is True


def test_update_yaml_keeps_comments_and_adds_what_is_missing():
    from bibcc.config import update_yaml

    text = "# mine\nformat:\n  indent: 2  # two spaces\n  # keep this\n  align: true\n"
    data = {"format": {"indent": 4, "align": True, "drop_empty": True}, "other": {"key": 1}}
    edited = update_yaml(text, data)
    assert edited == ("# mine\nformat:\n  indent: 4  # two spaces\n  # keep this\n  align: true\n"
                      "  drop_empty: true\n\nother:\n  key: 1\n")


def test_update_yaml_rewrites_a_layout_it_cannot_edit_under_its_own_header():
    from bibcc.config import parse_yaml, update_yaml

    edited = update_yaml("# mine\nformat: {indent: 2}\n", {"format": {"indent": 4}})
    assert edited.startswith("# mine\n")
    assert parse_yaml(edited, "x") == {"format": {"indent": 4}}


def test_config_examples_lists_miaa(capsys):
    assert _run(["config", "examples"]) == 0
    assert "miaa  format (12 settings)" in capsys.readouterr().out


def test_config_profile_imports_config_venues_and_terms(tmp_path: Path, monkeypatch, capsys):
    from bibcc.terms import read_terms
    from bibcc.venues import VenueLibrary

    monkeypatch.chdir(tmp_path)
    assert _run(["config", "profile", "miaa", "--scope", "project", "--dry-run"]) == 0
    assert not list(tmp_path.glob(".bibcc*"))

    assert _run(["config", "profile", "miaa", "--scope", "project"]) == 0
    assert load_config(tmp_path / ".bibcc.yaml").section("format")["sort_fields"] is True
    assert VenueLibrary.load(tmp_path / ".bibcc-venues.yaml").families
    assert "CLIP" in read_terms(tmp_path / ".bibcc-terms.txt")

    (tmp_path / "bib").mkdir()
    capsys.readouterr()
    assert _run(["config", "where", str(tmp_path / "bib")]) == 0
    out = capsys.readouterr().out
    assert "📂 Other files that apply:" in out
    journals = len(VenueLibrary.load(tmp_path / ".bibcc-venues.yaml").journals)
    assert f"project  {(tmp_path / '.bibcc-venues.yaml').resolve()} ({journals} journals" in out
    assert f"project  {(tmp_path / '.bibcc-terms.txt').resolve()} (" in out
    assert "provider table" in out and "bibcc venues providers" in out


def test_config_profile_unknown_name(tmp_path: Path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    assert _run(["config", "profile", "no-such-lab"]) == 1
    assert "No shared config, venue library, or terms file is named no-such-lab" in capsys.readouterr().out
