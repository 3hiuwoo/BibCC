import json

import pytest

from bibcc import official, sources
from bibcc.official import (
    find_official,
    interim_source_of,
    next_for_error,
    next_step,
    official_fields,
    official_from_url,
    record_from_official,
    venue_family,
)
from bibcc.sources import Record
from test_add import FakeWeb, _fixture

CVPR_TITLE = "A Unified, Resilient, and Explainable Adversarial Patch Detector"
CVF_TITLE = "Towards Source-Free Machine Unlearning"
XPLORE_EXPORT = "ieeexplore.ieee.org/rest/search/citation/format?recordIds="


@pytest.fixture
def web(monkeypatch):
    fake = FakeWeb({})
    monkeypatch.setattr(sources, "fetch_url", fake)
    official.clear_cache()
    yield fake
    official.clear_cache()


def _record(entry_type="inproceedings", doi="", arxiv_id="", **fields):
    return Record(entry_type=entry_type, fields=fields, source="test", doi=doi, arxiv_id=arxiv_id)


def _crossref_items(*names):
    return json.dumps({"message": {"items": [json.loads(_fixture(n))["message"] for n in names]}})


# ----------------------------------------------------------------- parsing


def test_official_fields_cleans_xplore_export():
    text = json.loads(_fixture("xplore_11095062.json"))["data"].replace("\r\n", "\n")
    entry_type, fields = official_fields(text)
    assert entry_type == "inproceedings"
    assert fields["pages"] == "30387--30397"
    assert fields["booktitle"] == "2025 IEEE/CVF Conference on Computer Vision and Pattern Recognition (CVPR)"
    # Every field is kept, empty ones included.
    assert fields["keywords"].startswith("Computer vision;Scalability")
    assert fields["volume"] == "" and fields["number"] == ""


def test_official_fields_splits_pmlr_month_and_keeps_pdf():
    html = _fixture("pmlr_abad-rocamora24a.html")
    text = html.split('id="bibtex">')[1].split("</code>")[0]
    _, fields = official_fields(text)
    assert fields["month"] == "Jul" and fields["day"] == "21--27"
    assert fields["pdf"].endswith(".pdf") and fields["abstract"] == "Adversarial attacks in NLP."
    assert fields["series"] == "Proceedings of Machine Learning Research"


def test_official_fields_reads_springer_key_and_quotes():
    entry_type, fields = official_fields(_fixture("springer_eccv2024.bib"))
    assert entry_type == "inproceedings"
    assert fields["booktitle"] == "Computer Vision -- ECCV 2024"
    assert fields["author"].startswith("Ma, Zhiyuan and Wei, Yuxiang")
    assert fields["isbn"] == "978-3-031-72667-5"
    assert fields["abstract"].startswith("By leveraging")


def test_record_from_official_reads_arxiv_bibtex():
    record = record_from_official(official.Official("arXiv", "u", _fixture("arxiv_2603.03818.bib")))
    assert record.entry_type == "misc" and record.arxiv_id == "2603.03818"
    assert record.fields["title"].startswith("Pretrained Vision-Language-Action Models")


@pytest.mark.parametrize(
    "booktitle,url,year,expected",
    [
        ("Proceedings of the Computer Vision and Pattern Recognition Conference (CVPR)", "", "2025", "cvf"),
        ("Proceedings of the IEEE/CVF Winter Conference on Applications of Computer Vision (WACV)", "", "2024",
         "cvf"),
        ("Proceedings of the {IEEE/CVF} Conference on Computer Vision and Pattern Recognition (CVPR) Workshops",
         "", "2023", "cvf"),
        ("2025 IEEE/CVF Conference on Computer Vision and Pattern Recognition (CVPR)", "", "2025", ""),
        ("The Thirteenth International Conference on Learning Representations", "", "2025", "openreview"),
        ("The Eleventh International Conference on Learning Representations", "", "2023", ""),
        ("Forty-first International Conference on Machine Learning", "", "2024", "openreview"),
        ("The Thirty-eighth Annual Conference on Neural Information Processing Systems", "", "2024", "openreview"),
        ("Advances in Neural Information Processing Systems", "", "2024", ""),
        ("Some Workshop", "https://openreview.net/forum?id=x", "2025", "openreview"),
    ],
)
def test_interim_source_of(booktitle, url, year, expected):
    assert interim_source_of(booktitle, url=url, year=year) == expected


