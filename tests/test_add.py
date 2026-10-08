from pathlib import Path

import bibtexparser
import pytest

from bibcc import sources
from bibcc.adder import (
    add_papers,
    first_author_surname,
    format_entry,
    latex_escape,
    suggest_key,
)
from bibcc.checkers.citation_keys import _KEY_PATTERN, abbreviate_venue
from bibcc.checkers.smart_protection import protect_terms
from bibcc.cli import main
from bibcc.venues import VenueLibrary

SOURCES = Path(__file__).parent / "fixtures" / "sources"


def _fixture(name: str) -> str:
    return (SOURCES / name).read_text(encoding="utf-8")


class FakeWeb:
    """Serve canned API responses by URL substring; everything else is a 404."""

    def __init__(self, routes):
        self.routes = routes
        self.calls = []

    def __call__(self, url, headers=None, timeout=15, retries=0):
        self.calls.append(url)
        for needle, response in self.routes.items():
            if needle in url:
                return response
        return None, "HTTP 404: Not Found"


DEFAULT_ROUTES = {
    "api.crossref.org/works/10.1109/TPAMI.2024.3429383": (_fixture("crossref_tpami.json"), None),
    "api.crossref.org/works/10.1007/978-3-031-72667-5_1": (_fixture("crossref_eccv.json"), None),
    "export.arxiv.org/api/query?id_list=2603.03818": (_fixture("arxiv_2603.03818.xml"), None),
    "semanticscholar.org/graph/v1/paper/search/match": (_fixture("s2_sdlora_match.json"), None),
}


@pytest.fixture
def web(monkeypatch):
    fake = FakeWeb(dict(DEFAULT_ROUTES))
    monkeypatch.setattr(sources, "fetch_url", fake)
    return fake


@pytest.fixture
def library():
    return VenueLibrary.load()


def _entries(path: Path):
    parser = bibtexparser.bparser.BibTexParser(common_strings=True)
    return {e["ID"]: e for e in bibtexparser.loads(path.read_text(), parser=parser).entries}


@pytest.mark.parametrize(
    "text,expected",
    [
        ("10.1109/TPAMI.2024.3429383", ("doi", "10.1109/TPAMI.2024.3429383")),
        ("https://doi.org/10.1109/TPAMI.2024.3429383", ("doi", "10.1109/TPAMI.2024.3429383")),
        ("doi:10.1007/978-3-031-72667-5_1", ("doi", "10.1007/978-3-031-72667-5_1")),
        ("2501.13198", ("arxiv", "2501.13198")),
        ("arXiv:2501.13198v3", ("arxiv", "2501.13198")),
        ("https://arxiv.org/pdf/2501.13198v2.pdf", ("arxiv", "2501.13198")),
        ("10.48550/arXiv.2501.13198", ("arxiv", "2501.13198")),
        ("https://openreview.net/forum?id=x", ("url", "https://openreview.net/forum?id=x")),
        ("Three Scenarios for Continual Learning", ("title", "Three Scenarios for Continual Learning")),
    ],
)
def test_parse_identifier(text, expected):
    assert sources.parse_identifier(text) == expected


def test_crossref_book_chapter_becomes_inproceedings():
    import json

    msg = json.loads(_fixture("crossref_eccv.json"))["message"]
    record = sources.record_from_crossref(msg)
    assert record.entry_type == "inproceedings"
    assert record.fields["booktitle"] == "Computer Vision – ECCV 2024"
    assert record.fields["series"] == "Lecture Notes in Computer Science"
    assert record.fields["year"] == "2025"  # print date, as in the venue library
    assert record.fields["pages"] == "1--19"
    assert "\u00a0" not in record.fields["title"]


