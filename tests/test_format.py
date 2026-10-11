from pathlib import Path

import pytest

from bibcc import formatter
from bibcc.bibedit import BibEditError
from bibcc.cli import main
from bibcc.formatter import FormatOptions, format_bib, format_text

SURVEY_STYLE = (
    "@inproceedings{GKEAL_Zhuang_CVPR2023,\n"
    "  title     = {{GKEAL}: {Gaussian} Kernel Embedded Analytic Learning},\n"
    "  author    = {Zhuang, Huiping and Weng, Zhenyu},\n"
    "  year      = {2023},\n"
    "  month     = jun,\n"
    "  booktitle = {2023 {IEEE/CVF} Conference on Computer Vision and Pattern Recognition ({CVPR})},\n"
    "  citation  = {115}\n"
    "}\n"
    "\n"
    "% TODO: check pages\n"
    "@article{B_Doe_TPAMI2024,\n"
    "  title   = {A Study\n"
    "             over Two Lines},\n"
    "  journal = {{IEEE} Transactions on Pattern Analysis and Machine Intelligence},\n"
    "  year    = {2024}\n"
    "}\n"
)

MESSY = (
    "\n\n@ARTICLE{k2,\n"
    '    Title = "A {B} c",\n'
    "  YEAR=2024,\n"
    "  month = {June},\n"
    "  note = {},\n"
    "  journal = {J},\n"
    "}\n\n\n\n"
    "@Misc{k1, title = {T}, month = \"6\", howpublished = pre # {fix}}"
)


def test_survey_style_is_unchanged():
    assert format_text(SURVEY_STYLE) == SURVEY_STYLE


def test_messy_entries_are_normalised():
    assert format_text(MESSY) == (
        "@article{k2,\n"
        "  title   = {A {B} c},\n"
        "  year    = {2024},\n"
        "  month   = jun,\n"
        "  note    = {},\n"
        "  journal = {J}\n"
        "}\n"
        "\n"
        "@misc{k1,\n"
        "  title        = {T},\n"
        "  month        = jun,\n"
        "  howpublished = pre # {fix}\n"
        "}\n"
    )


def test_formatting_is_idempotent():
    once = format_text(MESSY, FormatOptions(sort_fields=True, sort_entries=True))
    assert format_text(once, FormatOptions(sort_fields=True, sort_entries=True)) == once


def test_keep_quotes_and_months():
    out = format_text(MESSY, FormatOptions(braces=False, months=False))
    assert '  title   = "A {B} c",\n' in out
    assert "  year    = 2024,\n" in out
    assert "  month   = {June},\n" in out


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("{{Whole Title}}", "{Whole Title}"),
        ("{{{Whole Title}}}", "{Whole Title}"),
        ('"{Whole Title}"', "{Whole Title}"),
        ("{ {Whole Title} }", "{Whole Title}"),
        ("{{GKEAL}: Kernel}", "{{GKEAL}: Kernel}"),
        ("{{A} and {B}}", "{{A} and {B}}"),
        ('{{\\"O}}', '{{\\"O}}'),
    ],
)
def test_redundant_outer_braces_are_stripped(raw, expected):
    out = format_text(f"@misc{{k, title = {raw}}}\n")
    assert f"title = {expected}\n" in out


def test_name_lists_and_keep_outer_braces_keep_double_braces():
    text = "@misc{k, author = {{World Health Organization}}, title = {{T}}}\n"
    assert "author = {{World Health Organization}}," in format_text(text)
    assert "title  = {{T}}\n" in format_text(text, FormatOptions(outer_braces=False))


def test_outer_braces_around_months_and_pages():
    out = format_text("@misc{k, month = {{June}}, pages = {{12-15}}}\n")
    assert "month = jun," in out
    assert "pages = {12--15}\n" in out


def test_missing_commas_are_added():
    text = "@article{k\n  title = {T}\n  year = 2024\n  journal = {J}\n}\n"
    assert format_text(text) == (
        "@article{k,\n  title   = {T},\n  year    = {2024},\n  journal = {J}\n}\n"
    )


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("{12-15}", "{12--15}"),
        ('"12 – 15"', "{12--15}"),
        ("{S1-S9, 20-22}", "{S1--S9, 20--22}"),
        ("{12--15}", "{12--15}"),
        ("{e1234}", "{e1234}"),
        ("{12---15}", "{12---15}"),
    ],
)
def test_page_ranges_use_double_hyphens(raw, expected):
    out = format_text(f"@misc{{k, pages = {raw}}}\n")
    assert f"pages = {expected}\n" in out


def test_keep_pages():
    out = format_text("@misc{k, pages = {12-15}}\n", FormatOptions(pages=False))
    assert "pages = {12-15}" in out


def test_unrecognised_month_is_left_alone():
    out = format_text("@misc{k, month = {Summer}}\n")
    assert "month = {Summer}" in out


def test_no_align_indent_and_trailing_comma():
    out = format_text(
        "@misc{k, title = {T}, publisher = {P}}\n",
        FormatOptions(align=False, indent="\t", trailing_comma=True),
    )
    assert out == "@misc{k,\n\ttitle = {T},\n\tpublisher = {P},\n}\n"


def test_sort_fields_puts_unknown_fields_last_in_source_order():
    text = "@misc{k, citation = {3}, year = {2020}, zeta = {z}, title = {T}, author = {A}}\n"
    out = format_text(text, FormatOptions(sort_fields=True))
    names = [line.split("=")[0].strip() for line in out.splitlines()[1:-1]]
    assert names == ["title", "author", "year", "citation", "zeta"]


