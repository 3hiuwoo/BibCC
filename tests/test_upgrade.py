import json
from pathlib import Path

import bibtexparser
import pytest

from bibcc import official, sources
from bibcc.cli import main
from bibcc.upgrader import candidate_kind, is_preprint, report_published, upgrade_bib
from bibcc.venues import VenueLibrary, merge_missing_venues
from conftest import MIAA_VENUES
from test_add import XPLORE_EXPORT, FakeWeb, _fixture

PANDA_TITLE = (
    "PANDA - Patch and Distribution-Aware Augmentation for Long-Tailed "
    "Exemplar-Free Continual Learning"
)
ICLR_SITE = "proceedings.iclr.cc/paper_files/paper/2025"
CVPR_TITLE = "A Unified, Resilient, and Explainable Adversarial Patch Detector"
CVF_2025 = "Proceedings of the Computer Vision and Pattern Recognition Conference (CVPR)"
XPLORE_CVPR = "2025 IEEE/CVF Conference on Computer Vision and Pattern Recognition (CVPR)"


def _panda_arxiv(comment: str = "", doi: str = "") -> str:
    xml = _fixture("arxiv_2603.03818.xml").replace("2603.03818", "2511.09791")
    xml = xml.replace(
        "Pretrained Vision-Language-Action Models are Surprisingly Resistant to Forgetting in Continual Learning",
        PANDA_TITLE,
    )
    if comment:
        xml = xml.replace(
            "<arxiv:comment>Project website: https://continual-vlas.github.io/forget-me-not/</arxiv:comment>",
            f"<arxiv:comment>{comment}</arxiv:comment>",
        )
    if doi:
        xml = xml.replace("<arxiv:primary_category", f"<arxiv:doi>{doi}</arxiv:doi>\n    <arxiv:primary_category")
    return xml


def _s2_iclr() -> str:
    return json.dumps({
        "title": PANDA_TITLE,
        "externalIds": {"DBLP": "conf/iclr/RaghavanHZ25", "ArXiv": "2511.09791"},
        "venue": "International Conference on Learning Representations",
        "year": 2025,
        "authors": [{"name": "S. Raghavan"}, {"name": "J. He"}, {"name": "F. Zhu"}],
    })


def _iclr_routes() -> dict:
    """PANDA in the ICLR 2025 proceedings."""
    listing = _fixture("iclr_2025_listing.html").replace(
        "Generalization and Distributed Learning of GFlowNets", PANDA_TITLE)
    bib = _fixture("iclr_000eba87.bib").replace(
        "Generalization and Distributed Learning of GFlowNets",
        "PANDA - Patch and Distribution-Aware Augmentation for Long-Tailed Exemplar-Free Continual Learning",
    ).replace(
        "Silva, Tiago and Souza, Amauri and Rivasplata, Omar and Garg, Vikas and Kaski, Samuel and Mesquita, Diego",
        "Raghavan, Siddeshwar and He, Jiangpeng and Zhu, Fengqing",
    )
    return {
        "id_list=2511.09791": (_panda_arxiv(), None),
        "paper/arXiv:2511.09791": (_s2_iclr(), None),
        f"{ICLR_SITE}/hash/": ("", None),
        f"{ICLR_SITE}/file/000eba875068854d5ff003b1fa534cd6-Bibtex.bib": (bib, None),
        ICLR_SITE: (listing, None),
    }


def _cvpr_routes() -> dict:
    items = {"message": {"items": [json.loads(_fixture("crossref_cvpr2025.json"))["message"]]}}
    return {
        "query.bibliographic": (json.dumps(items), None),
        XPLORE_EXPORT + "11095062": (_fixture("xplore_11095062.json"), None),
    }


CVF_ENTRY = f"""@inproceedings{{Unified_Kumar_CVPR2025,
  title     = {{A Unified, Resilient, and Explainable Adversarial Patch Detector}},
  author    = {{Kumar, Vishesh and Agarwal, Akshay}},
  booktitle = {{{CVF_2025}}},
  month     = jun,
  year      = {{2025}},
  pages     = {{30387-30397}},
  url       = {{https://openaccess.thecvf.com/content/CVPR2025/html/Kumar_A_Unified_CVPR_2025_paper.html}},
  note      = {{oral}}
}}
"""


