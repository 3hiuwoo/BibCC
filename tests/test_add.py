from pathlib import Path

import bibtexparser
import pytest

from bibcc import official, sources
from bibcc.adder import (
    EMPTY_ENTRY_MARK,
    add_papers,
    build_entry,
    first_author_surname,
    format_entry,
    latex_escape,
    suggest_key,
    venue_proposals,
)
from bibcc.checkers.citation_keys import _KEY_PATTERN, abbreviate_venue
from bibcc.checkers.smart_protection import protect_terms
from bibcc.cli import main
from bibcc.venues import VenueLibrary
from conftest import MIAA_VENUES

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


XPLORE_EXPORT = "ieeexplore.ieee.org/rest/search/citation/format?recordIds="
SDLORA_TITLE = "SD-LoRA: Scalable Decoupled Low-Rank Adaptation for Class Incremental Learning"

DEFAULT_ROUTES = {
    "api.crossref.org/works/10.1109/TPAMI.2024.3429383": (_fixture("crossref_tpami.json"), None),
    "api.crossref.org/works/10.1007/978-3-031-72667-5_1": (_fixture("crossref_eccv.json"), None),
    "export.arxiv.org/api/query?id_list=2603.03818": (_fixture("arxiv_2603.03818.xml"), None),
    "semanticscholar.org/graph/v1/paper/search/match": (_fixture("s2_sdlora_match.json"), None),
    # Official BibTeX exports.
    XPLORE_EXPORT + "10599804": (_fixture("xplore_10599804.json"), None),
    "citation-needed.springer.com/v2/references/10.1007/978-3-031-72667-5_1": (
        _fixture("springer_eccv2024.bib"), None),
    "arxiv.org/bibtex/2603.03818": (_fixture("arxiv_2603.03818.bib"), None),
}


@pytest.fixture
def web(monkeypatch):
    fake = FakeWeb(dict(DEFAULT_ROUTES))
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
        ("hep-th/9901001v2", ("arxiv", "hep-th/9901001")),
        ("arXiv:math.GT/0309136", ("arxiv", "math/0309136")),
        ("https://arxiv.org/abs/cs/0112017v1", ("arxiv", "cs/0112017")),
        ("https://openreview.net/forum?id=x", ("url", "https://openreview.net/forum?id=x")),
        ("Three Scenarios for Continual Learning", ("title", "Three Scenarios for Continual Learning")),
    ],
)
def test_parse_identifier(text, expected):
    assert sources.parse_identifier(text) == expected


@pytest.mark.parametrize(
    "entry,expected",
    [
        ({"eprint": "hep-th/9901001"}, "hep-th/9901001"),
        ({"eprint": "2501.13198", "archiveprefix": "arXiv"}, "2501.13198"),
        ({"eprint": "hep-th/9901001", "archiveprefix": "PubMed"}, ""),
        ({"journal": "arXiv preprint hep-th/9901001"}, "hep-th/9901001"),
        ({"note": "arXiv:cs.LG/0112017v2"}, "cs/0112017"),
        ({"journal": "arXiv preprint arXiv:2501.13198"}, "2501.13198"),
        ({"journal": "arXiv preprint 2501.131981"}, ""),
        ({"journal": "Pattern Recognition"}, ""),
    ],
)
def test_entry_arxiv_id(entry, expected):
    assert sources.entry_arxiv_id(entry) == expected


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


def test_crossref_proceedings_journal_becomes_inproceedings():
    import json

    msg = json.loads(_fixture("crossref_tpami.json"))["message"]
    msg.update({
        "container-title": ["Proceedings of the AAAI Conference on Artificial Intelligence"],
        "published-print": {"date-parts": [[2025, 4]]},
    })
    record = sources.record_from_crossref(msg)
    assert record.entry_type == "inproceedings"
    assert record.fields["booktitle"] == "Proceedings of the AAAI Conference on Artificial Intelligence"
    assert "journal" not in record.fields and "issn" not in record.fields
    assert record.extra["landing_url"] == "https://ieeexplore.ieee.org/document/10599804/"


def _xplore_text(name: str = "xplore_10599804.json") -> str:
    import json

    return json.loads(_fixture(name))["data"].replace("\r\n", "\n")