def test_add_doi_uses_library_fields_and_survey_format(web, library, tmp_path):
    out = tmp_path / "added.bib"
    summary = add_papers(["10.1109/TPAMI.2024.3429383"], out, library, delay=0, log=lambda _: None)
    assert summary["added"] == [("10.1109/TPAMI.2024.3429383", "ClassIncremental_Zhou_TPAMI2024")]
    text = out.read_text()
    assert "@article{ClassIncremental_Zhou_TPAMI2024,\n  title     = {Class-Incremental" in text
    assert "  month     = dec,\n" in text
    assert "  journal   = {{IEEE} Transactions on Pattern Analysis" in text
    entry = _entries(out)["ClassIncremental_Zhou_TPAMI2024"]
    assert entry["publisher"] == "IEEE"  # library wins over CrossRef's long name
    assert entry["issn"] == "1939-3539"
    assert entry["doi"] == "10.1109/TPAMI.2024.3429383"  # caller's casing kept
    assert entry["author"].startswith("Zhou, Da-Wei and Wang, Qi-Wei")


def test_add_eccv_chapter_matches_library_record(web, library, tmp_path):
    out = tmp_path / "added.bib"
    add_papers(["10.1007/978-3-031-72667-5_1"], out, library, delay=0, log=lambda _: None)
    entry = _entries(out)["ScaleDreamer_Ma_ECCV2025"]
    assert entry["booktitle"] == "Computer Vision -- {ECCV} 2024"
    assert entry["venue"] == "Milan, Italy"
    assert entry["doi"] == "10.1007/978-3-031-72667-5_1"
    assert "doi       = {10.1007/978-3-031-72667-5_1}" in out.read_text()


def test_add_arxiv_without_published_version_stays_misc(web, library, tmp_path):
    out = tmp_path / "added.bib"
    add_papers(["https://arxiv.org/abs/2603.03818v2"], out, library, delay=0, log=lambda _: None)
    entry = _entries(out)["PretrainedVision_Liu_arXiv2026"]
    assert entry["ENTRYTYPE"] == "misc"
    assert entry["eprint"] == "2603.03818"
    assert entry["archiveprefix"] == "arXiv"
    assert entry["url"] == "https://arxiv.org/abs/2603.03818"
    assert entry["title"].startswith("Pretrained Vision-Language-Action Models Are")
    assert any("arXiv:2603.03818" in call for call in web.calls)  # looked for a published version


def test_add_title_resolves_iclr_paper_via_dblp_key(web, library, tmp_path):
    out = tmp_path / "added.bib"
    title = "SD-LoRA: Scalable Decoupled Low-Rank Adaptation for Class Incremental Learning"
    add_papers([title], out, library, delay=0, log=lambda _: None)
    entry = _entries(out)["SD-LoRA_Wu_ICLR2025"]
    assert entry["ENTRYTYPE"] == "inproceedings"
    assert entry["booktitle"] == "The Thirteenth International Conference on Learning Representations"
    assert entry["venue"] == "Singapore"
    assert entry["title"].startswith("{SD-LoRA}: Scalable")


def test_add_arxiv_finds_published_version_via_crossref_search(web, library, tmp_path):
    import json

    preprint = _fixture("arxiv_2603.03818.xml").replace(
        "Pretrained Vision-Language-Action Models are Surprisingly Resistant to Forgetting in Continual Learning",
        "Class-Incremental Learning: A Survey",
    ).replace("2603.03818", "2302.03648")
    web.routes["id_list=2302.03648"] = (preprint, None)
    web.routes["semanticscholar.org"] = (None, "HTTP 429: Too Many Requests")
    tpami = json.loads(_fixture("crossref_tpami.json"))["message"]
    web.routes["query.bibliographic"] = (json.dumps({"message": {"items": [tpami]}}), None)
    out = tmp_path / "added.bib"
    summary = add_papers(["2302.03648"], out, library, delay=0, log=lambda _: None)
    assert [k for _, k in summary["added"]] == ["ClassIncremental_Zhou_TPAMI2024"]
    assert _entries(out)["ClassIncremental_Zhou_TPAMI2024"]["ENTRYTYPE"] == "article"


def test_add_arxiv_published_via_dblp_keeps_arxiv_author_names(web, library, tmp_path):
    import json

    web.routes["paper/arXiv:2603.03818"] = (json.dumps({
        "title": "Pretrained Vision-Language-Action Models are Surprisingly Resistant to Forgetting in Continual Learning",
        "externalIds": {"DBLP": "conf/iclr/LiuKLLZ25", "ArXiv": "2603.03818"},
        "authors": [{"name": "H. Liu"}],
    }), None)
    out = tmp_path / "added.bib"
    add_papers(["2603.03818"], out, library, delay=0, log=lambda _: None)
    entry = _entries(out)["PretrainedVision_Liu_ICLR2025"]
    assert entry["author"].startswith("Huihan Liu and Changyeon Kim")
    assert entry["booktitle"] == "The Thirteenth International Conference on Learning Representations"


