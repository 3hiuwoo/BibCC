"""``bibcc add --fallback``: entries built from metadata, the add report, and their upgrade."""

import json
from pathlib import Path

import bibtexparser
import pytest

from bibcc import official, sources
from bibcc.adder import (
    EMPTY_ENTRY_MARK,
    METADATA_MARK,
    REPORT_HEADER,
    add_papers,
    drop_metadata_comment,
    metadata_keys,
)
from bibcc.cli import main
from bibcc.upgrader import report_published, upgrade_bib
from bibcc.venues import VenueLibrary
from conftest import MIAA_VENUES
from test_add import DEFAULT_ROUTES, XPLORE_EXPORT, FakeWeb, _fixture

TPAMI = "10.1109/TPAMI.2024.3429383"
AAAI = "10.1609/aaai.v39i1.30001"
TPAMI_KEY = "ClassIncremental_Zhou_TPAMI2024"
AAAI_KEY = "ContinualLearning_Zhou_AAAI2025"


def _aaai_crossref() -> str:
    msg = json.loads(_fixture("crossref_tpami.json"))["message"]
    msg.pop("resource")
    msg.update({
        "DOI": AAAI,
        "title": ["Continual Learning for Everyone"],
        "container-title": ["Proceedings of the AAAI Conference on Artificial Intelligence"],
        "published-print": {"date-parts": [[2025, 4]]},
    })
    return json.dumps({"message": msg})


@pytest.fixture
def web(monkeypatch):
    fake = FakeWeb(dict(DEFAULT_ROUTES))
    fake.routes[f"api.crossref.org/works/{AAAI}"] = (_aaai_crossref(), None)
    monkeypatch.setattr(sources, "fetch_url", fake)
    official.clear_cache()
    yield fake
    official.clear_cache()


@pytest.fixture
def library():
    return VenueLibrary.load(MIAA_VENUES)


def _entries(path: Path):
    parser = bibtexparser.bparser.BibTexParser(common_strings=True)
    return {e["ID"]: e for e in bibtexparser.loads(path.read_text(), parser=parser).entries}


def _report(tmp_path: Path, name: str = "added.bib"):
    lines = (tmp_path / ".bibcc" / f"{name}.add.txt").read_text().splitlines()
    assert lines[0] == REPORT_HEADER
    return [line.split("\t") for line in lines[1:]]


def test_default_is_official_only_and_says_which_level_would_cover_each_paper(web, library, tmp_path):
    web.routes[XPLORE_EXPORT + "10599804"] = (None, "HTTP 503: Service Unavailable")
    out = tmp_path / "added.bib"
    lines = []
    summary = add_papers([AAAI, TPAMI, "No Such Paper Anywhere"], out, library, delay=0, log=lines.append)
    assert [k for _, k, _ in summary["empty"]] == [AAAI_KEY]
    assert summary["metadata"] == []
    assert [i for i, _ in summary["failed"]] == [TPAMI, "No Such Paper Anywhere"]
    assert METADATA_MARK not in out.read_text()

    rows = _report(tmp_path)
    assert [(r[0], r[1], r[2]) for r in rows] == [
        (AAAI, "empty", AAAI_KEY),
        (TPAMI, "failed", ""),
        ("No Such Paper Anywhere", "failed", ""),
    ]
    assert rows[0][5] == f"https://doi.org/{AAAI}"
    assert rows[1][3] == "Class-Incremental Learning: A Survey" and "503" in rows[1][4]

    log = "\n".join(lines)
    todo = log[log.index("✋ 3 left to do by hand"):]
    assert "--fallback missing" in todo and "--fallback all" in todo
    assert "check the identifier" in todo


def test_fallback_missing_builds_blocked_paper_from_crossref(web, library, tmp_path):
    out = tmp_path / "added.bib"
    summary = add_papers([AAAI], out, library, delay=0, log=lambda _: None, fallback="missing")
    assert summary["empty"] == []
    assert [(i, k) for i, k, _ in summary["metadata"]] == [(AAAI, AAAI_KEY)]
    assert summary["added"] == [(AAAI, AAAI_KEY)]

    text = out.read_text()
    assert text.startswith(f"{METADATA_MARK}; it was built from metadata.")
    assert "%   source: CrossRef\n" in text
    assert "%   reason: AAAI blocks automated BibTeX downloads\n" in text
    assert f"%   get it: https://doi.org/{AAAI}\n" in text
    assert EMPTY_ENTRY_MARK not in text
    entry = _entries(out)[AAAI_KEY]
    assert entry["ENTRYTYPE"] == "inproceedings"
    assert entry["booktitle"] == "Proceedings of the {AAAI} Conference on Artificial Intelligence"
    assert entry["doi"] == AAAI
    assert entry["author"].startswith("Zhou, Da-Wei")
    # The venue library wins over the metadata, and fills what it lacks.
    assert entry["publisher"] == "AAAI Press"
    assert entry["venue"] == "Philadelphia, Pennsylvania, USA"
    assert entry["issn"] == "2374-3468"
    assert metadata_keys(text) == {AAAI_KEY}
    assert [r[1] for r in _report(tmp_path)] == ["metadata"]

    # It counts as present: adding the paper again is a duplicate.
    again = add_papers([AAAI], out, library, delay=0, log=lambda _: None, fallback="missing")
    assert again["duplicates"][0][1].key == AAAI_KEY and out.read_text() == text


