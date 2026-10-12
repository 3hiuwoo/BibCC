from pathlib import Path
from typing import List

import pytest
import yaml

from bibcc.completer import compute_completion, same_field_value
from bibcc.completer import main as complete_main
from bibcc.venues import (
    JOURNAL,
    PROCEEDINGS,
    Venue,
    VenueLibrary,
    merge_missing_venues,
    normalize_venue,
    previous_edition,
)
from conftest import MIAA_VENUES


@pytest.fixture
def library(tmp_path: Path) -> VenueLibrary:
    lib = VenueLibrary(path=tmp_path / "venues.yaml")
    lib.upsert(
        Venue(
            JOURNAL,
            "Information Processing \\& Management",
            {"publisher": "Elsevier", "issn": "0306-4573"},
            aliases=["Inf. Process. Manag."],
        )
    )
    lib.upsert(
        Venue(
            PROCEEDINGS,
            "2025 IEEE/CVF Conference on Computer Vision and Pattern Recognition (CVPR)",
            {"publisher": "IEEE", "issn": "2575-7075", "month": "June", "venue": "Nashville, TN, USA"},
            year="2025",
        )
    )
    return lib


def test_miaa_example_library_loads():
    lib = VenueLibrary.load(MIAA_VENUES)
    assert len(lib.journals) >= 30
    assert len(lib.proceedings) >= 70
    eccv = lib.find_exact(PROCEEDINGS, "Computer Vision -- ECCV 2024", "2025")
    assert eccv is not None and eccv.fields["series"] == "Lecture Notes in Computer Science"


def test_normalize_venue_ignores_braces_escapes_case_and_spacing():
    assert normalize_venue("{IEEE}  Trans. \\& {X}") == normalize_venue("ieee trans. & x")


def test_journal_lookup_by_name_alias_and_issn(library: VenueLibrary):
    assert library.lookup("Information Processing & Management", "2024", JOURNAL).venue
    assert library.lookup("Inf. Process. Manag.", "2024", JOURNAL).venue
    assert library.lookup("Some Other Spelling", "2024", JOURNAL, issn="0306 4573").venue
    assert library.lookup("Unknown Journal", "2024", JOURNAL).venue is None


def test_proceedings_lookup_requires_year(library: VenueLibrary):
    name = "2025 {IEEE/CVF} Conference on Computer Vision and Pattern Recognition ({CVPR})"
    assert library.lookup(name, "2025", PROCEEDINGS).venue
    assert library.lookup(name, "2026", PROCEEDINGS).venue is None


def test_ambiguous_matches_choose_nothing(library: VenueLibrary):
    library.upsert(Venue(JOURNAL, "Other Journal", {"issn": "0306-4573"}))
    result = library.lookup("Other Journal", "2024", JOURNAL, issn="0306-4573")
    assert result.venue is None
    assert len(result.ambiguous) == 2


def test_save_and_load_round_trip(library: VenueLibrary):
    library.save()
    again = VenueLibrary.load(library.path)
    j = again.find_exact(JOURNAL, "Information Processing \\& Management")
    assert j.aliases == ["Inf. Process. Manag."]
    assert j.fields == {"publisher": "Elsevier", "issn": "0306-4573"}
    assert again.proceedings[0].year == "2025"


def test_proceedings_without_year_is_rejected(tmp_path: Path):
    path = tmp_path / "bad.yaml"
    path.write_text("proceedings:\n  - name: X\n    fields: {a: b}\n")
    with pytest.raises(ValueError, match="needs a 'year'"):
        VenueLibrary.load(path)


def test_previous_edition_links_conference_years(library: VenueLibrary):
    prior = previous_edition(
        library,
        "2026 IEEE/CVF Conference on Computer Vision and Pattern Recognition (CVPR)",
        "2026",
    )
    assert prior is not None and prior.year == "2025"


def test_compute_completion_adds_missing_and_reports_conflicts(library: VenueLibrary):
    entries = [
        {
            "ID": "a",
            "ENTRYTYPE": "inproceedings",
            "year": "2025",
            "booktitle": "2025 IEEE/CVF Conference on Computer Vision and Pattern Recognition (CVPR)",
            "month": "July",
        },
        {"ID": "b", "ENTRYTYPE": "article", "year": "2024", "journal": "Brand New Journal"},
        {"ID": "c", "ENTRYTYPE": "misc", "year": "2025"},
    ]
    result = compute_completion(entries, library)
    assert result["patches"]["a"] == {
        "publisher": "IEEE",
        "issn": "2575-7075",
        "venue": "Nashville, TN, USA",
    }
    assert result["conflicts"]["a"] == [("month", "July", "June")]
    assert list(result["missing"].values()) == [("Brand New Journal", "2024", JOURNAL)]
    assert result["incomplete"] == [("c", "", "2025", "misc")]