@pytest.fixture
def web(monkeypatch):
    fake = FakeWeb({})
    monkeypatch.setattr(sources, "fetch_url", fake)
    official.clear_cache()
    yield fake
    official.clear_cache()


@pytest.fixture
def library():
    return VenueLibrary.load(MIAA_VENUES)


def _entries(text: str):
    parser = bibtexparser.bparser.BibTexParser(common_strings=True)
    return {e["ID"]: e for e in bibtexparser.loads(text, parser=parser).entries}


def test_is_preprint():
    assert is_preprint({"ENTRYTYPE": "misc", "eprint": "1"})
    assert is_preprint({"ENTRYTYPE": "article", "journal": "arXiv preprint arXiv:2401.00001"})
    assert not is_preprint({"ENTRYTYPE": "article", "journal": "Pattern Recognition"})
    assert not is_preprint({"ENTRYTYPE": "misc", "howpublished": "GitHub", "journal": "Zenodo"})


def test_candidate_kind(library):
    assert candidate_kind({"ENTRYTYPE": "misc", "eprint": "1"}, library) == "preprint"
    assert candidate_kind({"ENTRYTYPE": "inproceedings", "booktitle": CVF_2025, "year": "2025"}, library) == "cvf"
    iclr = "The Thirteenth International Conference on Learning Representations"
    assert candidate_kind({"ENTRYTYPE": "inproceedings", "booktitle": iclr, "year": "2025"}, library) == "openreview"
    assert candidate_kind({"ENTRYTYPE": "inproceedings", "booktitle": XPLORE_CVPR, "year": "2025"}, library) == ""
    old_iclr = "The Eleventh International Conference on Learning Representations"
    assert candidate_kind({"ENTRYTYPE": "inproceedings", "booktitle": old_iclr, "year": "2023"}, library) == ""


def test_upgrade_dry_run_writes_diff_only(web, library, sample_bib: Path):
    web.routes.update(_iclr_routes())
    original = sample_bib.read_text()
    summary = upgrade_bib(sample_bib, None, library, delay=0, log=lambda _: None)
    assert summary["upgraded"] == [("PANDA_Raghavan_arXiv2025", "ICLR Proceedings")]
    assert sample_bib.read_text() == original
    diff = (sample_bib.parent / ".bibcc" / "sample.bib" / "upgrade.diff").read_text()
    assert "+@inproceedings{PANDA_Raghavan_arXiv2025," in diff


def test_upgrade_in_place_keeps_key_title_and_custom_fields(web, library, sample_bib: Path, miaa_user_library):
    web.routes.update(_iclr_routes())
    original = sample_bib.read_text()
    main(["upgrade", str(sample_bib), "--in-place", "--delay", "0"])
    text = sample_bib.read_text()

    entry = _entries(text)["PANDA_Raghavan_arXiv2025"]
    assert entry["ENTRYTYPE"] == "inproceedings"
    assert entry["booktitle"] == "International Conference on Learning Representations"
    assert entry["venue"] == "Singapore"  # from the library
    assert entry["editor"].startswith("Y. Yue and A. Garg")  # from the official BibTeX
    assert entry["title"].startswith("{PANDA} -- Patch And")  # hand-made title kept
    assert entry["author"] == "Raghavan, Siddeshwar and He, Jiangpeng and Zhu, Fengqing"
    assert entry["citation"] == "0"
    assert entry["url"].startswith("https://proceedings.iclr.cc/")
    for dropped in ("eprint", "archiveprefix", "primaryclass"):
        assert dropped not in entry

    # Everything outside the replaced entry is byte-identical, comment included.
    start = original.index("@misc{PANDA_Raghavan_arXiv2025")
    assert text[:start] == original[:start]
    assert "% TODO: switch to official bibtex\n@inproceedings{PANDA" in text