def test_fallback_missing_leaves_unreachable_site_as_failure(web, library, tmp_path):
    web.routes[XPLORE_EXPORT + "10599804"] = (None, "HTTP 503: Service Unavailable")
    out = tmp_path / "added.bib"
    lines = []
    summary = add_papers([TPAMI], out, library, delay=0, log=lines.append, fallback="missing")
    assert summary["added"] == [] and "503" in summary["failed"][0][1]
    assert not out.exists()
    assert "or run again with --fallback all" in "\n".join(lines)


def test_fallback_all_builds_paper_whose_site_is_unreachable(web, library, tmp_path):
    web.routes[XPLORE_EXPORT + "10599804"] = (None, "HTTP 503: Service Unavailable")
    out = tmp_path / "added.bib"
    summary = add_papers([TPAMI], out, library, delay=0, log=lambda _: None, fallback="all")
    assert summary["failed"] == []
    assert [k for _, k, _ in summary["metadata"]] == [TPAMI_KEY]
    text = out.read_text()
    assert "%   reason: IEEE Xplore: HTTP 503: Service Unavailable\n" in text
    entry = _entries(out)[TPAMI_KEY]
    assert entry["ENTRYTYPE"] == "article"
    assert entry["journal"] == "{IEEE} Transactions on Pattern Analysis and Machine Intelligence"
    assert entry["pages"] == "9851--9873"
    assert entry["doi"] == TPAMI


def test_fallback_all_cli_exits_zero(web, tmp_path, monkeypatch, miaa_user_library):
    web.routes[XPLORE_EXPORT + "10599804"] = (None, "HTTP 503: Service Unavailable")
    monkeypatch.chdir(tmp_path)
    main(["add", TPAMI, AAAI, "--delay", "0", "--fallback", "all"])
    assert metadata_keys((tmp_path / "added.bib").read_text()) == {TPAMI_KEY, AAAI_KEY}
    with pytest.raises(SystemExit) as exc:
        main(["add", "2603.03818", "--fallback", "sometimes"])
    assert exc.value.code == 2


def test_metadata_comment_helpers_only_touch_the_marked_entry():
    text = (
        "% my own note\n@misc{A,\n  title = {A}\n}\n\n"
        f"{METADATA_MARK}; it was built from metadata.\n%   source: CrossRef\n@article{{B,\n  title = {{B}}\n}}\n"
    )
    assert metadata_keys(text) == {"B"}
    dropped = drop_metadata_comment(text, "B")
    assert dropped == "% my own note\n@misc{A,\n  title = {A}\n}\n\n@article{B,\n  title = {B}\n}\n"
    assert drop_metadata_comment(text, "A") == text


def _metadata_bib(web, library, tmp_path) -> Path:
    web.routes[XPLORE_EXPORT + "10599804"] = (None, "HTTP 503: Service Unavailable")
    out = tmp_path / "added.bib"
    out.write_text("% staging\n@misc{Old_Doe_2020,\n  title = {Old},\n  howpublished = {Somewhere}\n}\n")
    add_papers([TPAMI, AAAI], out, library, delay=0, log=lambda _: None, fallback="all")
    return out


def test_upgrade_replaces_metadata_entry_once_official_bibtex_downloads(web, library, tmp_path):
    out = _metadata_bib(web, library, tmp_path)
    web.routes[XPLORE_EXPORT + "10599804"] = (_fixture("xplore_10599804.json"), None)
    summary = upgrade_bib(out, out, library, delay=0, log=lambda _: None)
    assert summary["upgraded"] == [(TPAMI_KEY, "IEEE Xplore")]
    assert [k for k, _ in summary["unchanged"]] == [AAAI_KEY]
    assert "still no official BibTeX: AAAI blocks" in summary["unchanged"][0][1]

    text = out.read_text()
    assert metadata_keys(text) == {AAAI_KEY}  # the TPAMI comment is gone, the AAAI one stays
    assert text.count(METADATA_MARK) == 1
    assert text.startswith("% staging\n@misc{Old_Doe_2020,")
    assert list(_entries(out)) == ["Old_Doe_2020", TPAMI_KEY, AAAI_KEY]
    assert _entries(out)[TPAMI_KEY]["number"] == "12"


def test_upgrade_reports_unreachable_site_for_metadata_entry(web, library, tmp_path):
    out = _metadata_bib(web, library, tmp_path)
    before = out.read_text()
    summary = upgrade_bib(out, out, library, ids=[TPAMI_KEY], delay=0, log=lambda _: None)
    assert [k for k, _ in summary["failed"]] == [TPAMI_KEY]
    assert out.read_text() == before


def test_report_only_lists_metadata_entries_with_official_bibtex(web, library, tmp_path):
    out = _metadata_bib(web, library, tmp_path)
    web.routes[XPLORE_EXPORT + "10599804"] = (_fixture("xplore_10599804.json"), None)
    summary = report_published([str(out)], library, delay=0, log=lambda _: None)
    rows = [(row[1], row[2], row[4]) for row in summary["published"]]
    assert (TPAMI_KEY, "official BibTeX available", "IEEE Xplore") in rows