def test_compute_completion_tracks_where_collected_values_come_from(library: VenueLibrary):
    entries = [
        {"ID": "p1", "ENTRYTYPE": "article", "year": "2024", "journal": "New Journal",
         "publisher": "Elsevier"},
        {"ID": "p2", "ENTRYTYPE": "article", "year": "2025", "journal": "New Journal",
         "publisher": "Elsevier", "issn": "1234-5678"},
        {"ID": "p3", "ENTRYTYPE": "article", "year": "2024", "journal": "New Journal",
         "publisher": "Wiley"},
    ]
    result = compute_completion(entries, library)
    (key,) = result["collected"]
    assert result["collected"][key]["publisher"] == "Elsevier"  # the majority value
    assert result["collected_from"][key]["publisher"] == ["p1", "p2"]
    assert result["collected_from"][key]["issn"] == ["p2"]


def test_complete_separates_misc_from_entries_to_fix(tmp_path: Path, library: VenueLibrary):
    bib = tmp_path / "refs.bib"
    bib.write_text(
        "@inproceedings{A_Doe_Unknown2025,\n"
        "  title = {T}, author = {Doe, J}, year = {2025},\n"
        "  booktitle = {Unknown Conference 2025}, publisher = {ACM}\n"
        "}\n"
        "@inproceedings{NoVenue_Doe_2025,\n"
        "  title = {T}, author = {Doe, J}, year = {2025}\n"
        "}\n"
        "@misc{ArXiv_Doe_2024,\n"
        "  title = {T}, author = {Doe, J}, year = {2024}, eprint = {2401.00001}\n"
        "}\n"
    )
    lines: List[str] = []
    complete_main(str(bib), str(bib), dry_run=True, library=library, log=lines.append)
    out = "\n".join(lines)
    assert "not completed" in out and "NoVenue_Doe_2025 (@inproceedings)" in out
    assert "Skipped 1 misc entry (no venue expected): ArXiv_Doe_2024" in out
    assert "publisher (from A_Doe_Unknown2025)" in out
    report = (tmp_path / ".bibcc" / "refs.bib" / "incomplete_entries.txt").read_text()
    assert "entry_id\ttype\tvenue\tyear" in report
    assert "ArXiv_Doe_2024\tmisc" in report


def test_compute_completion_treats_equivalent_months_as_equal(library: VenueLibrary):
    entry = {
        "ID": "a",
        "ENTRYTYPE": "inproceedings",
        "year": "2025",
        "booktitle": "2025 IEEE/CVF Conference on Computer Vision and Pattern Recognition (CVPR)",
        "month": "6",
    }
    result = compute_completion([entry], library)
    assert "a" not in result["conflicts"]


@pytest.mark.parametrize(
    "name, existing, value",
    [
        ("editor", "Che, Wanxiang  and Nabende,\n   Joyce", "Che, Wanxiang and Nabende, Joyce"),
        ("venue", 'Stockholmsm\\"{a}ssan, Stockholm, Sweden', "Stockholmsmässan, Stockholm, Sweden"),
        ("venue", "Montr{\\'e}al, {QC}, Canada", "Montréal, QC, Canada"),
        ("isbn", "979-8-4007-0686-8", "9798400706868"),
        ("issn", "2575 7075", "2575-7075"),
        ("publisher", "Taylor \\& Francis", "Taylor & Francis"),
    ],
)
def test_same_field_value_ignores_formatting(name, existing, value):
    assert same_field_value(name, existing, value)


@pytest.mark.parametrize(
    "name, existing, value",
    [
        ("venue", "Long Beach, California, USA", "Long Beach, CA, USA"),
        ("isbn", "978-1-57735-866-4", "978-1-57735-887-9"),
        ("month", "July", "June"),
    ],
)
def test_same_field_value_keeps_real_differences(name, existing, value):
    assert not same_field_value(name, existing, value)


def test_miaa_aaai_2021_record_is_not_icml_2018():
    lib = VenueLibrary.load(MIAA_VENUES)
    aaai = lib.find_exact(PROCEEDINGS, "Proceedings of the AAAI Conference on Artificial Intelligence", "2021")
    assert aaai.fields["venue"] == "Online"
    assert "series" not in aaai.fields
    assert aaai.fields["month"] == "May"  # publication month, like the other AAAI records


