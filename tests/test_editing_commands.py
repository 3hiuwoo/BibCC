from pathlib import Path

import pytest

from bibcc.cli import main
from bibcc.titlecases import check_title_case


def _strip_added(text: str, added: str) -> str:
    return text.replace(added, "", 1)


def test_complete_output_only_adds_fields(sample_bib: Path, tmp_path: Path, miaa_user_library):
    original = sample_bib.read_text()
    out = tmp_path / "out.bib"
    main(["complete", str(sample_bib), "--output", str(out)])
    result = out.read_text()

    # Fields land before the closing brace, aligned like the entry's own fields;
    # the CVPR family's fields come first.
    added_ispc = (
        ",\n  issn      = {2575-7075},\n  publisher = {IEEE},\n"
        "  venue     = {Seattle, WA, USA},\n  isbn      = {979-8-3503-5300-6},\n  month     = jun"
    )
    assert added_ispc in result
    # "publisher" is longer than DualPrompt's '=' column, so that entry's column widens.
    dual_before = original[original.index("  title   = {a study"): original.index("  month   = jun") + 15]
    dual_after = (
        "  title     = {a study of prompts\n             for continual learning},\n"
        "  author    = {Wang, Zifeng and Zhang, Zizhao},\n"
        "  journal   = {IEEE Transactions on Pattern Analysis and Machine Intelligence},\n"
        "  year      = {2024},\n  month     = jun,\n  issn      = {1939-3539},\n  publisher = {IEEE}"
    )
    assert dual_after in result
    assert _strip_added(result, added_ispc) == original.replace(dual_before, dual_after)
    assert sample_bib.read_text() == original


def test_complete_dry_run_writes_diff_but_not_the_bib(sample_bib: Path, miaa_user_library):
    original = sample_bib.read_text()
    main(["complete", str(sample_bib)])
    diff = (sample_bib.parent / ".bibcc" / "sample.bib" / "complete.diff").read_text()
    assert "+  publisher = {IEEE}" in diff
    assert sample_bib.read_text() == original


def test_complete_in_place(sample_bib: Path, miaa_user_library):
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


def test_title_case_report_keeps_multi_line_titles_on_one_line(sample_bib: Path):
    main(["check", "title", str(sample_bib)])
    report = (sample_bib.parent / ".bibcc" / "sample.bib" / "title_case.txt").read_text()
    assert (
        "DualPrompt_Wang_TPAMI2024\ta study of prompts for continual learning\t"
        "A Study of Prompts for Continual Learning\n"
    ) in report


RESOLVE_BIB = """\
@inproceedings{KeyA,
  title     = {Paper A},
  author    = {Doe, Jane},
  year      = {2024},
  booktitle = {2024 Conference on Examples (CE)},
  publisher = {Wrong Publisher}
}

@inproceedings{KeyB,
  title     = {Paper B},
  author    = {Roe, John},
  year      = {2024},
  booktitle = {2024 Conference on Examples (CE)},
  issn      = {0000-0000}
}
"""

RESOLVE_VENUES = """\
proceedings:
  - name: "2024 Conference on Examples (CE)"
    year: "2024"
    fields:
      publisher: "IEEE"
      issn: "1234-5678"
      month: "October"
"""


def _resolve_fixture(tmp_path: Path):
    bib = tmp_path / "refs.bib"
    bib.write_text(RESOLVE_BIB)
    venues = tmp_path / "venues.yaml"
    venues.write_text(RESOLVE_VENUES)
    return bib, venues


def test_complete_keep_mode_never_overwrites(tmp_path: Path):
    bib, venues = _resolve_fixture(tmp_path)
    out = tmp_path / "out.bib"
    main(["complete", str(bib), "--venues", str(venues), "--output", str(out)])
    result = out.read_text()
    assert "publisher = {Wrong Publisher}" in result
    assert "issn      = {0000-0000}" in result
    assert "month     = oct" in result  # missing fields are still added
    conflicts = (tmp_path / ".bibcc" / "refs.bib" / "conflicts.txt").read_text()
    assert "KeyA\tpublisher\tEXISTING=Wrong Publisher\tLIBRARY=IEEE" in conflicts
    assert "KeyB\tissn\tEXISTING=0000-0000\tLIBRARY=1234-5678" in conflicts


