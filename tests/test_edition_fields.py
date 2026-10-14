from pathlib import Path

import pytest

from bibcc.checkers.edition_fields import check_edition_fields
from bibcc.checkers.template_fields import check_template_fields
from bibcc.venues import VenueLibrary, family_key, family_label


def _icml(key: str, year: str, ordinal: str, *, day: bool = True, pages: bool = True, extra: str = "") -> str:
    return (
        f"@inproceedings{{{key},\n"
        f"  title = {{T {key}}},\n  author = {{Doe, Jane}},\n"
        f"  booktitle = {{Proceedings of the {ordinal} International Conference on Machine Learning}},\n"
        f"  year = {{{year}}},\n  series = {{PMLR}},\n  volume = {{1}},\n  citation = {{3}},\n"
        + ("  day = {1},\n" if day else "")
        + ("  pages = {1--2},\n" if pages else "")
        + extra
        + "}\n"
    )


def test_family_key_groups_editions_named_by_year_ordinal_or_article():
    assert family_key("Proceedings of the 41st International Conference on Machine Learning") == \
        family_key("Proceedings of the 36th International Conference on Machine Learning")
    assert family_key("The Eleventh International Conference on Learning Representations") == \
        family_key("International Conference on Learning Representations")
    assert family_key("Computer Vision -- ECCV 2024") == family_key("Computer Vision -- ECCV 2022")
    assert family_key("2025 IEEE/CVF Conference on Computer Vision and Pattern Recognition (CVPR)") != \
        family_key("2025 IEEE/CVF Conference on Computer Vision and Pattern Recognition Workshops (CVPRW)")
    assert family_label("Proceedings of the 41st International Conference on Machine Learning") == \
        "Proceedings of the International Conference on Machine Learning"
    assert family_label("The Thirty-ninth Annual Conference on Neural Information Processing Systems") == \
        "Annual Conference on Neural Information Processing Systems"


def test_check_venues_groups_ordinal_editions_and_skips_interim_records(tmp_path: Path):
    path = tmp_path / "venues.yaml"
    path.write_text(
        """\
proceedings:
- name: Proceedings of the 40th International Conference on Machine Learning
  year: '2023'
  fields: {publisher: PMLR, day: '23', venue: 'Honolulu, HI, USA'}
- name: Proceedings of the 41st International Conference on Machine Learning
  year: '2024'
  fields: {publisher: PMLR, venue: 'Vienna, Austria'}
- name: 2025 IEEE/CVF Conference on Computer Vision and Pattern Recognition (CVPR)
  year: '2025'
  fields: {publisher: IEEE, venue: 'Nashville, TN, USA'}
- name: Proceedings of the IEEE/CVF Conference on Computer Vision and Pattern Recognition (CVPR)
  year: '2026'
  fields: {month: June}
""",
        encoding="utf-8",
    )
    logs = []
    check_template_fields(path, [], [], log=logs.append)
    section = "\n".join(logs).split("Cross-edition consistency")[1]

    assert "Proceedings of the International Conference on Machine Learning: 'day' missing in 2024" in section
    # The interim CVPR 2026 record lacks publication fields by design; its event fields still count.
    assert "'publisher' missing in 2026" not in section
    assert "'venue' missing in 2026" in section
    assert "'month' missing in 2025" in section


def test_check_edition_fields_same_year_and_other_years(tmp_path: Path):
    bib = tmp_path / "refs.bib"
    bib.write_text(
        _icml("A_Doe_ICML2025", "2025", "42nd")
        + _icml("B_Doe_ICML2025", "2025", "42nd")
        + _icml("C_Doe_ICML2025", "2025", "42nd", pages=False)
        + _icml("D_Doe_ICML2026", "2026", "43rd", day=False),
        encoding="utf-8",
    )
    other = tmp_path / "bib"
    other.mkdir()
    (other / "old.bib").write_text(
        _icml("E_Doe_ICML2023", "2023", "40th", extra="  abstract = {Long.},\n")
        + _icml("F_Doe_ICML2024", "2024", "41st")
        # A copy of an input entry doesn't count twice.
        + _icml("C_Doe_ICML2025", "2025", "42nd", pages=False),
        encoding="utf-8",
    )

    rows = check_edition_fields(str(bib), against=[other], log=lambda _: None)

    assert [(r[0], r[2], r[3], r[4]) for r in rows] == [
        ("C_Doe_ICML2025", "2025", "pages", "same_year"),
        ("D_Doe_ICML2026", "2026", "day", "other_years"),
    ]
    assert rows[0][1] == "Proceedings of the International Conference on Machine Learning"
    assert rows[0][5] == "2 of 2 other 2025 entries have it"
    assert rows[1][5] == "3 of 3 other years have it (2023, 2024, 2025)"
    # citation (BibCC's own) is ignored by default, and one abstract isn't the venue's style.
    assert not any(r[3] in ("citation", "abstract") for r in rows)

    rows = check_edition_fields(
        str(bib), against=[other], ignore_fields=["pages", "day"], log=lambda _: None,
    )
    assert rows == []