def test_missing_venues_yaml_round_trips_into_library(tmp_path: Path, library: VenueLibrary):
    bib = tmp_path / "new.bib"
    bib.write_text(
        "@inproceedings{X_Doe_CVPR2026,\n"
        "  title = {T}, author = {Doe, J}, year = {2026},\n"
        "  booktitle = {2026 IEEE/CVF Conference on Computer Vision and Pattern Recognition (CVPR)}\n"
        "}\n"
        "@article{Y_Doe_PR2026,\n"
        '  title = {T}, author = {Doe, J}, year = {2026}, journal = {Journal of "Quoted" Things},\n'
        "  publisher = {Elsevier}\n"
        "}\n"
    )
    complete_main(str(bib), str(bib), dry_run=True, library=library, log=lambda _: None)
    missing_yaml = tmp_path / ".bibcc" / "new.bib" / "missing_venues.yaml"
    text = missing_yaml.read_text()
    assert "# from 2025 edition" in text
    assert "# from bib" in text
    # The comment names the entry the collected value comes from.
    assert 'publisher: "Elsevier"  # from bib (Y_Doe_PR2026)' in text

    data = yaml.safe_load(text)
    proc = data["proceedings"][0]
    assert proc["year"] == "2026"
    assert proc["fields"]["publisher"] == "IEEE"
    assert proc["fields"]["issn"] == "2575-7075"
    assert proc["fields"]["month"] == "June"
    assert data["journals"][0]["name"] == 'Journal of "Quoted" Things'

    counts = merge_missing_venues(library, missing_yaml, log=lambda _: None)
    assert counts["added"] == 2
    assert library.lookup(
        "2026 IEEE/CVF Conference on Computer Vision and Pattern Recognition (CVPR)",
        "2026",
        PROCEEDINGS,
    ).venue


def test_merge_skips_records_without_fields(tmp_path: Path, library: VenueLibrary):
    path = tmp_path / "m.yaml"
    path.write_text('journals:\n  - name: "Empty"\n    fields:\n      issn: ""\n')
    counts = merge_missing_venues(library, path, log=lambda _: None)
    assert counts == {"added": 0, "updated": 0, "unchanged": 0, "skipped": 1}


# ------------------------------------------------------- interim booktitles

CVF_NAME = "Proceedings of the IEEE/CVF Conference on Computer Vision and Pattern Recognition (CVPR)"
XPLORE_NAME = "2025 IEEE/CVF Conference on Computer Vision and Pattern Recognition (CVPR)"


def test_interim_lookup_names_the_source(library: VenueLibrary):
    record = library.find_exact(PROCEEDINGS, XPLORE_NAME, "2025")
    assert record.add_interim("cvf", CVF_NAME)
    assert not record.add_interim("cvf", CVF_NAME.upper())  # already known
    result = library.lookup("Proceedings of the {IEEE/CVF} Conference on Computer Vision and Pattern "
                            "Recognition ({CVPR})", "2025", PROCEEDINGS)
    assert result.venue is record and result.interim_source == "cvf"
    assert library.lookup(XPLORE_NAME, "2025", PROCEEDINGS).interim_source is None
    assert library.lookup(CVF_NAME, "2024", PROCEEDINGS).venue is None


def test_interim_round_trips_as_string_or_list(tmp_path: Path):
    path = tmp_path / "v.yaml"
    path.write_text(
        "proceedings:\n"
        f"  - name: {XPLORE_NAME!r}\n"
        "    year: 2025\n"
        "    interim:\n"
        f"      CVF: [{CVF_NAME!r}, 'Proceedings of the Computer Vision and Pattern Recognition Conference (CVPR)']\n"
        "      openreview: Some OpenReview Name\n"
        "    fields: {month: June}\n"
    )
    lib = VenueLibrary.load(path)
    venue = lib.proceedings[0]
    assert venue.interim["cvf"][0] == CVF_NAME and len(venue.interim["cvf"]) == 2  # source lower-cased
    lib.save()
    data = yaml.safe_load(path.read_text())["proceedings"][0]
    assert data["interim"]["openreview"] == "Some OpenReview Name"
    assert len(data["interim"]["cvf"]) == 2


def test_upsert_renames_record_stored_under_interim_name(tmp_path: Path):
    lib = VenueLibrary(path=tmp_path / "v.yaml")
    lib.upsert(Venue(PROCEEDINGS, CVF_NAME, {"month": "June"}, year="2026"))
    published = Venue(PROCEEDINGS, XPLORE_NAME.replace("2025", "2026"), {"publisher": "IEEE"}, year="2026",
                      interim={"cvf": [CVF_NAME]})
    assert lib.upsert(published) == "updated"
    (record,) = lib.proceedings
    assert record.name == published.name
    assert record.fields == {"month": "June", "publisher": "IEEE"}
    assert record.interim == {"cvf": [CVF_NAME]} and record.aliases == []


def test_upsert_of_other_name_adds_alias(library: VenueLibrary):
    assert library.upsert(Venue(PROCEEDINGS, "CVPR 2025", {}, year="2025",
                                aliases=[XPLORE_NAME])) == "updated"
    record = library.find_exact(PROCEEDINGS, XPLORE_NAME, "2025")
    assert record.aliases == ["CVPR 2025"]