def test_upgrade_to_interim_openreview_bibtex(web, library, sample_bib: Path):
    bibtex = (
        "@inproceedings{\nraghavan2025panda,\ntitle={" + PANDA_TITLE + "},\n"
        "author={Siddeshwar Raghavan and Jiangpeng He and Fengqing Zhu},\n"
        "booktitle={The Thirteenth International Conference on Learning Representations},\n"
        "year={2025},\nurl={https://openreview.net/forum?id=abc}\n}"
    )
    notes = {"notes": [{"id": "abc", "forum": "abc", "content": {
        "title": {"value": PANDA_TITLE},
        "venue": {"value": "ICLR 2025 Poster"},
        "venueid": {"value": "ICLR.cc/2025/Conference"},
        "authors": {"value": ["Siddeshwar Raghavan", "Jiangpeng He", "Fengqing Zhu"]},
        "_bibtex": {"value": bibtex},
    }}]}
    web.routes.update({
        "id_list=2511.09791": (_panda_arxiv(), None),
        "semanticscholar.org": (None, "HTTP 429: Too Many Requests"),
        "api2.openreview.net": (json.dumps(notes), None),
    })
    summary = upgrade_bib(sample_bib, sample_bib, library, delay=0, log=lambda _: None)
    assert summary["upgraded"] == [("PANDA_Raghavan_arXiv2025", "OpenReview")]
    entry = _entries(sample_bib.read_text())["PANDA_Raghavan_arXiv2025"]
    assert entry["url"] == "https://openreview.net/forum?id=abc"
    assert entry["booktitle"] == "The Thirteenth International Conference on Learning Representations"
    assert entry["venue"] == "Singapore"


def test_upgrade_reports_accepted_but_unindexed(web, library, sample_bib: Path):
    web.routes["id_list=2511.09791"] = (_panda_arxiv("Accepted at WACV 2026"), None)
    original = sample_bib.read_text()
    summary = upgrade_bib(sample_bib, sample_bib, library, delay=0, log=lambda _: None)
    assert summary["upgraded"] == []
    key, reason = summary["unchanged"][0]
    assert key == "PANDA_Raghavan_arXiv2025" and "Accepted at WACV 2026" in reason
    assert sample_bib.read_text() == original
    report = (sample_bib.parent / ".bibcc" / "sample.bib" / "upgrade.txt").read_text()
    assert "PANDA_Raghavan_arXiv2025\tunchanged" in report


def test_upgrade_keeps_preprint_without_official_bibtex(web, library, sample_bib: Path):
    msg = json.loads(_fixture("crossref_tpami.json"))["message"]
    msg.pop("resource")
    msg.update({
        "DOI": "10.1609/aaai.v39i1.30001",
        "title": [PANDA_TITLE],
        "container-title": ["Proceedings of the AAAI Conference on Artificial Intelligence"],
        "published-print": {"date-parts": [[2025, 4]]},
    })
    web.routes.update({
        "id_list=2511.09791": (_panda_arxiv(doi="10.1609/aaai.v39i1.30001"), None),
        "api.crossref.org/works/10.1609/aaai.v39i1.30001": (json.dumps({"message": msg}), None),
    })
    original = sample_bib.read_text()
    summary = upgrade_bib(sample_bib, sample_bib, library, delay=0, log=lambda _: None)
    assert summary["upgraded"] == [] and summary["failed"] == []
    ((key, reason),) = summary["unchanged"]
    assert "published in Proceedings of the AAAI Conference on Artificial Intelligence (2025)" in reason
    assert "AAAI blocks" in reason and "https://doi.org/10.1609/aaai.v39i1.30001" in reason
    assert sample_bib.read_text() == original


def test_upgrade_interim_cvf_entry_to_xplore(web, library, tmp_path):
    web.routes.update(_cvpr_routes())
    bib = tmp_path / "cvpr.bib"
    bib.write_text(CVF_ENTRY)
    summary = upgrade_bib(bib, bib, library, delay=0, log=lambda _: None)
    assert summary["upgraded"] == [("Unified_Kumar_CVPR2025", "IEEE Xplore")]
    entry = _entries(bib.read_text())["Unified_Kumar_CVPR2025"]
    assert entry["booktitle"] == "2025 {IEEE/CVF} Conference on Computer Vision and Pattern Recognition ({CVPR})"
    assert entry["doi"] == "10.1109/CVPR52734.2025.02829"
    assert entry["venue"] == "Nashville, TN, USA"  # from the library
    assert entry["note"] == "oral"  # custom field carried over
    assert "url" not in entry  # the CVF page is dropped
    # The library already links this CVF name: nothing to propose.
    assert not (tmp_path / ".bibcc" / "cvpr.bib" / "missing_venues.yaml").exists()