def test_build_entry_completes_from_library_and_reports_differences(library):
    text = _xplore_text().replace("  year={2024},", "  year={2024},\n  publisher={Someone Else},")
    built = build_entry(official.Official("IEEE Xplore", "u", text), library)
    assert built.entry_type == "article"
    assert built.fields["issn"] == "1939-3539"  # added from the library
    assert built.fields["publisher"] == "Someone Else"  # never overwritten...
    assert any("publisher: official 'Someone Else' kept" in n for n in built.notes)  # ...but reported
    assert built.fields["pages"] == "9851--9873"
    assert "keywords" not in built.fields


def test_build_entry_adds_located_doi_when_official_has_none(library):
    built = build_entry(official.Official("Springer", "u", _fixture("springer_eccv2024.bib")), library,
                        doi="10.1007/978-3-031-72667-5_1")
    assert built.fields["doi"] == "10.1007/978-3-031-72667-5_1"
    assert built.fields["booktitle"] == "Computer Vision -- {ECCV} 2024"


def test_build_entry_interim_booktitle_only_gets_event_fields(library):
    import json

    notes = json.loads(_fixture("openreview_sdlora.json"))["notes"]
    bibtex = next(n for n in notes if n["id"] == "5U1rlpX68A")["content"]["_bibtex"]["value"]
    built = build_entry(official.Official("OpenReview", "u", bibtex, interim="openreview"), library)
    assert built.fields["booktitle"] == "The Thirteenth International Conference on Learning Representations"
    assert built.fields["venue"] == "Singapore"
    assert built.completion.interim_source == "openreview"
    assert any("interim BibTeX from OpenReview" in n for n in built.notes)


def test_venue_proposals_for_new_proceedings_link_interim_record(library):
    text = _xplore_text("xplore_11095062.json").replace("2025", "2026")
    xplore = official.Official("IEEE Xplore", "u", text)
    built = build_entry(xplore, library)
    assert built.completion.status == "missing"
    (proposal,) = venue_proposals(built, xplore, library, "Unified_Kumar_CVPR2026")
    assert proposal.name == "2026 IEEE/CVF Conference on Computer Vision and Pattern Recognition (CVPR)"
    assert proposal.collected_label == "from official BibTeX"
    # The library's CVPR 2026 record still has the CVF name; merging the proposal renames it.
    assert proposal.interim == {
        "cvf": ["Proceedings of the IEEE/CVF Conference on Computer Vision and Pattern Recognition (CVPR)"]
    }


def test_add_doi_uses_official_bibtex_and_library_fields(web, library, tmp_path):
    out = tmp_path / "added.bib"
    summary = add_papers(["10.1109/TPAMI.2024.3429383"], out, library, delay=0, log=lambda _: None)
    assert summary["added"] == [("10.1109/TPAMI.2024.3429383", "ClassIncremental_Zhou_TPAMI2024")]
    text = out.read_text()
    assert "@article{ClassIncremental_Zhou_TPAMI2024,\n  title     = {Class-Incremental" in text
    assert "  journal   = {{IEEE} Transactions on Pattern Analysis" in text
    entry = _entries(out)["ClassIncremental_Zhou_TPAMI2024"]
    assert entry["publisher"] == "IEEE"  # from the library
    assert entry["issn"] == "1939-3539"
    assert entry["doi"] == "10.1109/TPAMI.2024.3429383"
    assert entry["pages"] == "9851--9873"
    assert entry["number"] == "12"
    assert "keywords" not in entry
    assert entry["author"].startswith("Zhou, Da-Wei and Wang, Qi-Wei")
    assert any(XPLORE_EXPORT + "10599804" in call for call in web.calls)


def test_add_eccv_chapter_uses_springer_bibtex(web, library, tmp_path):
    out = tmp_path / "added.bib"
    add_papers(["10.1007/978-3-031-72667-5_1"], out, library, delay=0, log=lambda _: None)
    entry = _entries(out)["ScaleDreamer_Ma_ECCV2025"]
    assert entry["booktitle"] == "Computer Vision -- {ECCV} 2024"
    assert entry["venue"] == "Milan, Italy"  # from the library
    assert entry["editor"].startswith("Leonardis, Ale{\\v{s}} and Ricci, Elisa")
    assert entry["doi"] == "10.1007/978-3-031-72667-5_1"
    assert "abstract" not in entry


