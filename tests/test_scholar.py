import json
from pathlib import Path

import pytest

from bibcc import sources
from bibcc.utils import scholar

SOURCES = Path(__file__).parent / "fixtures" / "sources"


class FakeWeb:
    """Serve canned responses by URL substring; everything else is a 404."""

    def __init__(self, routes):
        self.routes = routes
        self.calls = []

    def __call__(self, url, headers=None, timeout=15, retries=0):
        self.calls.append(url)
        for needle, response in self.routes.items():
            if needle in url:
                return response
        return None, "HTTP 404: Not Found"


@pytest.fixture
def web(monkeypatch):
    fake = FakeWeb({})
    monkeypatch.setattr(sources, "fetch_url", fake)
    return fake


def test_crossref_lookup_uses_doi(web):
    web.routes["api.crossref.org/works/10.1109%2FTPAMI.2024.3429383"] = (
        (SOURCES / "crossref_tpami.json").read_text(encoding="utf-8"),
        None,
    )
    entry = {"doi": "https://doi.org/10.1109/TPAMI.2024.3429383", "title": "Class-incremental learning: a survey"}

    matches, statuses = scholar.find_original_title(entry, delay=0)

    assert [m.original_title for m in matches] == ["Class-Incremental Learning: A Survey"]
    assert [(s.source, s.status) for s in statuses] == [("CrossRef (DOI)", "found")]
    assert len(web.calls) == 1


def test_arxiv_case_difference_stops_search(web):
    web.routes["export.arxiv.org/api/query?id_list=2603.03818"] = (
        (SOURCES / "arxiv_2603.03818.xml").read_text(encoding="utf-8"),
        None,
    )
    entry = {
        "eprint": "2603.03818",
        "title": "Pretrained vision-language-action models are surprisingly resistant to forgetting "
        "in continual learning",
    }

    matches, statuses = scholar.find_original_title(entry, delay=0)

    assert matches[0].source == "arXiv"
    assert matches[0].url == "https://arxiv.org/abs/2603.03818"
    assert [s.status for s in statuses] == ["found"]
    assert not any("dblp" in url for url in web.calls)


def test_title_only_entry_uses_semantic_scholar_and_not_dblp(web):
    web.routes["api.semanticscholar.org/graph/v1/paper/search"] = (
        json.dumps({"data": [{"title": "Some Paper Title", "url": "https://s2/x"}]}),
        None,
    )

    matches, statuses = scholar.find_original_title({"title": "Some paper title"}, delay=0)

    assert [(m.source, m.original_title) for m in matches] == [("Semantic Scholar", "Some Paper Title")]
    assert [(s.source, s.status, s.error) for s in statuses] == [("Semantic Scholar", "found", None)]
    assert not any("dblp" in url for url in web.calls)


def test_arxiv_match_without_case_difference_asks_semantic_scholar(web):
    web.routes["export.arxiv.org/api/query?id_list=2603.03818"] = (
        (SOURCES / "arxiv_2603.03818.xml").read_text(encoding="utf-8"),
        None,
    )
    web.routes["api.semanticscholar.org"] = (None, "HTTP 503: Service Unavailable")
    arxiv_title = scholar.lookup_arxiv({"eprint": "2603.03818"}).match.original_title

    matches, statuses = scholar.find_original_title({"eprint": "2603.03818", "title": arxiv_title}, delay=0)

    assert [m.source for m in matches] == ["arXiv"]
    assert [(s.source, s.status) for s in statuses] == [("arXiv", "found"), ("Semantic Scholar", "error")]