def test_complete_resolve_library_overwrites_conflicts(tmp_path: Path):
    bib, venues = _resolve_fixture(tmp_path)
    main(["complete", str(bib), "--venues", str(venues), "--in-place", "--resolve", "library"])
    result = bib.read_text()
    assert "publisher = {IEEE}" in result
    assert "issn      = {1234-5678}" in result
    assert "Wrong Publisher" not in result
    assert "0000-0000" not in result
    assert result.count("month     = oct") == 2


def test_complete_resolve_scoped_by_fields(tmp_path: Path):
    bib, venues = _resolve_fixture(tmp_path)
    main(["complete", str(bib), "--venues", str(venues), "--in-place",
          "--resolve", "library", "--fields", "issn"])
    result = bib.read_text()
    # Only issn may be written: KeyB's is overwritten, nothing else changes.
    assert "issn      = {1234-5678}" in result
    assert "publisher = {Wrong Publisher}" in result
    assert "month" not in result


def test_complete_resolve_scoped_by_ids(tmp_path: Path):
    bib, venues = _resolve_fixture(tmp_path)
    main(["complete", str(bib), "--venues", str(venues), "--in-place",
          "--resolve", "library", "--ids", "KeyB"])
    result = bib.read_text()
    # KeyA is out of scope: no overwrite, no added fields.
    assert "publisher = {Wrong Publisher}" in result
    key_a = result[: result.index("@inproceedings{KeyB")]
    assert "month" not in key_a
    assert "issn      = {1234-5678}" in result


def test_complete_ids_warns_about_unknown_keys(tmp_path: Path, capsys):
    bib, venues = _resolve_fixture(tmp_path)
    main(["complete", str(bib), "--venues", str(venues), "--ids", "KeyA,NoSuchKey"])
    assert "NoSuchKey" in capsys.readouterr().out


def test_complete_update_venues_only_merges_without_touching_the_bib(tmp_path: Path):
    bib, venues = _resolve_fixture(tmp_path)
    original = bib.read_text()
    yaml_dir = tmp_path / ".bibcc" / "refs.bib"
    yaml_dir.mkdir(parents=True)
    (yaml_dir / "missing_venues.yaml").write_text(
        """\
proceedings:
  - name: "2025 Conference on Examples (CE)"
    year: "2025"
    fields:
      publisher: "IEEE"
      month: "June"
"""
    )
    main(["complete", str(bib), "--venues", str(venues), "--update-venues-only"])
    assert "2025 Conference on Examples (CE)" in venues.read_text()
    assert bib.read_text() == original


def test_complete_update_venues_only_rejects_bib_options(tmp_path: Path):
    bib, venues = _resolve_fixture(tmp_path)
    for extra in (["--output", "x.bib"], ["--in-place"], ["--online"], ["--resolve", "library"]):
        with pytest.raises(SystemExit):
            main(["complete", str(bib), "--venues", str(venues), "--update-venues-only", *extra])


def test_scholar_cite_adds_empty_citation_fields_safely(sample_bib: Path, tmp_path: Path):
    from bibcc.utils.scholar import cmd_cite

    original = sample_bib.read_text()
    out = tmp_path / "cited.bib"
    cmd_cite(sample_bib, out, dry_run=False, log=lambda _: None)
    result = out.read_text()
    # "citation" is one character longer than DualPrompt's '=' column, which widens.
    dual_before = original[original.index("  title   = {a study"): original.index("  month   = jun") + 15]
    dual_after = (
        "  title    = {a study of prompts\n             for continual learning},\n"
        "  author   = {Wang, Zifeng and Zhang, Zizhao},\n"
        "  journal  = {IEEE Transactions on Pattern Analysis and Machine Intelligence},\n"
        "  year     = {2024},\n  month    = jun,\n  citation = {}"
    )
    assert result == original.replace(dual_before, dual_after)