def test_add_arxiv_without_published_version_uses_arxiv_bibtex(web, library, tmp_path):
    out = tmp_path / "added.bib"
    add_papers(["https://arxiv.org/abs/2603.03818v2"], out, library, delay=0, log=lambda _: None)
    entry = _entries(out)["PretrainedVision_Liu_arXiv2026"]
    assert entry["ENTRYTYPE"] == "misc"
    assert entry["eprint"] == "2603.03818"
    assert entry["archiveprefix"] == "arXiv"
    assert entry["primaryclass"] == "cs.LG"
    assert entry["url"] == "https://arxiv.org/abs/2603.03818"
    assert entry["title"].startswith("Pretrained Vision-Language-Action Models Are")
    assert any("arXiv:2603.03818" in call for call in web.calls)  # looked for a published version


def test_add_title_of_iclr_paper_not_in_proceedings_gets_openreview_bibtex(web, library, tmp_path):
    web.routes["api2.openreview.net"] = (_fixture("openreview_sdlora.json"), None)
    out = tmp_path / "added.bib"
    lines = []
    add_papers([SDLORA_TITLE], out, library, delay=0, log=lines.append)
    entry = _entries(out)["SD-LoRA_Wu_ICLR2025"]
    assert entry["ENTRYTYPE"] == "inproceedings"
    assert entry["booktitle"] == "The Thirteenth International Conference on Learning Representations"
    assert entry["venue"] == "Singapore"
    assert entry["url"] == "https://openreview.net/forum?id=5U1rlpX68A"
    assert entry["title"].startswith("{SD-LoRA}: Scalable")
    assert any("interim BibTeX from OpenReview" in line for line in lines)
    assert any("proceedings.iclr.cc/paper_files/paper/2025" in call for call in web.calls)


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


def test_add_arxiv_published_at_iclr_uses_iclr_proceedings(web, library, tmp_path):
    import json

    title = "Generalization and Distributed Learning of GFlowNets"
    web.routes["id_list=2603.03818"] = (_fixture("arxiv_2603.03818.xml").replace(
        "Pretrained Vision-Language-Action Models are Surprisingly Resistant to Forgetting in Continual Learning",
        title), None)
    web.routes["paper/arXiv:2603.03818"] = (json.dumps({
        "title": title,
        "externalIds": {"DBLP": "conf/iclr/SilvaSRGKM25", "ArXiv": "2603.03818"},
        "authors": [{"name": "T. Silva"}],
    }), None)
    web.routes["proceedings.iclr.cc/paper_files/paper/2025/hash/"] = ("", None)
    web.routes["proceedings.iclr.cc/paper_files/paper/2025/file/000eba875068854d5ff003b1fa534cd6-Bibtex.bib"] = (
        _fixture("iclr_000eba87.bib"), None)
    web.routes["proceedings.iclr.cc/paper_files/paper/2025"] = (_fixture("iclr_2025_listing.html"), None)
    out = tmp_path / "added.bib"
    summary = add_papers(["2603.03818"], out, library, delay=0, log=lambda _: None)
    (key,) = [k for _, k in summary["added"]]
    entry = _entries(out)[key]
    assert key.endswith("_Silva_ICLR2025")
    assert entry["booktitle"] == "International Conference on Learning Representations"
    assert entry["author"].startswith("Silva, Tiago and Souza, Amauri")
    assert entry["venue"] == "Singapore"  # library record matched by its published name
    assert "{GFlowNets}" in entry["title"]