def test_upgrade_interim_entry_waits_for_proceedings(web, library, tmp_path):
    web.routes["query.bibliographic"] = (json.dumps({"message": {"items": []}}), None)
    bib = tmp_path / "cvpr.bib"
    bib.write_text(CVF_ENTRY)
    summary = upgrade_bib(bib, bib, library, delay=0, log=lambda _: None)
    assert summary["upgraded"] == []
    ((_, reason),) = summary["unchanged"]
    assert reason.startswith("proceedings not available yet")
    assert not any("thecvf.com" in c for c in web.calls)  # no interim source for an interim entry
    assert bib.read_text() == CVF_ENTRY


def test_upgrade_proposes_link_for_unknown_interim_name(web, tmp_path):
    web.routes.update(_cvpr_routes())
    venues = tmp_path / "venues.yaml"
    venues.write_text(
        "proceedings:\n"
        f"- name: {json.dumps(XPLORE_CVPR)}\n"
        "  year: 2025\n"
        "  fields:\n"
        "    venue: Nashville, TN, USA\n"
    )
    library = VenueLibrary.load(venues)
    bib = tmp_path / "cvpr.bib"
    bib.write_text(CVF_ENTRY)
    summary = upgrade_bib(bib, None, library, delay=0, log=lambda _: None)
    assert summary["upgraded"]
    yaml_path = tmp_path / ".bibcc" / "cvpr.bib" / "missing_venues.yaml"
    text = yaml_path.read_text()
    assert CVF_2025 in text and "cvf" in text

    merge_missing_venues(library, yaml_path, log=lambda _: None)
    record = library.lookup(CVF_2025, "2025", "proceedings")
    assert record.venue.name == XPLORE_CVPR and record.interim_source == "cvf"


def test_report_only_lists_published_versions_without_downloading(web, library, tmp_path):
    web.routes.update(_iclr_routes())
    web.routes.update(_cvpr_routes())
    folder = tmp_path / "bib"
    folder.mkdir()
    (folder / "cvpr.bib").write_text(CVF_ENTRY)
    sample = Path(__file__).parent / "fixtures" / "sample.bib"
    (folder / "sample.bib").write_text(sample.read_text())
    before = {p.name: p.read_text() for p in folder.glob("*.bib")}

    summary = report_published([str(folder)], library, delay=0, log_dir=tmp_path / "out", log=lambda _: None)
    rows = {row[1]: row for row in summary["published"]}
    assert set(rows) == {"Unified_Kumar_CVPR2025", "PANDA_Raghavan_arXiv2025"}
    assert rows["Unified_Kumar_CVPR2025"][4:] == ("IEEE Xplore", "https://ieeexplore.ieee.org/document/11095062")
    assert rows["PANDA_Raghavan_arXiv2025"][2] == "published"
    assert rows["PANDA_Raghavan_arXiv2025"][5].endswith("-Abstract-Conference.html")
    assert {p.name: p.read_text() for p in folder.glob("*.bib")} == before
    assert not any(XPLORE_EXPORT in c or c.endswith(".bib") for c in web.calls)
    report = (tmp_path / "out" / "bib" / "published.txt").read_text()
    assert "Unified_Kumar_CVPR2025\tpublished\t" in report


def test_report_only_cli_accepts_several_paths(web, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    a, b = tmp_path / "a.bib", tmp_path / "b.bib"
    a.write_text("@article{A,\n  title = {T},\n  journal = {Pattern Recognition},\n  year = {2024}\n}\n")
    b.write_text("")
    main(["upgrade", "--report-only", str(a), str(b), "--delay", "0"])
    assert (tmp_path / ".bibcc" / "a.bib" / "published.txt").exists()
    with pytest.raises(SystemExit):
        main(["upgrade", "--report-only", str(a), "--in-place"])
    with pytest.raises(SystemExit):
        main(["upgrade", str(a), str(b)])


def test_upgrade_refuses_output_and_in_place(sample_bib: Path):
    with pytest.raises(SystemExit):
        main(["upgrade", str(sample_bib), "--in-place", "--output", "x.bib"])
