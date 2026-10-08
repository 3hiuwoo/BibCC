from pathlib import Path

import pytest

from bibcc.cli import main
from bibcc.titlecases import check_title_case


def _strip_added(text: str, added: str) -> str:
    return text.replace(added, "", 1)


def test_complete_output_only_adds_fields(sample_bib: Path, tmp_path: Path):
    original = sample_bib.read_text()
    out = tmp_path / "out.bib"
    main(["complete", str(sample_bib), "--output", str(out)])
    result = out.read_text()

    # Fields land before the closing brace, aligned like the entry's own fields.
    added_ispc = (
        ",\n  venue     = {Seattle, WA, USA},\n  issn      = {2575-7075},\n"
        "  isbn      = {979-8-3503-5300-6},\n  publisher = {IEEE},\n  month     = {June}"
    )
    added_dual = ",\n  issn    = {1939-3539},\n  publisher = {IEEE}"
    assert added_ispc in result
    assert added_dual in result
    assert _strip_added(_strip_added(result, added_ispc), added_dual) == original
    assert sample_bib.read_text() == original


def test_complete_dry_run_writes_diff_but_not_the_bib(sample_bib: Path):
    original = sample_bib.read_text()
    main(["complete", str(sample_bib)])
    diff = (sample_bib.parent / ".bibcc" / "sample.bib.complete.diff").read_text()
    assert "+  publisher = {IEEE}" in diff
    assert sample_bib.read_text() == original


def test_complete_in_place(sample_bib: Path):
    main(["complete", str(sample_bib), "--in-place"])
    assert "publisher = {IEEE}" in sample_bib.read_text()


def test_complete_refuses_output_and_in_place(sample_bib: Path):
    with pytest.raises(SystemExit):
        main(["complete", str(sample_bib), "--in-place", "--output", "x.bib"])


def test_title_apply_rewrites_only_title_values(sample_bib: Path):
    original = sample_bib.read_text()
    changed = check_title_case(str(sample_bib), apply=True, log=lambda _: None)
    result = sample_bib.read_text()
    assert [c[0] for c in changed] == ["DualPrompt_Wang_TPAMI2024", "PANDA_Raghavan_arXiv2025"]
    # The multi-line title is replaced as a whole; nothing else moves.
    assert "title   = {A Study of Prompts for Continual Learning}," in result
    restored = result.replace(
        "{A Study of Prompts for Continual Learning}",
        "{a study of prompts\n             for continual learning}",
    ).replace("Patch and Distribution-Aware", "Patch And Distribution-Aware")
    assert restored == original


def test_scholar_cite_adds_empty_citation_fields_safely(sample_bib: Path, tmp_path: Path):
    from bibcc.utils.scholar import cmd_cite

    original = sample_bib.read_text()
    out = tmp_path / "cited.bib"
    cmd_cite(sample_bib, out, dry_run=False, log=lambda _: None)
    result = out.read_text()
    assert "  month   = jun,\n  citation = {}\n}" in result
    assert result.replace(",\n  citation = {}", "", 1) == original