@pytest.mark.parametrize(
    "venue,expected",
    [
        ("2023 IEEE/CVF Conference on Computer Vision and Pattern Recognition Workshops (CVPRW)", "CVPRW"),
        ("Proceedings of the IEEE/CVF International Conference on Computer Vision (ICCV) Workshops", "ICCVW"),
        ("Proceedings of The 3rd Conference on Lifelong Learning Agents", "CoLLAs"),
        ("Findings of the Association for Computational Linguistics: ACL 2023", "Findings"),
        ("Computer Vision -- ECCV 2024", "ECCV"),
        ("Forty-first International Conference on Machine Learning", "ICML"),
    ],
)
def test_venue_family(venue, expected):
    assert venue_family(_record(booktitle=venue, year="2024"))[0] == expected


# ----------------------------------------------------------------- routing


def test_ieee_doi_downloads_xplore_export(web):
    web.routes["api.crossref.org/works/10.1109"] = (_fixture("crossref_cvpr2025.json"), None)
    web.routes[XPLORE_EXPORT + "11095062"] = (_fixture("xplore_11095062.json"), None)
    found = find_official(_record(doi="10.1109/CVPR52734.2025.02829", title=CVPR_TITLE))
    assert found.official.provider == "IEEE Xplore"
    assert found.official.url == "https://ieeexplore.ieee.org/document/11095062"
    assert found.official.text.startswith("@INPROCEEDINGS{11095062,\n")
    assert not found.official.interim
    export = next(c for c in web.calls if XPLORE_EXPORT in c)
    assert "download-bibtex" in export


def test_cvpr_without_doi_finds_xplore_through_crossref_search(web):
    web.routes["query.bibliographic"] = (_crossref_items("crossref_cvpr2025.json"), None)
    web.routes[XPLORE_EXPORT + "11095062"] = (_fixture("xplore_11095062.json"), None)
    record = _record(title=CVPR_TITLE, year="2025",
                     booktitle="Proceedings of the Computer Vision and Pattern Recognition Conference (CVPR)")
    found = find_official(record)
    assert found.official.provider == "IEEE Xplore"
    assert any("filter=prefix:10.1109" in c for c in web.calls)


def test_cvpr_not_in_xplore_gets_interim_cvf_bibtex(web):
    web.routes["query.bibliographic"] = (json.dumps({"message": {"items": []}}), None)
    web.routes["openaccess.thecvf.com/CVPR2025?day=all"] = (_fixture("cvf_cvpr2025_listing.html"), None)
    record = _record(title=CVF_TITLE, year="2025", booktitle="CVPR 2025")
    found = find_official(record)
    assert found.official.provider == "CVF Open Access"
    assert found.official.interim == "cvf"
    assert found.official.url.endswith("Ahmed_Towards_Source-Free_Machine_Unlearning_CVPR_2025_paper.html")
    assert "Ahmed_2025_CVPR" in found.official.text
    # Without interim sources (as for upgrade) there is nothing yet.
    assert next_step(found) == ""
    later = find_official(record, interim=False)
    assert later.official is None and next_step(later) == "wait"


def test_cvpr_with_no_cvf_listing_yet_waits(web):
    web.routes["query.bibliographic"] = (json.dumps({"message": {"items": []}}), None)
    web.routes["openaccess.thecvf.com/CVPR2026?day=all"] = (None, "HTTP 404: Not Found")
    found = find_official(_record(title=CVF_TITLE, year="2026", booktitle="CVPR 2026"))
    assert found.official is None and found.waiting and next_step(found) == "wait"


