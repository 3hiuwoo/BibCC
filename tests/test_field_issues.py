from pathlib import Path

import pytest

from bibcc.checkers.field_issues import check_field_issues, suggest_field, value_issues
from bibcc.cli import main


def _quiet(_msg: str) -> None:
    pass


def _check(tmp_path: Path, text: str, **kwargs):
    bib = tmp_path / "refs.bib"
    bib.write_text(text, encoding="utf-8")
    return check_field_issues(str(bib), log=_quiet, **kwargs)


def test_suggest_field_finds_typos():
    assert suggest_field("volumn") == "volume"
    assert suggest_field("pubisher") == "publisher"
    assert suggest_field("booktile") == "booktitle"
    assert suggest_field("zzzz") is None


@pytest.mark.parametrize(
    "name, raw, kind",
    [
        ("year", "{2024}", None),
        ("year", "{24}", "bad_year"),
        ("pages", "{12--15}", None),
        ("pages", "{12-15}", "page_range"),
        ("pages", "{e1234}", None),
        ("doi", "{10.1109/CVPR.2024.001}", None),
        ("doi", "{https://doi.org/10.1109/CVPR.2024.001}", "doi_format"),
        ("doi", "{CVPR.2024}", "doi_format"),
        ("month", "jun", None),
        ("month", "{June}", "month_format"),
        ("month", "{Summer}", "month_format"),
        ("issn", "{0031-3203}", None),
        ("issn", "{1939-3539, 0162-8828}", None),
        ("issn", "{00313203}", "issn_format"),
        ("url", "{https://x.org}", None),
        ("url", "{www.x.org}", "url_format"),
        ("note", "{}", "empty_value"),
        ("note", "{a} # {b}", None),
        ("pages", 'pre # "1-2"', None),
    ],
)
def test_value_issues(name, raw, kind):
    kinds = [k for k, _ in value_issues(name, raw)]
    assert kinds == ([kind] if kind else [])


def test_page_range_detail_shows_fix():
    assert value_issues("pages", "{12-15}") == [("page_range", "'12-15' → '12--15'")]


def test_unknown_fields_and_extra_fields(tmp_path: Path):
    text = "@article{k, title = {T}, volumn = {3}, citation = {5}, code = {x}}\n"
    rows = _check(tmp_path, text)
    assert ("k", "unknown_field", "'volumn' → did you mean 'volume'?") in rows
    assert ("k", "unknown_field", "'code' is not a known field") in rows
    assert not any("citation" in d for _, _, d in rows)
    rows = _check(tmp_path, text, extra_fields=["code"])
    assert not any("'code'" in d for _, _, d in rows)


def test_duplicates_within_file(tmp_path: Path):
    text = (
        "@article{A, title = {Same Paper}, doi = {10.1109/TPAMI.2021.1}}\n"
        "@article{B, title = {Other}, doi = {10.1109/tpami.2021.1}}\n"
        "@misc{C, title = {Same  paper.}}\n"
        "@misc{A, title = {Third}}\n"
    )
    rows = _check(tmp_path, text)
    dups = [(k, kind) for k, kind, _ in rows if kind.startswith("duplicate")]
    assert ("B", "duplicate_paper") in dups
    assert ("C", "duplicate_paper") in dups
    assert ("A", "duplicate_key") in dups


def test_duplicates_against_other_files(tmp_path: Path):
    other = tmp_path / "bib" / "other.bib"
    other.parent.mkdir()
    other.write_text("@misc{Old, title = {X}, eprint = {2501.13198}, archiveprefix = {arXiv}}\n")
    rows = _check(tmp_path, "@misc{New, title = {Y}, eprint = {2501.13198}, archiveprefix = {arXiv}}\n",
                  against=[tmp_path / "bib"])
    assert rows == [("New", "duplicate_paper", f"same arXiv ID 2501.13198 as Old ({other})")]


def test_duplicate_key_names_where_it_is_used(tmp_path: Path):
    other = tmp_path / "bib" / "other.bib"
    other.parent.mkdir()
    other.write_text("@misc{K, title = {X}}\n")
    rows = _check(tmp_path, "@misc{K, title = {Y}}\n@misc{L, title = {Z}}\n@misc{L, title = {W}}\n",
                  against=[tmp_path / "bib"])
    assert ("K", "duplicate_key", f"citation key is already used ({other})") in rows
    assert ("L", "duplicate_key", "citation key is already used (this file)") in rows


def test_input_inside_against_dir_is_not_its_own_duplicate(tmp_path: Path):
    bib = tmp_path / "refs.bib"
    bib.write_text("@misc{K, title = {T}}\n")
    assert check_field_issues(str(bib), against=[tmp_path], log=_quiet) == []


def test_syntax_error_is_reported(tmp_path: Path):
    rows = _check(tmp_path, "@misc{k, title = {T}, title = {U}}\n")
    assert rows[0][:2] == ("(file)", "syntax")


def test_cli_writes_report(tmp_path: Path):
    bib = tmp_path / "refs.bib"
    bib.write_text("@article{k, title = {T}, volumn = {3}, pages = {1-2}}\n")
    main(["check", str(bib), "--check-fields"])
    report = (tmp_path / ".bibcc" / "refs.bib.field_issues.txt").read_text()
    assert "k\tunknown_field\t'volumn' → did you mean 'volume'?" in report
    assert "k\tpage_range\t'1-2' → '1--2'" in report
    assert bib.read_text() == "@article{k, title = {T}, volumn = {3}, pages = {1-2}}\n"