def test_check_edition_fields_leaves_out_interim_and_metadata_entries(tmp_path: Path):
    library = VenueLibrary.loads(
        """\
proceedings:
- name: 2025 IEEE/CVF Conference on Computer Vision and Pattern Recognition (CVPR)
  year: '2025'
  interim:
    cvf: Proceedings of the Computer Vision and Pattern Recognition Conference (CVPR)
  fields: {publisher: IEEE, month: jun}
""")
    cvpr = "2025 IEEE/CVF Conference on Computer Vision and Pattern Recognition (CVPR)"
    interim = "Proceedings of the Computer Vision and Pattern Recognition Conference (CVPR)"
    entry = "@inproceedings{{{key}, title = {{T}}, booktitle = {{{venue}}}, year = {{2025}}{extra}}}\n"
    bib = tmp_path / "refs.bib"
    bib.write_text(
        entry.format(key="A", venue=cvpr, extra=", doi = {10.1/a}, publisher = {IEEE}")
        + entry.format(key="B", venue=cvpr, extra=", doi = {10.1/b}, publisher = {IEEE}")
        + entry.format(key="C", venue=cvpr, extra="")
        + entry.format(key="D", venue=interim, extra="")
        + "% BibCC: not the official BibTeX; it was built from metadata.\n"
        + entry.format(key="E", venue=cvpr, extra=""),
        encoding="utf-8",
    )

    rows = check_edition_fields(str(bib), library=library, log=lambda _: None)

    assert {(r[0], r[3]) for r in rows} == {("C", "doi"), ("C", "publisher")}
    hints = {r[3]: r[5] for r in rows}
    assert hints["publisher"].endswith("the library has it, so 'bibcc complete' adds it")
    assert "library" not in hints["doi"]


def test_check_editions_report_and_strict_counts_same_year_only(tmp_path: Path, capsys):
    from bibcc.cli import main

    bib = tmp_path / "refs.bib"
    bib.write_text(
        _icml("A_Doe_ICML2024", "2024", "41st") + _icml("B_Doe_ICML2025", "2025", "42nd")
        + _icml("C_Doe_ICML2026", "2026", "43rd", day=False),
        encoding="utf-8",
    )
    main(["check", "editions", str(bib), "--strict"])  # other_years only: exit status 0
    report = (tmp_path / ".bibcc" / "refs.bib" / "edition_fields.txt").read_text()
    assert "C_Doe_ICML2026\tProceedings of the International Conference on Machine Learning\t2026\tday\t" \
        "other_years\t2 of 2 other years have it (2024, 2025)" in report
    assert "the venue changed its BibTeX" in capsys.readouterr().out

    bib.write_text(
        bib.read_text() + _icml("D_Doe_ICML2026", "2026", "43rd") + _icml("E_Doe_ICML2026", "2026", "43rd"),
        encoding="utf-8",
    )
    with pytest.raises(SystemExit) as exc:
        main(["check", "editions", str(bib), "--strict"])
    assert exc.value.code == 1
    assert "C_Doe_ICML2026\tProceedings of the International Conference on Machine Learning\t2026\tday\t" \
        "same_year\t2 of 2 other 2026 entries have it" in report_text(tmp_path)

    bib.write_text(_icml("A_Doe_ICML2024", "2024", "41st"), encoding="utf-8")
    main(["check", "editions", str(bib), "--strict"])
    assert not (tmp_path / ".bibcc" / "refs.bib" / "edition_fields.txt").exists()


def report_text(tmp_path: Path) -> str:
    return (tmp_path / ".bibcc" / "refs.bib" / "edition_fields.txt").read_text()
