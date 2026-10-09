from pathlib import Path

import pytest
import yaml

from bibcc.completer import compute_completion
from bibcc.completer import main as complete_main
from bibcc.venues import (
    DEFAULT_LIBRARY_PATH,
    JOURNAL,
    PROCEEDINGS,
    Venue,
    VenueLibrary,
    merge_missing_venues,
    normalize_venue,
    previous_edition,
)


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


def test_bundled_library_loads():
    lib = VenueLibrary.load(DEFAULT_LIBRARY_PATH)
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
    assert result["incomplete"] == [("c", "", "2025")]


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
    missing_yaml = tmp_path / ".bibcc" / "new.bib.missing_venues.yaml"
    text = missing_yaml.read_text()
    assert "# from 2025 edition" in text
    assert "# from bib" in text

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