def test_add_title_uses_openreview_when_s2_is_rate_limited(web, library, tmp_path):
    web.routes["semanticscholar.org/graph/v1/paper/search/match"] = (None, "HTTP 429: Too Many Requests")
    web.routes["api2.openreview.net"] = (_fixture("openreview_sdlora.json"), None)
    out = tmp_path / "added.bib"
    add_papers([SDLORA_TITLE], out, library, delay=0, log=lambda _: None)
    entry = _entries(out)["SD-LoRA_Wu_ICLR2025"]
    assert entry["booktitle"] == "The Thirteenth International Conference on Learning Representations"
    assert entry["url"] == "https://openreview.net/forum?id=5U1rlpX68A"  # the conference's note
    assert entry["author"].startswith("Yichen Wu and Hongming Piao")


def test_add_paper_page_url(web, library, tmp_path):
    web.routes["proceedings.mlr.press/v235/abad-rocamora24a.html"] = (_fixture("pmlr_abad-rocamora24a.html"), None)
    out = tmp_path / "added.bib"
    summary = add_papers(["https://proceedings.mlr.press/v235/abad-rocamora24a.html"], out, library,
                         delay=0, log=lambda _: None)
    (key,) = [k for _, k in summary["added"]]
    assert key.endswith("_AbadRocamora_ICML2024")
    entry = _entries(out)[key]
    assert entry["booktitle"] == "Proceedings of the 41st International Conference on Machine Learning"
    assert entry["month"] == "July" or entry["month"].lower().startswith("jul")
    assert entry["day"] == "21--27"
    assert entry["venue"] == "Vienna, Austria"  # from the library
    assert "pdf" not in entry and "abstract" not in entry


def test_add_writes_empty_entry_when_publisher_blocks_downloads(web, library, tmp_path):
    import json

    msg = json.loads(_fixture("crossref_tpami.json"))["message"]
    msg.pop("resource")
    msg.update({
        "DOI": "10.1609/aaai.v39i1.30001",
        "title": ["Continual Learning for Everyone"],
        "container-title": ["Proceedings of the AAAI Conference on Artificial Intelligence"],
        "published-print": {"date-parts": [[2025, 4]]},
    })
    web.routes["api.crossref.org/works/10.1609/aaai.v39i1.30001"] = (json.dumps({"message": msg}), None)
    out = tmp_path / "added.bib"
    summary = add_papers(["10.1609/aaai.v39i1.30001"], out, library, delay=0, log=lambda _: None)
    ((_, key, reason),) = summary["empty"]
    assert key == "ContinualLearning_Zhou_AAAI2025"
    assert "AAAI blocks" in reason
    text = out.read_text()
    assert f"{EMPTY_ENTRY_MARK} could be downloaded" in text
    assert "%   doi:    10.1609/aaai.v39i1.30001\n" in text
    assert "%   get it: https://doi.org/10.1609/aaai.v39i1.30001\n" in text
    assert f"@inproceedings{{{key},\n}}" in text
    assert not any("ieeexplore" in c for c in web.calls)

    # The empty entry counts as present: adding the paper again is a duplicate.
    again = add_papers(["10.1609/aaai.v39i1.30001"], out, library, delay=0, log=lambda _: None)
    assert again["duplicates"][0][1].key == key
    assert out.read_text() == text


def test_add_download_error_writes_nothing(web, library, tmp_path):
    web.routes[XPLORE_EXPORT + "10599804"] = (None, "HTTP 503: Service Unavailable")
    out = tmp_path / "added.bib"
    summary = add_papers(["10.1109/TPAMI.2024.3429383"], out, library, delay=0, log=lambda _: None)
    assert summary["added"] == [] and "503" in summary["failed"][0][1]
    assert not out.exists()


