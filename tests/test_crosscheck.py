import json
from pathlib import Path

import pytest
import yaml

from bibcc import sources
from bibcc.completer import main as complete_main
from bibcc.crosscheck import check_entry, same_value, venue_fields_from_crossref
from bibcc.venues import JOURNAL, PROCEEDINGS, Venue, VenueLibrary
from test_add import FakeWeb, _fixture

XPLORE_NAME = "2025 IEEE/CVF Conference on Computer Vision and Pattern Recognition (CVPR)"


@pytest.fixture
def web(monkeypatch):
    fake = FakeWeb({
        "api.crossref.org/works/10.1109/CVPR52734.2025.02829": (_fixture("crossref_cvpr2025.json"), None),
        "api.crossref.org/works/10.1109/TPAMI.2024.3429383": (_fixture("crossref_tpami.json"), None),
    })
    monkeypatch.setattr(sources, "fetch_url", fake)
    return fake


@pytest.fixture
def library(tmp_path: Path) -> VenueLibrary:
    lib = VenueLibrary(path=tmp_path / "venues.yaml")
    lib.upsert(Venue(PROCEEDINGS, XPLORE_NAME, {"publisher": "IEEE", "issn": "1111-1111", "month": "June"},
                     year="2025"))
    return lib


def _cvpr_record():
    return sources.record_from_crossref(json.loads(_fixture("crossref_cvpr2025.json"))["message"])


def test_same_value_rules():
    assert same_value("issn", "1939-3539", ["0162-8828", "1939 3539"])
    assert same_value("pages", "30387--30397", ["30387-30397"])
    assert same_value("publisher", "IEEE", ["IEEE"])
    assert same_value("booktitle", "2025 {IEEE/CVF} Conference on Computer Vision and Pattern Recognition ({CVPR})",
                      [XPLORE_NAME])
    assert not same_value("volume", "45", ["46"])
    assert same_value("month", "jun", ["June"])


def test_check_entry_tells_who_differs(library):
    record = _cvpr_record()
    entry = {"ENTRYTYPE": "inproceedings", "booktitle": XPLORE_NAME, "year": "2025", "pages": "1--2"}
    venue = library.proceedings[0]
    checks = {c.name: c for c in check_entry("K", entry, PROCEEDINGS, venue, record)}
    assert checks["pages"].verdict == "bib differs"
    assert checks["booktitle"].verdict == "ok"
    assert checks["month"].verdict == "ok"
    venue.fields["venue"] = "Seattle, WA, USA"
    checks = {c.name: c for c in check_entry("K", entry, PROCEEDINGS, venue, record)}
    assert checks["venue"].verdict == "library differs"
    assert checks["venue"].crossref == "Nashville, TN, USA"


def test_venue_fields_from_crossref():
    fields = venue_fields_from_crossref(_cvpr_record(), PROCEEDINGS)
    assert fields.get("publisher") == "IEEE"
    tpami = sources.record_from_crossref(json.loads(_fixture("crossref_tpami.json"))["message"])
    assert venue_fields_from_crossref(tpami, JOURNAL)["issn"] == "0162-8828"


def test_complete_online_reports_and_fills_yaml(web, library, tmp_path):
    bib = tmp_path / "refs.bib"
    bib.write_text(
        "@inproceedings{Unified_Kumar_CVPR2025,\n"
        "  title = {A Unified, Resilient, and Explainable Adversarial Patch Detector},\n"
        f"  booktitle = {{{XPLORE_NAME}}},\n  year = {{2025}},\n  pages = {{1--2}},\n"
        "  doi = {10.1109/CVPR52734.2025.02829}\n}\n"
        "@article{ClassIncremental_Zhou_TPAMI2024,\n  title = {Class-Incremental Learning: A Survey},\n"
        "  journal = {IEEE Transactions on Pattern Analysis and Machine Intelligence},\n  year = {2024},\n"
        "  doi = {10.1109/TPAMI.2024.3429383}\n}\n"
        "@inproceedings{NoDoi_X_ICML2024,\n  title = {T},\n  booktitle = {Some Workshop},\n  year = {2024}\n}\n"
    )
    original = bib.read_text()
    complete_main(str(bib), str(bib), dry_run=True, library=library, log=lambda _: None, online=True, delay=0)
    assert bib.read_text() == original

    check = (tmp_path / ".bibcc" / "refs.bib.venue_check.txt").read_text()
    assert "Unified_Kumar_CVPR2025\tpages\tbib differs" in check
    assert "NoDoi_X_ICML2024\t(not checked)\tno DOI" in check

    yaml_text = (tmp_path / ".bibcc" / "refs.bib.missing_venues.yaml").read_text()
    assert "# from CrossRef" in yaml_text
    data = yaml.safe_load(yaml_text)
    tpami = next(j for j in data["journals"] if j["name"].startswith("IEEE Transactions on Pattern"))
    assert tpami["fields"]["issn"]
    calls = [c for c in web.calls if "api.crossref.org" in c]
    assert len(calls) == 2  # one request per DOI


def test_complete_online_suggests_library_corrections(web, library, tmp_path):
    library.proceedings[0].fields["venue"] = "Seattle, WA, USA"
    bib = tmp_path / "refs.bib"
    bib.write_text(f"@inproceedings{{A,\n  booktitle = {{{XPLORE_NAME}}},\n  year = {{2025}},\n"
                   "  doi = {10.1109/CVPR52734.2025.02829}\n}\n")
    complete_main(str(bib), str(bib), dry_run=True, library=library, log=lambda _: None, online=True, delay=0)
    text = (tmp_path / ".bibcc" / "refs.bib.missing_venues.yaml").read_text()
    assert "# ---- Suggested corrections to library records" in text
    assert '#      venue: "Nashville, TN, USA"  # library has "Seattle, WA, USA"' in text
    data = yaml.safe_load(text) or {}
    assert not data.get("proceedings")  # commented out: nothing is merged by accident


def test_complete_offline_makes_no_requests(web, library, tmp_path):
    bib = tmp_path / "refs.bib"
    bib.write_text(f"@inproceedings{{A,\n  booktitle = {{{XPLORE_NAME}}},\n  year = {{2025}},\n"
                   "  doi = {10.1109/CVPR52734.2025.02829}\n}\n")
    complete_main(str(bib), str(bib), dry_run=True, library=library, log=lambda _: None)
    assert web.calls == []
    assert not (tmp_path / ".bibcc" / "refs.bib.venue_check.txt").exists()
