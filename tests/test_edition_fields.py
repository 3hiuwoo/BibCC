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


ICML_FAMILY = """\
families:
- name: International Conference on Machine Learning
  acronym: ICML
  entry_fields: [day, pages, volume]
  learned_from: official BibTeX of 2 entries (2025), 2025-07-01
"""


def test_check_edition_fields_reports_fields_of_the_schema(tmp_path: Path):
    library = VenueLibrary.loads(ICML_FAMILY + """\
proceedings:
- name: Proceedings of the 43rd International Conference on Machine Learning
  year: '2026'
  fields: {publisher: PMLR}
  entry_fields: [pages, volume]
""")
    bib = tmp_path / "refs.bib"
    bib.write_text(
        _icml("A_Doe_ICML2025", "2025", "42nd")
        + _icml("C_Doe_ICML2025", "2025", "42nd", pages=False)
        # 2026 has its own schema, without day.
        + _icml("D_Doe_ICML2026", "2026", "43rd", day=False)
        + _icml("E_Doe_ICML2026", "2026", "43rd", pages=False),
        encoding="utf-8",
    )

    result = check_edition_fields(str(bib), library, log=lambda _: None)

    assert [(r[0], r[2], r[3], r[4]) for r in result.fields] == [
        ("C_Doe_ICML2025", "2025", "pages", "missing"),
        ("E_Doe_ICML2026", "2026", "pages", "missing"),
    ]
    assert result.fields[0][5] == (
        "in the schema of family International Conference on Machine Learning (ICML), "
        "learned from official BibTeX of 2 entries (2025), 2025-07-01"
    )
    assert result.fields[1][5].startswith("in the schema of Proceedings of the 43rd International")
    assert result.checked == 4 and not result.schemas

    result = check_edition_fields(str(bib), library, ignore_fields=["pages"], log=lambda _: None)
    assert result.fields == []


def test_check_edition_fields_proposes_schemas_from_peers_and_learns_them(tmp_path: Path):
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
        _icml("E_Doe_ICML2025", "2025", "42nd", extra="  abstract = {Long.},\n")
        # A copy of an input entry doesn't count twice.
        + _icml("C_Doe_ICML2025", "2025", "42nd", pages=False),
        encoding="utf-8",
    )

    # Without a schema, the comparison only proposes one.
    result = check_edition_fields(str(bib), VenueLibrary(), against=[other], log=lambda _: None)
    assert result.fields == []
    assert result.unschematized == {"Proceedings of the International Conference on Machine Learning": [
        "A_Doe_ICML2025", "B_Doe_ICML2025", "C_Doe_ICML2025", "D_Doe_ICML2026"]}
    (row,) = result.schemas
    assert row[:6] == ("Proceedings of the International Conference on Machine Learning", "", "family",
                       "schema_lacks", "4", "day, pages, volume")
    assert row[6].endswith("; lacking: C_Doe_ICML2025 (pages)")
    # 2026 has one entry, too few to propose its own schema; one abstract isn't the venue's.

    target = VenueLibrary(path=tmp_path / "venues.yaml")
    result = check_edition_fields(str(bib), VenueLibrary(), against=[other], learn=target, log=lambda _: None)
    assert result.learned == 1
    (family,) = target.families
    assert family.acronym == "ICML"
    assert family.entry_fields == ["day", "pages", "volume"]
    assert family.learned_from.startswith("peer comparison of 4 entries (2025), ")
    assert [(r[0], r[3]) for r in result.fields] == [("C_Doe_ICML2025", "pages"), ("D_Doe_ICML2026", "day")]


def test_check_edition_fields_skips_issue_fields_of_articles_not_in_an_issue(tmp_path: Path):
    library = VenueLibrary.loads("""\
journals:
- name: Pattern Recognition
  fields: {publisher: Elsevier}
  entry_fields: [doi, number, pages, volume]
""")
    bib = tmp_path / "refs.bib"
    bib.write_text(
        "@article{A, title = {T}, journal = {Pattern Recognition}, year = {2025}, volume = {1}, doi = {10.1/a}}\n"
        "@article{B, title = {T}, journal = {Pattern Recognition}, year = {2025}}\n",
        encoding="utf-8",
    )

    result = check_edition_fields(str(bib), library, log=lambda _: None)

    assert [(r[0], r[3]) for r in result.fields] == [("A", "number"), ("A", "pages"), ("B", "doi")]


def test_check_edition_fields_leaves_out_interim_and_metadata_entries(tmp_path: Path):
    library = VenueLibrary.loads(
        """\
proceedings:
- name: 2025 IEEE/CVF Conference on Computer Vision and Pattern Recognition (CVPR)
  year: '2025'
  interim:
    cvf: Proceedings of the Computer Vision and Pattern Recognition Conference (CVPR)
  fields: {publisher: IEEE, month: jun}
  entry_fields: [doi]
""")
    cvpr = "2025 IEEE/CVF Conference on Computer Vision and Pattern Recognition (CVPR)"
    interim = "Proceedings of the Computer Vision and Pattern Recognition Conference (CVPR)"
    entry = "@inproceedings{{{key}, title = {{T}}, booktitle = {{{venue}}}, year = {{2025}}{extra}}}\n"
    bib = tmp_path / "refs.bib"
    bib.write_text(
        entry.format(key="A", venue=cvpr, extra=", doi = {10.1/a}, publisher = {IEEE}")
        + entry.format(key="C", venue=cvpr, extra="")
        + entry.format(key="D", venue=interim, extra="")
        + "% BibCC: not the official BibTeX; it was built from metadata.\n"
        + entry.format(key="E", venue=cvpr, extra=""),
        encoding="utf-8",
    )

    result = check_edition_fields(str(bib), library, log=lambda _: None)

    assert [(r[0], r[3]) for r in result.fields] == [("C", "doi")]


def test_check_editions_reports_learn_and_strict(tmp_path: Path):
    from bibcc.cli import main

    venues = tmp_path / "venues.yaml"
    bib = tmp_path / "refs.bib"
    bib.write_text(
        _icml("A_Doe_ICML2025", "2025", "42nd") + _icml("B_Doe_ICML2025", "2025", "42nd")
        + _icml("C_Doe_ICML2025", "2025", "42nd", day=False),
        encoding="utf-8",
    )
    reports = tmp_path / ".bibcc" / "refs.bib"
    # Proposals alone don't count as findings.
    main(["check", "editions", str(bib), "--strict", "--venues", str(venues)])
    assert not (reports / "edition_fields.txt").exists()
    assert "\tfamily\tschema_lacks\t3\tpages, volume\t" in (reports / "edition_schemas.txt").read_text()

    venues.write_text(ICML_FAMILY, encoding="utf-8")
    with pytest.raises(SystemExit) as exc:
        main(["check", "editions", str(bib), "--strict", "--venues", str(venues)])
    assert exc.value.code == 1
    assert "C_Doe_ICML2025\tProceedings of the 42nd International Conference on Machine Learning\t2025\tday\t" \
        "missing\tin the schema of family" in (reports / "edition_fields.txt").read_text()
    assert not (reports / "edition_schemas.txt").exists()

    venues.unlink()
    main(["check", "editions", str(bib), "--learn", "--venues", str(venues)])
    assert "entry_fields:\n  - pages\n  - volume\n" in venues.read_text()