def test_add_title_uses_openreview_when_s2_is_rate_limited(web, library, tmp_path):
    web.routes["semanticscholar.org/graph/v1/paper/search/match"] = (None, "HTTP 429: Too Many Requests")
    web.routes["api2.openreview.net"] = (_fixture("openreview_sdlora.json"), None)
    out = tmp_path / "added.bib"
    title = "SD-LoRA: Scalable Decoupled Low-Rank Adaptation for Class Incremental Learning"
    add_papers([title], out, library, delay=0, log=lambda _: None)
    entry = _entries(out)["SD-LoRA_Wu_ICLR2025"]
    assert entry["booktitle"] == "The Thirteenth International Conference on Learning Representations"
    assert entry["url"] == "https://openreview.net/forum?id=5U1rlpX68A"  # the conference's note
    assert entry["author"].startswith("Yichen Wu and Hongming Piao")


def test_openreview_ignores_unaccepted_and_other_titles(web, library):
    import json

    notes = {"notes": [
        {"id": "a", "forum": "a", "content": {"title": {"value": "Some Paper"},
                                              "venue": {"value": "Submitted to ICLR 2025"}}},
        {"id": "b", "forum": "b", "content": {"title": {"value": "Another Paper"},
                                              "venue": {"value": "ICLR 2025 Poster"}}},
    ]}
    web.routes["api2.openreview.net"] = (json.dumps(notes), None)
    assert sources.openreview_search("Some Paper", library) == (None, None)


def test_add_title_falls_back_to_arxiv_search(web, library, tmp_path):
    web.routes["search/match"] = (None, "HTTP 429: Too Many Requests")
    web.routes["search_query=ti"] = (_fixture("arxiv_2603.03818.xml"), None)
    out = tmp_path / "added.bib"
    title = "Pretrained Vision-Language-Action Models are Surprisingly Resistant to Forgetting in Continual Learning"
    summary = add_papers([title], out, library, delay=0, log=lambda _: None)
    assert [k for _, k in summary["added"]] == ["PretrainedVision_Liu_arXiv2026"]


def test_add_skips_duplicates_without_fetching(web, library, sample_bib, tmp_path):
    out = tmp_path / "added.bib"
    summary = add_papers(
        ["arXiv:2511.09791"], out, library, against=[str(sample_bib.parent)], delay=0, log=lambda _: None
    )
    assert summary["duplicates"][0][1].key == "PANDA_Raghavan_arXiv2025"
    assert web.calls == []
    assert not out.exists()


def test_add_skips_duplicate_found_after_fetching(web, library, tmp_path):
    existing = tmp_path / "bib"
    existing.mkdir()
    (existing / "a.bib").write_text(
        "@article{CIL_Zhou_TPAMI2024,\n  title = {Class-Incremental Learning: {A} Survey}\n}\n"
    )
    summary = add_papers(
        ["10.1109/TPAMI.2024.3429383"], tmp_path / "added.bib", library,
        against=[str(existing)], delay=0, log=lambda _: None,
    )
    assert summary["duplicates"][0][1].reason == "same title"


def test_add_appends_and_keeps_existing_text(web, library, tmp_path):
    out = tmp_path / "added.bib"
    original = "% staging\n@misc{Old_Doe_arXiv2020,\n  title = {Old}\n}\n"
    out.write_text(original)
    add_papers(["10.1109/TPAMI.2024.3429383", "2603.03818"], out, library, delay=0, log=lambda _: None)
    text = out.read_text()
    assert text.startswith(original.rstrip())
    assert list(_entries(out)) == [
        "Old_Doe_arXiv2020", "ClassIncremental_Zhou_TPAMI2024", "PretrainedVision_Liu_arXiv2026"
    ]
    # Running again finds both papers in the staging file itself.
    summary = add_papers(["10.1109/TPAMI.2024.3429383"], out, library, delay=0, log=lambda _: None)
    assert summary["duplicates"] and out.read_text() == text