def test_cvpr_in_neither_xplore_nor_cvf_waits_for_xplore(web):
    web.routes["query.bibliographic"] = (json.dumps({"message": {"items": []}}), None)
    web.routes["openaccess.thecvf.com/CVPR2025?day=all"] = (_fixture("cvf_cvpr2025_listing.html"), None)
    found = find_official(_record(title="A Paper the Listing Lacks", year="2025", booktitle="CVPR 2025"))
    # IEEE Xplore may still add it, so it counts as waiting rather than lost.
    assert found.official is None and next_step(found) == "wait"


def test_cvf_listing_is_fetched_once(web):
    web.routes["query.bibliographic"] = (json.dumps({"message": {"items": []}}), None)
    web.routes["openaccess.thecvf.com/CVPR2025?day=all"] = (_fixture("cvf_cvpr2025_listing.html"), None)
    for title in (CVF_TITLE, "Towards Source-Free Machine Unlearning"):
        find_official(_record(title=title, year="2025", booktitle="CVPR 2025"))
    assert sum("CVPR2025?day=all" in c for c in web.calls) == 1


def test_xplore_failure_falls_back_to_cvf(web):
    web.routes["api.crossref.org/works/10.1109"] = (_fixture("crossref_cvpr2025.json"), None)
    web.routes[XPLORE_EXPORT] = ("<html>blocked</html>", None)
    listing = _fixture("cvf_cvpr2025_listing.html").replace(CVF_TITLE, CVPR_TITLE)
    web.routes["openaccess.thecvf.com/CVPR2025?day=all"] = (listing, None)
    record = _record(doi="10.1109/CVPR52734.2025.02829", title=CVPR_TITLE, year="2025",
                     booktitle="2025 IEEE/CVF Conference on Computer Vision and Pattern Recognition (CVPR)")
    found = find_official(record)
    assert found.official.provider == "CVF Open Access"
    assert "IEEE Xplore failed" in found.reason


def test_springer_doi(web):
    web.routes["citation-needed.springer.com/v2/references/10.1007/978-3-031-72667-5_1"] = (
        _fixture("springer_eccv2024.bib"), None)
    found = find_official(_record(doi="10.1007/978-3-031-72667-5_1"))
    assert found.official.provider == "Springer"
    assert found.official.url == "https://link.springer.com/10.1007/978-3-031-72667-5_1"


def test_eccv_not_on_springerlink_has_no_official_bibtex(web):
    web.routes["query.bibliographic"] = (json.dumps({"message": {"items": []}}), None)
    found = find_official(_record(title="Some ECCV Paper", year="2026", booktitle="ECCV 2026"))
    assert found.official is None and not found.error
    assert "SpringerLink" in found.reason and "ecva.net" in found.manual_url
    assert next_step(found) == "wait"


@pytest.mark.parametrize("prefix,publisher", [("10.1609", "AAAI"), ("10.1145", "ACM"), ("10.1016", "Elsevier")])
def test_blocked_publishers(web, prefix, publisher):
    found = find_official(_record(doi=f"{prefix}/x.1"))
    assert found.official is None and not found.error
    assert publisher in found.reason and found.manual_url == f"https://doi.org/{prefix}/x.1"
    assert next_step(found) == "by hand"
    assert web.calls == []