def test_add_proposes_missing_venue_in_yaml(web, library, tmp_path):
    web.routes["aclanthology.org/2023.acl-long.1.bib"] = (_fixture("acl_2023.acl-long.1.bib").replace(
        "61st Annual Meeting", "99th Annual Meeting"), None)
    web.routes["api.crossref.org/works/10.18653"] = (None, "HTTP 404: Not Found")
    out = tmp_path / "added.bib"
    summary = add_papers(["https://aclanthology.org/2023.acl-long.1/"], out, library, delay=0,
                         log=lambda _: None)
    assert summary["added"]
    yaml_text = (tmp_path / ".bibcc" / "added.bib" / "missing_venues.yaml").read_text()
    assert "99th Annual Meeting" in yaml_text
    assert "Toronto, Canada" in yaml_text  # collected from the official BibTeX


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
        # The LaTeX and Unicode spellings of a name give the same key part.
        ("Zaj\\k{a}c, Micha{\\l}", "Zajac"),
        ("Zaj{\\k{a}}c, M.", "Zajac"),
        ("Zaj\u0105c, Micha\u0142", "Zajac"),
        ("{\\v{S}}imon, Petr", "Simon"),
        ("\\v Simon, Petr", "Simon"),
        ("\u0160imon, Petr", "Simon"),
        ("M{\\\"u}ller, A.", "Muller"),
        ("M\\\"{u}ller, A.", "Muller"),
        ("Ke{\\c{s}}ki{\\c{n}}, B.", "Keskin"),
        ("{\\O}stergaard, J.", "Ostergaard"),
        ("Lindstr{\\o}m, K.", "Lindstrom"),
        ("Stra{\\ss}e, H.", "Strasse"),
        ("Aaron {\\AA}berg", "Aberg"),
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


def test_key_venue_check_ignores_braces():
    from bibcc.checkers.citation_keys import _match_venue_abbreviation

    assert _match_venue_abbreviation(
        "TPAMI", None, "{IEEE} Transactions on Pattern Analysis and Machine Intelligence"
    ) is None
    assert _match_venue_abbreviation("TIP", None, "Pattern Recognition") is not None


def test_key_venue_check_matches_whole_words_and_any_case():
    from bibcc.checkers.citation_keys import _match_venue_abbreviation

    # "acl" inside "Oracle" and "pattern recognition" inside a longer name are not matches.
    assert _match_venue_abbreviation("ACL", "Proceedings of the Oracle Workshop", None) is not None
    assert _match_venue_abbreviation("PR", None, "Pattern Recognitionology") is not None
    assert _match_venue_abbreviation("PR", None, "Pattern Recognition Letters") is None
    # Wrong-case abbreviations are verified and the canonical spelling suggested.
    assert _match_venue_abbreviation("Neurips", "Advances in Neural Information Processing Systems", None) == (
        "write 'NeurIPS' instead of 'Neurips'"
    )
    assert _match_venue_abbreviation("cvpr", "International Conference on Machine Learning", None) is not None


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
        ("Proceedings of the Computer Vision and Pattern Recognition Conference (CVPR)", "CVPR"),
        ("Proceedings of the IEEE Conference on Computer Vision and Pattern Recognition", "CVPR"),
    ],
)
def test_abbreviate_venue(venue, expected):
    assert abbreviate_venue(venue) == expected


def test_protect_terms_groups_compounds():
    assert protect_terms("SD-LoRA for IEEE/CVF", ["SD", "LoRA", "IEEE", "CVF"]) == "{SD-LoRA} for {IEEE/CVF}"
    assert protect_terms("Already {BERT} and BERT", ["BERT"]) == "Already {BERT} and {BERT}"


@pytest.mark.parametrize(
    "title,expected",
    [
        ("{SD}-Lo{RA}: Scalable", "{SD-LoRA}: Scalable"),
        ("{BERT} and {GPT}s", "{BERT} and {GPTs}"),
        ("Ale{\\v{s}} {Foo Bar}", "Ale{\\v{s}} {Foo Bar}"),
    ],
)
def test_merge_word_braces(title, expected):
    from bibcc.adder import _merge_word_braces

    assert _merge_word_braces(title) == expected


def test_latex_escape_and_format_entry():
    assert latex_escape("R&D at 50% $a_b$ and x_y") == "R\\&D at 50\\% $a_b$ and x\\_y"
    assert latex_escape("already \\& done") == "already \\& done"
    text = format_entry("misc", "K_A_arXiv2020", {"title": "T", "year": "2020", "month": "6", "eprint": "1"})
    assert text == (
        "@misc{K_A_arXiv2020,\n  title  = {T},\n  year   = {2020},\n"
        "  month  = jun,\n  eprint = {1}\n}"
    )
    assert format_entry("misc", "K", {}) == "@misc{K,\n}"
    assert format_entry("misc", "K", {"title": ""}) == "@misc{K,\n}"