def test_add_dry_run_writes_nothing(web, library, tmp_path):
    out = tmp_path / "added.bib"
    summary = add_papers(["2603.03818"], out, library, dry_run=True, delay=0, log=lambda _: None)
    assert summary["added"] and not out.exists()


def test_add_cli_reports_failures(web, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    ids = tmp_path / "ids.txt"
    ids.write_text("# new papers\n2603.03818\n\nhttps://openreview.net/forum?id=x\n")
    with pytest.raises(SystemExit) as exc:
        main(["add", "--from", str(ids), "--delay", "0"])
    assert exc.value.code == 1
    assert list(_entries(tmp_path / "added.bib")) == ["PretrainedVision_Liu_arXiv2026"]


@pytest.mark.parametrize(
    "author,expected",
    [
        ("van de Ven, Gido M. and Tolias, Andreas S.", "vandeVen"),
        ("Gido M. van de Ven and Andreas S. Tolias", "vandeVen"),
        ("Varol, G{\\\"u}l", "Varol"),
        ("Jos\u00e9 M\u00fcller", "Muller"),
        ("Long-Kai Huang", "Huang"),
    ],
)
def test_first_author_surname(author, expected):
    assert first_author_surname(author) == expected


def test_suggest_key_is_unique_and_follows_convention():
    fields = {"title": "{EASE}: Expandable Subspaces", "author": "Zhou, Da-Wei", "year": "2024",
              "booktitle": "2024 IEEE/CVF Conference on Computer Vision and Pattern Recognition (CVPR)"}
    assert suggest_key("inproceedings", fields, set()) == "EASE_Zhou_CVPR2024"
    assert suggest_key("inproceedings", fields, {"ease_zhou_cvpr2024"}) == "EASE2_Zhou_CVPR2024"
    arxiv = {"title": "Three Scenarios for Continual Learning", "author": "Gido M. van de Ven",
             "year": "2019", "archiveprefix": "arXiv"}
    key = suggest_key("misc", arxiv, set())
    assert key == "ThreeScenarios_vandeVen_arXiv2019"
    assert _KEY_PATTERN.match(key)


def test_key_pattern_accepts_arxiv_and_prefixes():
    assert _KEY_PATTERN.match("PretrainedVLA_Liu_arXiv2026")
    assert _KEY_PATTERN.match("Survey:CIL_Zhou_TPAMI2024")
    assert not _KEY_PATTERN.match("Survey:LTL_Zhang_2023")


@pytest.mark.parametrize(
    "venue,expected",
    [
        ("{IEEE} Transactions on Pattern Analysis and Machine Intelligence", "TPAMI"),
        ("The Thirteenth International Conference on Learning Representations", "ICLR"),
        ("Computer Vision -- {ECCV} 2024", "ECCV"),
        ("IEEE Transactions on Neural Networks and Learning Systems", "TNNLS"),
        ("Proceedings of the 2025 Workshop on Foo (FooW)", "FooW"),
        ("Machine Intelligence Research", "MIR"),
    ],
)
def test_abbreviate_venue(venue, expected):
    assert abbreviate_venue(venue) == expected


def test_protect_terms_groups_compounds():
    assert protect_terms("SD-LoRA for IEEE/CVF", ["SD", "LoRA", "IEEE", "CVF"]) == "{SD-LoRA} for {IEEE/CVF}"
    assert protect_terms("Already {BERT} and BERT", ["BERT"]) == "Already {BERT} and {BERT}"


def test_latex_escape_and_format_entry():
    assert latex_escape("R&D at 50% $a_b$ and x_y") == "R\\&D at 50\\% $a_b$ and x\\_y"
    assert latex_escape("already \\& done") == "already \\& done"
    text = format_entry("misc", "K_A_arXiv2020", {"title": "T", "year": "2020", "month": "6", "eprint": "1"})
    assert text == (
        "@misc{K_A_arXiv2020,\n  title  = {T},\n  year   = {2020},\n"
        "  month  = jun,\n  eprint = {1}\n}"
    )