def test_neurips_proceedings(web):
    web.routes["proceedings.neurips.cc/paper_files/paper/2024/hash/"] = ("", None)
    web.routes["proceedings.neurips.cc/paper_files/paper/2024/file/000f947dcaff8fbffcc3f53a1314f358-Bibtex.bib"] = (
        _fixture("neurips_000f947d.bib"), None)
    web.routes["proceedings.neurips.cc/paper_files/paper/2024"] = (_fixture("neurips_2024_listing.html"), None)
    title = "MicroAdam: Accurate Adaptive Optimization with Low Space Overhead and Provable Convergence"
    found = find_official(_record(title=title, year="2024",
                                  booktitle="Advances in Neural Information Processing Systems"))
    assert found.official.provider == "NeurIPS Proceedings"
    assert found.official.url.endswith("000f947dcaff8fbffcc3f53a1314f358-Abstract-Conference.html")
    assert "NEURIPS2024_000f947d" in found.official.text


def test_iclr_2025_not_in_proceedings_uses_openreview(web):
    web.routes["proceedings.iclr.cc/paper_files/paper/2025"] = (_fixture("iclr_2025_listing.html"), None)
    web.routes["api2.openreview.net"] = (_fixture("openreview_sdlora.json"), None)
    title = "SD-LoRA: Scalable Decoupled Low-Rank Adaptation for Class Incremental Learning"
    found = find_official(_record(title=title, year="2025", booktitle="ICLR 2025"))
    assert found.official.provider == "OpenReview"
    assert found.official.interim == "openreview"
    assert found.official.url == "https://openreview.net/forum?id=5U1rlpX68A"
    assert "wu2025sdlora" in found.official.text  # the conference's note, not DBLP's import


def test_iclr_2023_openreview_is_official(web):
    notes = json.loads(_fixture("openreview_sdlora.json"))
    for note in notes["notes"]:
        note["content"]["venue"]["value"] = note["content"]["venue"]["value"].replace("2025", "2023")
    web.routes["api2.openreview.net"] = (json.dumps(notes), None)
    title = "SD-LoRA: Scalable Decoupled Low-Rank Adaptation for Class Incremental Learning"
    found = find_official(_record(title=title, year="2023", booktitle="ICLR 2023"))
    assert found.official.provider == "OpenReview" and not found.official.interim
    assert not any("proceedings.iclr.cc" in c for c in web.calls)


def test_icml_from_pmlr(web):
    web.routes["proceedings.mlr.press/v235/abad-rocamora24a.html"] = (_fixture("pmlr_abad-rocamora24a.html"), None)
    web.routes["proceedings.mlr.press/v235/"] = (_fixture("pmlr_v235.html"), None)
    web.routes["proceedings.mlr.press/"] = (_fixture("pmlr_index.html"), None)
    title = "Revisiting Character-level Adversarial Attacks for Language Models"
    found = find_official(_record(title=title, year="2024", booktitle="Forty-first International Conference on "
                                                                        "Machine Learning"))
    assert found.official.provider == "PMLR"
    assert found.official.url == "https://proceedings.mlr.press/v235/abad-rocamora24a.html"
    assert found.official.text.startswith("@InProceedings{pmlr-v235-abad-rocamora24a,")
    # Without downloading, only the page is reported.
    official.clear_cache()
    lookup = find_official(_record(title=title, year="2024", booktitle="ICML 2024"), download=False)
    assert lookup.official.url.endswith("abad-rocamora24a.html") and lookup.official.text == ""


def test_pmlr_volume_not_out_yet(web):
    web.routes["proceedings.mlr.press/"] = (_fixture("pmlr_index.html"), None)
    found = find_official(_record(title="T", year="2027", booktitle="ICML 2027"), interim=False)
    assert found.official is None and "no ICML 2027 volume" in found.reason
    assert next_step(found) == "wait"


def test_acl_and_ijcai_dois(web):
    web.routes["aclanthology.org/2023.acl-long.1.bib"] = (_fixture("acl_2023.acl-long.1.bib"), None)
    web.routes["ijcai.org/proceedings/2025/bibtex/0001"] = (_fixture("ijcai_2025_0001.bib"), None)
    acl = find_official(_record(doi="10.18653/v1/2023.acl-long.1"))
    assert acl.official.provider == "ACL Anthology"
    assert acl.official.url == "https://aclanthology.org/2023.acl-long.1/"
    ijcai = find_official(_record(doi="10.24963/ijcai.2025/1"))
    assert ijcai.official.provider == "IJCAI"
    assert ijcai.official.url == "https://www.ijcai.org/proceedings/2025/0001"