def test_custom_field_order():
    text = "@misc{k, title = {T}, year = {2020}, author = {A}}\n"
    out = format_text(text, FormatOptions(sort_fields=True, field_order=("year", "author")))
    names = [line.split("=")[0].strip() for line in out.splitlines()[1:-1]]
    assert names == ["year", "author", "title"]


def test_sort_entries_carries_comments_and_keeps_strings_on_top():
    text = (
        "@string{tpami = {IEEE TPAMI}}\n\n"
        "% about b\n"
        "@article{b, journal = tpami, year = {2020}}\n\n"
        "% about a\n"
        "@article{a, title = {A}}\n"
    )
    out = format_text(text, FormatOptions(sort_entries=True))
    assert out.startswith("@string{tpami = {IEEE TPAMI}}\n\n% about a\n@article{a,")
    assert out.index("% about b\n@article{b,") > out.index("@article{a,")
    assert "journal = tpami" in out


def test_comment_blocks_and_blank_lines_are_preserved():
    text = "@comment{ keep me }\n\n\n@misc{k, title = {T}}\n"
    out = format_text(text, FormatOptions(blank_lines=2))
    assert out == "@comment{ keep me }\n\n\n@misc{k,\n  title = {T}\n}\n"


def test_drop_empty_removes_empty_fields():
    out = format_text("@misc{k, title = {T}, note = {}, doi = \"\"}\n", FormatOptions(drop_empty=True))
    assert out == "@misc{k,\n  title = {T}\n}\n"


def test_crlf_is_kept():
    out = format_text("@misc{k, title = {T}}\r\n")
    assert out == "@misc{k,\r\n  title = {T}\r\n}\r\n"


def test_duplicate_keys_are_rejected():
    with pytest.raises(BibEditError, match="duplicate citation key 'k'"):
        format_bib("@misc{k, title={a}}\n@misc{k, title={b}}\n")


def test_verification_failure_raises(monkeypatch):
    monkeypatch.setattr(formatter, "_convert", lambda name, raw, options: "{changed}")
    with pytest.raises(BibEditError, match="changed field"):
        format_bib("@misc{k, title = {T}}\n")


def test_describe_reports_spacing_only_changes():
    result = format_bib("@misc{k,\n  title = {T}\n}")
    assert result.text.endswith("}\n")
    assert result.changed == []
    assert "spacing between entries only" in result.describe()


# -------------------------------------------------------------------- CLI


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def test_cli_dry_run_writes_diff_only(tmp_path: Path):
    bib = _write(tmp_path / "refs.bib", MESSY)
    main(["format", str(bib)])
    assert bib.read_text() == MESSY
    diff = (tmp_path / ".bibcc" / "refs.bib.format.diff").read_text()
    assert "+  month   = jun," in diff


def test_cli_in_place_and_output(tmp_path: Path):
    bib = _write(tmp_path / "refs.bib", MESSY)
    out = tmp_path / "out.bib"
    main(["format", str(bib), "--output", str(out)])
    assert bib.read_text() == MESSY
    assert out.read_text() == format_text(MESSY)
    main(["format", str(bib), "--in-place"])
    assert bib.read_text() == format_text(MESSY)


def test_cli_check_exit_codes(tmp_path: Path):
    bib = _write(tmp_path / "refs.bib", MESSY)
    with pytest.raises(SystemExit) as exc:
        main(["format", str(bib), "--check"])
    assert exc.value.code == 1
    assert bib.read_text() == MESSY
    assert not (tmp_path / ".bibcc").exists()
    bib.write_text(format_text(MESSY))
    main(["format", str(bib), "--check"])


def test_cli_directory_input_skips_output_dir(tmp_path: Path):
    a = _write(tmp_path / "bib" / "a.bib", MESSY)
    b = _write(tmp_path / "bib" / "sub" / "b.bib", SURVEY_STYLE)
    _write(tmp_path / "bib" / ".bibcc" / "stale.bib", "@misc{")
    main(["format", str(tmp_path / "bib"), "--in-place"])
    assert a.read_text() == format_text(MESSY)
    assert b.read_text() == SURVEY_STYLE


def test_cli_bad_file_is_skipped_and_fails(tmp_path: Path):
    good = _write(tmp_path / "good.bib", MESSY)
    _write(tmp_path / "bad.bib", "@misc{k, title = {unclosed}\n")
    with pytest.raises(SystemExit) as exc:
        main(["format", str(tmp_path), "--in-place"])
    assert exc.value.code == 1
    assert good.read_text() == format_text(MESSY)


def test_cli_output_requires_single_file(tmp_path: Path):
    _write(tmp_path / "a.bib", MESSY)
    with pytest.raises(SystemExit):
        main(["format", str(tmp_path), "--output", str(tmp_path / "o.bib")])


def test_empty_entries_from_add_are_kept():
    text = (
        "% BibCC: no official BibTeX could be downloaded; paste it into the entry below, keeping the key.\n"
        "%   title:  T\n"
        "@inproceedings{Empty_Doe_AAAI2025,\n}\n\n"
        "@article{A,\ntitle={T},\n  year = 2024}\n"
    )
    out = format_text(text)
    assert "@inproceedings{Empty_Doe_AAAI2025,\n}\n" in out
    assert "  title = {T},\n  year  = {2024}\n" in out
