import json
from pathlib import Path

import bibtexparser
import pytest

from bibcc import sources
from bibcc.cli import main
from bibcc.upgrader import is_preprint, upgrade_bib
from bibcc.venues import VenueLibrary
from test_add import FakeWeb, _fixture

PANDA_TITLE = (
    "PANDA - Patch and Distribution-Aware Augmentation for Long-Tailed "
    "Exemplar-Free Continual Learning"
)


def _panda_arxiv(comment: str = "") -> str:
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
    return xml


def _s2_iclr() -> str:
    return json.dumps({
        "title": PANDA_TITLE,
        "externalIds": {"DBLP": "conf/iclr/RaghavanHZ25", "ArXiv": "2511.09791"},
        "venue": "International Conference on Learning Representations",
        "year": 2025,
        "authors": [{"name": "S. Raghavan"}, {"name": "J. He"}, {"name": "F. Zhu"}],
    })


@pytest.fixture
def library():
    return VenueLibrary.load()


def _entries(text: str):
    parser = bibtexparser.bparser.BibTexParser(common_strings=True)
    return {e["ID"]: e for e in bibtexparser.loads(text, parser=parser).entries}


def test_is_preprint():
    assert is_preprint({"ENTRYTYPE": "misc", "eprint": "1"})
    assert is_preprint({"ENTRYTYPE": "article", "journal": "arXiv preprint arXiv:2401.00001"})
    assert not is_preprint({"ENTRYTYPE": "article", "journal": "Pattern Recognition"})
    assert not is_preprint({"ENTRYTYPE": "misc", "howpublished": "GitHub", "journal": "Zenodo"})


def test_upgrade_dry_run_writes_diff_only(monkeypatch, library, sample_bib: Path):
    fake = FakeWeb({
        "id_list=2511.09791": (_panda_arxiv(), None),
        "paper/arXiv:2511.09791": (_s2_iclr(), None),
    })
    monkeypatch.setattr(sources, "fetch_url", fake)
    original = sample_bib.read_text()
    summary = upgrade_bib(sample_bib, None, library, delay=0, log=lambda _: None)
    assert summary["upgraded"] == [("PANDA_Raghavan_arXiv2025", "Semantic Scholar (DBLP conf/iclr/RaghavanHZ25)")]
    assert sample_bib.read_text() == original
    diff = (sample_bib.parent / ".bibcc" / "sample.bib.upgrade.diff").read_text()
    assert "+@inproceedings{PANDA_Raghavan_arXiv2025," in diff


def test_upgrade_in_place_keeps_key_title_and_custom_fields(monkeypatch, library, sample_bib: Path):
    fake = FakeWeb({
        "id_list=2511.09791": (_panda_arxiv(), None),
        "paper/arXiv:2511.09791": (_s2_iclr(), None),
    })
    monkeypatch.setattr(sources, "fetch_url", fake)
    original = sample_bib.read_text()
    main(["upgrade", str(sample_bib), "--in-place", "--delay", "0"])
    text = sample_bib.read_text()

    entry = _entries(text)["PANDA_Raghavan_arXiv2025"]
    assert entry["ENTRYTYPE"] == "inproceedings"
    assert entry["booktitle"] == "The Thirteenth International Conference on Learning Representations"
    assert entry["venue"] == "Singapore"
    assert entry["title"].startswith("{PANDA} -- Patch And")  # hand-made title kept
    assert entry["author"] == "Siddeshwar Raghavan and Jiangpeng He and Fengqing Zhu"
    assert entry["citation"] == "0"
    for dropped in ("eprint", "archiveprefix", "primaryclass", "url"):
        assert dropped not in entry

    # Everything outside the replaced entry is byte-identical, comment included.
    start = original.index("@misc{PANDA_Raghavan_arXiv2025")
    assert text[:start] == original[:start]
    assert "% TODO: switch to official bibtex\n@inproceedings{PANDA" in text


def test_upgrade_via_openreview_adds_forum_url(monkeypatch, library, sample_bib: Path):
    notes = {"notes": [{"id": "abc", "forum": "abc", "content": {
        "title": {"value": PANDA_TITLE},
        "venue": {"value": "ICLR 2025 Poster"},
        "venueid": {"value": "ICLR.cc/2025/Conference"},
        "authors": {"value": ["Siddeshwar Raghavan", "Jiangpeng He", "Fengqing Zhu"]},
    }}]}
    fake = FakeWeb({
        "id_list=2511.09791": (_panda_arxiv(), None),
        "semanticscholar.org": (None, "HTTP 429: Too Many Requests"),
        "api2.openreview.net": (json.dumps(notes), None),
    })
    monkeypatch.setattr(sources, "fetch_url", fake)
    summary = upgrade_bib(sample_bib, sample_bib, library, delay=0, log=lambda _: None)
    assert summary["upgraded"] == [("PANDA_Raghavan_arXiv2025", "OpenReview (ICLR 2025 Poster)")]
    entry = _entries(sample_bib.read_text())["PANDA_Raghavan_arXiv2025"]
    assert entry["url"] == "https://openreview.net/forum?id=abc"
    assert entry["booktitle"] == "The Thirteenth International Conference on Learning Representations"


def test_upgrade_reports_accepted_but_unindexed(monkeypatch, library, sample_bib: Path):
    fake = FakeWeb({"id_list=2511.09791": (_panda_arxiv("Accepted at WACV 2026"), None)})
    monkeypatch.setattr(sources, "fetch_url", fake)
    original = sample_bib.read_text()
    summary = upgrade_bib(sample_bib, sample_bib, library, delay=0, log=lambda _: None)
    assert summary["upgraded"] == []
    key, reason = summary["unchanged"][0]
    assert key == "PANDA_Raghavan_arXiv2025" and "Accepted at WACV 2026" in reason
    assert sample_bib.read_text() == original
    report = (sample_bib.parent / ".bibcc" / "sample.bib.upgrade.txt").read_text()
    assert "PANDA_Raghavan_arXiv2025\tunchanged" in report


def test_upgrade_refuses_output_and_in_place(sample_bib: Path):
    with pytest.raises(SystemExit):
        main(["upgrade", str(sample_bib), "--in-place", "--output", "x.bib"])