def test_complete_gives_interim_entries_only_event_fields(tmp_path: Path, library: VenueLibrary):
    library.find_exact(PROCEEDINGS, XPLORE_NAME, "2025").add_interim("cvf", CVF_NAME)
    bib = tmp_path / "refs.bib"
    bib.write_text(
        "@inproceedings{A_B_CVPR2025,\n  title = {T},\n  author = {B, A},\n"
        f"  booktitle = {{{CVF_NAME}}},\n  year = {{2025}},\n  month = {{July}}\n}}\n"
    )
    lines = []
    complete_main(str(bib), str(bib), library=library, log=lines.append)
    text = bib.read_text()
    assert "venue = {Nashville, TN, USA}" in text.replace("  ", " ")
    assert "publisher" not in text and "issn" not in text
    conflicts = (tmp_path / ".bibcc" / "refs.bib" / "conflicts.txt").read_text()
    assert "A_B_CVPR2025\tmonth\tEXISTING=July\tLIBRARY=June" in conflicts
    assert f"A_B_CVPR2025\tbooktitle\tEXISTING={CVF_NAME}\tLIBRARY={XPLORE_NAME}" in conflicts
    assert any("Interim booktitles" in line for line in lines)


def test_complete_reports_conflicts_in_dry_run(tmp_path: Path, library: VenueLibrary):
    bib = tmp_path / "refs.bib"
    bib.write_text(f"@inproceedings{{A,\n  booktitle = {{{XPLORE_NAME}}},\n  year = {{2025}},\n"
                   "  publisher = {Someone}\n}\n")
    lines = []
    complete_main(str(bib), str(bib), dry_run=True, library=library, log=lines.append)
    assert any("existing='Someone', library='IEEE'" in line for line in lines)
    assert "A\tpublisher\tEXISTING=Someone" in (tmp_path / ".bibcc" / "refs.bib" / "conflicts.txt").read_text()


# ------------------------------------------------------ missing-venues YAML


def test_missing_venues_file_is_merged_not_overwritten(tmp_path: Path, library: VenueLibrary):
    from bibcc.missing_venues import MissingVenue, write_missing_venues

    path = tmp_path / "m.yaml"
    first = MissingVenue(JOURNAL, "Journal One", collected={"publisher": "Elsevier"})
    assert write_missing_venues(path, [first], library, "rerun")["new"] == 1
    # The user fills in a field by hand.
    path.write_text(path.read_text().replace('issn: ""', 'issn: "1234-5678"'))

    second = MissingVenue(JOURNAL, "Journal Two")
    counts = write_missing_venues(path, [first, second], library, "rerun")
    assert counts == {"new": 1, "kept": 1, "dropped": 0}
    text = path.read_text()
    assert '"1234-5678"' in text and "Journal Two" in text
    assert text.count("Journal One") == 1

    # Once the library has the venue, its block is dropped.
    merge_missing_venues(library, path, log=lambda _: None)
    counts = write_missing_venues(path, [], library, "rerun")
    assert counts["dropped"] == 1
    assert "Journal One" not in path.read_text()


def test_missing_venues_link_only_record_merges_interim_name(tmp_path: Path, library: VenueLibrary):
    from bibcc.missing_venues import MissingVenue, write_missing_venues

    path = tmp_path / "m.yaml"
    link = MissingVenue(PROCEEDINGS, XPLORE_NAME, "2025", interim={"cvf": [CVF_NAME]},
                        notes=["links an interim booktitle"], link_only=True)
    write_missing_venues(path, [link], library, "rerun")
    assert "fields: {}" in path.read_text()
    counts = merge_missing_venues(library, path, log=lambda _: None)
    assert counts["updated"] == 1
    record = library.find_exact(PROCEEDINGS, XPLORE_NAME, "2025")
    assert record.interim == {"cvf": [CVF_NAME]}
    assert record.fields["publisher"] == "IEEE"  # unchanged
    assert write_missing_venues(path, [], library, "rerun")["dropped"] == 1


def test_miaa_library_links_interim_names():
    lib = VenueLibrary.load(MIAA_VENUES)
    for name, year in [
        ("Proceedings of the Computer Vision and Pattern Recognition Conference (CVPR)", "2025"),
        ("Proceedings of the IEEE/CVF Conference on Computer Vision and Pattern Recognition (CVPR)", "2024"),
        ("The Thirteenth International Conference on Learning Representations", "2025"),
        ("Forty-first International Conference on Machine Learning", "2024"),
    ]:
        result = lib.lookup(name, year, PROCEEDINGS)
        assert result.venue is not None and result.interim_source, name