def test_crossref_title_search_is_the_fallback(web):
    web.routes["api.semanticscholar.org"] = (None, "HTTP 429: Too Many Requests")
    item = {"title": ["Some Paper Title"], "DOI": "10.1/x", "type": "journal-article"}
    web.routes["api.crossref.org/works?query"] = (json.dumps({"message": {"items": [item]}}), None)

    matches, statuses = scholar.find_original_title({"title": "Some paper title"}, delay=0)

    assert [(m.source, m.original_title, m.url) for m in matches] == [
        ("CrossRef (title)", "Some Paper Title", "https://doi.org/10.1/x")
    ]
    assert statuses[0].source == "Semantic Scholar"
    assert statuses[0].error.startswith("rate limited (HTTP 429)")
    assert [(s.source, s.status) for s in statuses[1:]] == [("CrossRef (title)", "found")]


def test_multi_line_title_is_reported_on_one_line(web, tmp_path: Path):
    bib = tmp_path / "refs.bib"
    bib.write_text("@misc{K, title={Some paper\n     title}}\n", encoding="utf-8")
    report = tmp_path / "report.txt"
    web.routes["api.semanticscholar.org"] = (json.dumps({"data": []}), None)
    web.routes["api.crossref.org/works?query"] = (json.dumps({"message": {"items": []}}), None)

    scholar.check_titles(str(bib), str(report), delay=0, verbose=False, log=lambda _: None)

    assert "Title: Some paper title\n" in report.read_text()
    assert scholar.parse_full_report(str(report))[2][0]["current_title"] == "Some paper title"


def test_html_response_is_an_error(web):
    web.routes["api.semanticscholar.org"] = ("<!DOCTYPE html><html>blocked</html>", None)

    result = scholar.lookup_semantic_scholar("Some paper title")

    assert result.match is None
    assert "HTML" in (result.error or "")


def test_title_report_round_trip_and_retry_merge(web, tmp_path: Path):
    bib = tmp_path / "refs.bib"
    bib.write_text(
        "@inproceedings{Lower, title={Some paper title}}\n"
        "@inproceedings{Flaky, title={Another paper title}}\n"
        "@inproceedings{Unknown, title={Nobody wrote this}}\n",
        encoding="utf-8",
    )
    report = tmp_path / "report.txt"

    def s2(title):
        return (json.dumps({"data": [{"title": title, "url": "https://s2/x"}]}), None)

    s2_search = "api.semanticscholar.org/graph/v1/paper/search?query="
    web.routes[s2_search + "Some"] = s2("Some Paper Title")
    web.routes[s2_search + "Another"] = (None, "HTTP 429: Too Many Requests")
    web.routes["api.semanticscholar.org"] = (json.dumps({"data": []}), None)
    web.routes["api.crossref.org/works?query"] = (json.dumps({"message": {"items": []}}), None)

    results = scholar.check_titles(str(bib), str(report), delay=0, verbose=False, log=lambda _: None)

    assert [(r["id"], r["not_found"]) for r in results] == [("Lower", False), ("Flaky", True), ("Unknown", True)]
    assert scholar.parse_error_ids_from_report(str(report)) == ["Flaky"]
    case_diffs, with_errors, no_match, meta = scholar.parse_full_report(str(report))
    assert [r["original_title"] for r in case_diffs] == ["Some Paper Title"]
    assert [r["id"] for r in with_errors] == ["Flaky"]
    assert [r["id"] for r in no_match] == ["Unknown"]
    assert meta["total"] == 3

    web.routes[s2_search + "Another"] = s2("Another Paper Title")
    retried = scholar.check_titles(
        str(bib), delay=0, verbose=False, filter_ids=["Flaky"], log=lambda _: None
    )
    scholar.merge_and_write_report(str(report), retried, ["Flaky"], str(bib), 1, log=lambda _: None)

    case_diffs, with_errors, no_match, meta = scholar.parse_full_report(str(report))
    assert [r["id"] for r in case_diffs] == ["Lower", "Flaky"]
    assert with_errors == []
    assert [r["id"] for r in no_match] == ["Unknown"]
    assert meta["total"] == 3


def test_case_differs_ignores_braces():
    assert scholar.case_differs("A {BERT} model", "A bert model")
    assert not scholar.case_differs("A {BERT} model", "A BERT model")
    assert not scholar.case_differs("A model", "Another model")