def test_arxiv_preprint(web):
    web.routes["arxiv.org/bibtex/2603.03818"] = (_fixture("arxiv_2603.03818.bib"), None)
    found = find_official(_record("misc", arxiv_id="2603.03818", title="T", year="2026"))
    assert found.official.provider == "arXiv"
    assert found.official.url == "https://arxiv.org/abs/2603.03818"


def test_network_errors_are_errors_not_reasons(web):
    web.routes["citation-needed.springer.com"] = (None, "HTTP 503: Service Unavailable")
    found = find_official(_record(doi="10.1007/978-3-031-72667-5_1"))
    assert found.official is None and "503" in found.error
    assert next_step(found) == "retry"


@pytest.mark.parametrize(
    "error,expected",
    [
        ("not found (Semantic Scholar: HTTP 429: Too Many Requests)", "retry"),
        ("Network error: [Errno 8] nodename nor servname provided", "retry"),
        ("Request timed out", "retry"),
        ("IEEE Xplore: unexpected response (bot protection?)", "retry"),
        ("not found (no source has a paper with this exact title)", "check"),
        ("key CLE_Zhou_AAAI2025 from the manifest is already used in refs.bib", "check"),
    ],
)
def test_next_for_error(error, expected):
    assert next_for_error(error) == expected


# ------------------------------------------------------------------- URLs


def test_official_from_url(web):
    web.routes["proceedings.mlr.press/v235/abad-rocamora24a.html"] = (_fixture("pmlr_abad-rocamora24a.html"), None)
    web.routes[XPLORE_EXPORT + "11095062"] = (_fixture("xplore_11095062.json"), None)
    assert official_from_url("https://proceedings.mlr.press/v235/abad-rocamora24a.html").official.provider == "PMLR"
    assert official_from_url("https://ieeexplore.ieee.org/document/11095062/").official.provider == "IEEE Xplore"
    assert "OpenReview" in official_from_url("https://openreview.net/forum?id=x").error
    assert "unsupported URL" in official_from_url("https://example.com/paper").error


def test_official_from_url_reads_legacy_cvf_page_with_br_tags(web):
    page = "https://openaccess.thecvf.com/content_iccv_2017/html/He_Mask_R-CNN_ICCV_2017_paper.html"
    web.routes["He_Mask_R-CNN_ICCV_2017_paper.html"] = (_fixture("cvf_iccv2017_paper.html"), None)
    found = official_from_url(page)
    assert found.official.provider == "CVF Open Access" and found.official.interim == "cvf"
    assert "<br" not in found.official.text
    assert found.official.text.startswith("@InProceedings{He_2017_ICCV,\nauthor = ")
    entry_type, fields = official_fields(found.official.text)
    assert entry_type == "inproceedings"
    assert fields["title"] == "Mask R-CNN & Friends"
    assert fields["author"].startswith("He, Kaiming and Gkioxari, Georgia")
    assert fields["year"] == "2017"


NEURIPS_HASH = "000f947dcaff8fbffcc3f53a1314f358"
NEURIPS_PAGE = f"https://proceedings.neurips.cc/paper_files/paper/2021/hash/{NEURIPS_HASH}-Abstract.html"


@pytest.mark.parametrize(
    "url",
    [
        f"https://proceedings.neurips.cc/paper/2021/hash/{NEURIPS_HASH}-Abstract.html",
        f"https://papers.nips.cc/paper/2021/hash/{NEURIPS_HASH}-Abstract.html",
        f"https://papers.nips.cc/paper_files/paper/2021/hash/{NEURIPS_HASH}-Abstract.html",
        f"http://papers.nips.cc/paper/2021/hash/{NEURIPS_HASH}-Abstract.html",
        NEURIPS_PAGE,
    ],
)
def test_official_from_url_normalizes_legacy_neurips_urls(web, url):
    web.routes["proceedings.neurips.cc/paper_files/paper/2021/hash/"] = ("", None)
    web.routes[f"proceedings.neurips.cc/paper_files/paper/2021/file/{NEURIPS_HASH}-Bibtex.bib"] = (
        _fixture("neurips_000f947d.bib"), None)
    found = official_from_url(url)
    assert found.official.provider == "NeurIPS Proceedings"
    assert found.official.url == NEURIPS_PAGE
    assert found.official.text.startswith("@")
    assert web.calls and all(c.startswith("https://proceedings.neurips.cc/paper_files/paper/2021/") for c in web.calls)


def test_official_from_url_keeps_conference_suffix_and_skips_download(web):
    url = f"https://papers.nips.cc/paper/2024/hash/{NEURIPS_HASH}-Abstract-Conference.html"
    found = official_from_url(url, download=False)
    assert found.official.url == (
        f"https://proceedings.neurips.cc/paper_files/paper/2024/hash/{NEURIPS_HASH}-Abstract-Conference.html")
    assert web.calls == []
    web.routes["proceedings.neurips.cc/paper_files/paper/2024/hash/"] = ("", None)
    web.routes[f"proceedings.neurips.cc/paper_files/paper/2024/file/{NEURIPS_HASH}-Bibtex.bib"] = (
        _fixture("neurips_000f947d.bib"), None)
    assert official_from_url(url).official.provider == "NeurIPS Proceedings"


# --------------------------------------------------------------- OpenReview

SDLORA = "SD-LoRA: Scalable Decoupled Low-Rank Adaptation for Class Incremental Learning"


def _openreview_notes(drop_bibtex=False):
    notes = json.loads(_fixture("openreview_sdlora.json"))
    if drop_bibtex:
        for note in notes["notes"]:
            note["content"].pop("_bibtex", None)
    return json.dumps(notes)


def _iclr_2025_record():
    return _record(title=SDLORA, year="2025", booktitle="ICLR 2025")


def test_openreview_no_matching_paper_is_a_reason(web):
    web.routes["proceedings.iclr.cc/paper_files/paper/2025"] = (_fixture("iclr_2025_listing.html"), None)
    web.routes["api2.openreview.net"] = (json.dumps({"notes": []}), None)
    found = find_official(_iclr_2025_record())
    assert found.official is None and not found.error
    assert found.reason == "no accepted paper with this title on OpenReview"


def test_openreview_accepted_paper_without_bibtex(web):
    web.routes["proceedings.iclr.cc/paper_files/paper/2025"] = (_fixture("iclr_2025_listing.html"), None)
    web.routes["api2.openreview.net"] = (_openreview_notes(drop_bibtex=True), None)
    found = find_official(_iclr_2025_record())
    assert found.official is None and not found.error
    assert found.reason == "OpenReview has the accepted paper but no BibTeX export for it"
    assert found.manual_url == "https://openreview.net/forum?id=5U1rlpX68A"


@pytest.mark.parametrize(
    "response",
    [
        (None, "HTTP 403: Forbidden"),
        (None, "HTTP 429: Too Many Requests"),
        (None, "Network error: [Errno 8] nodename nor servname provided, or not known"),
        ("<!DOCTYPE html><html>challenge</html>", None),
    ],
)
def test_openreview_blocked_or_unreachable_is_an_error(web, response):
    web.routes["proceedings.iclr.cc/paper_files/paper/2025"] = (_fixture("iclr_2025_listing.html"), None)
    web.routes["api2.openreview.net"] = response
    found = find_official(_iclr_2025_record())
    assert found.official is None
    assert found.error.startswith("OpenReview: ")
