"""
Find and download a paper's official BibTeX: the export offered by its
publisher or proceedings site.

``bibcc add`` and ``bibcc upgrade`` build entries from this BibTeX instead
of synthesizing them from API metadata.  The metadata sources
(:mod:`bibcc.sources`) only locate the paper: its DOI, venue, and year.
Routing, first match wins:

=====================================  ===========================================
Paper                                  Official BibTeX
=====================================  ===========================================
DOI 10.1109 (CVPR, ICCV, WACV, IEEE)   IEEE Xplore citation export
DOI 10.1007, 10.1038 (ECCV, Springer)  Springer citation export
DOI 10.18653 (ACL Anthology)           ``aclanthology.org/<id>.bib``
DOI 10.24963 (IJCAI)                   ``ijcai.org`` BibTeX export
DOI 10.1609, 10.1145, 10.1016          none: AAAI, ACM, and Elsevier block downloads
CVPR, ICCV, WACV not in Xplore yet     CVF Open Access (interim)
ECCV not on SpringerLink yet           none (ECVA pages have no BibTeX)
NeurIPS                                NeurIPS proceedings, else OpenReview (interim)
ICLR                                   ICLR proceedings (2024 on), else OpenReview
ICML, CoLLAs, other PMLR venues        PMLR, else OpenReview (interim)
arXiv preprint                         ``arxiv.org/bibtex/<id>``
=====================================  ===========================================

*Interim* BibTeX comes from a site the paper appears on before (or instead
of) the published proceedings; :attr:`Official.interim` names the source
(``cvf`` or ``openreview``) so ``bibcc upgrade`` can replace the entry once
the proceedings are out.  OpenReview is the official source for ICLR up to
2023, which has no other proceedings.

Listing pages (CVF, PMLR, NeurIPS, ICLR) are large, so each is fetched once
per run; :func:`clear_cache` empties the cache.

Usage:
    from bibcc.official import find_official, official_fields

    found = find_official(record)
    if found.official:
        entry_type, fields = official_fields(found.official.text)
"""

from __future__ import annotations

import html
import json
import re
import urllib.parse
from dataclasses import dataclass
from typing import Dict, Optional, Tuple

import bibtexparser

from bibcc import sources
from bibcc.bibedit import month_macro, page_range
from bibcc.checkers.citation_keys import abbreviate_venue
from bibcc.sources import (
    Record,
    clean_text,
    crossref_record,
    crossref_search,
    is_arxiv_doi,
    normalize_doi,
    openreview_search,
    titles_match,
)
from bibcc.venues import VenueLibrary

INTERIM_CVF = "cvf"
INTERIM_OPENREVIEW = "openreview"

# Publishers whose sites refuse automated BibTeX downloads.
BLOCKED_PREFIXES = {
    "10.1609": "AAAI",
    "10.1145": "the ACM Digital Library",
    "10.1016": "Elsevier",
}
CVF_FAMILIES = {"CVPR", "ICCV", "WACV", "CVPRW", "ICCVW", "WACVW"}
OPENREVIEW_FAMILIES = {"NeurIPS", "ICLR", "ICML"}
PMLR_FAMILIES = {"ICML", "CoLLAs", "AISTATS", "CoRL", "UAI", "COLT", "ACML", "CLeaR", "L4DC", "MIDL"}
ACL_FAMILIES = {"ACL", "EMNLP", "NAACL", "EACL", "COLING", "AACL", "Findings"}
_KNOWN_FAMILIES = CVF_FAMILIES | OPENREVIEW_FAMILIES | PMLR_FAMILIES | ACL_FAMILIES | {"ECCV", "AAAI", "IJCAI"}
# First ICLR year published on proceedings.iclr.cc; OpenReview is official before it.
ICLR_PROCEEDINGS_SINCE = 2024

# Fields of official exports that do not belong in a bibliography entry.
DROPPED_FIELDS = {"abstract", "keywords", "pdf", "file"}

_CVF = "https://openaccess.thecvf.com"
_PMLR = "https://proceedings.mlr.press"
_PROCEEDINGS_SITES = {"NeurIPS": "https://proceedings.neurips.cc", "ICLR": "https://proceedings.iclr.cc"}
_LISTING_TIMEOUT = 120

_cache: Dict[str, Tuple[Optional[str], Optional[str]]] = {}


@dataclass
class Official:
    """Where a paper's official BibTeX lives, and its text once downloaded."""

    provider: str
    url: str
    text: str = ""
    # "cvf" or "openreview" when this is interim BibTeX (proceedings not out yet).
    interim: str = ""


@dataclass
class OfficialLookup:
    """Outcome of looking for a paper's official BibTeX.

    ``official`` is set when it was found (``text`` is empty without
    downloading).  Otherwise ``reason`` says why there is none and
    ``manual_url`` where a person may get it; ``error`` is set instead when a
    site could not be reached, so trying again later may help.
    """

    official: Optional[Official] = None
    reason: str = ""
    manual_url: str = ""
    error: str = ""


def clear_cache() -> None:
    """Forget the listing pages fetched so far."""
    _cache.clear()


def _get(url: str, headers: Optional[Dict[str, str]] = None, timeout: int = 30, cache: bool = False):
    if cache and url in _cache:
        return _cache[url]
    # Looked up on the module so tests can replace sources.fetch_url.
    result = sources.fetch_url(url, headers=headers, timeout=timeout, retries=1)
    if cache:
        _cache[url] = result
    return result


def _bibtex_or_error(text: Optional[str], provider: str) -> Tuple[str, Optional[str]]:
    body = (text or "").strip()
    if not body.startswith("@"):
        return "", f"{provider} returned no BibTeX"
    return body, None


# ---------------------------------------------------------------- venues

_ORDINAL = (
    r"(?:(?:twenty|thirty|forty|fifty)-)?(?:first|second|third|fourth|fifth|sixth|seventh|eighth|ninth|"
    r"tenth|eleventh|twelfth|thirteenth|fourteenth|fifteenth|sixteenth|seventeenth|eighteenth|"
    r"nineteenth|twentieth|thirtieth|fortieth|fiftieth)"
)
_CVF_NAME = re.compile(r"^proceedings of the .*\((cvpr|iccv|wacv)\)( workshops)?$", re.IGNORECASE)
_OPENREVIEW_NAME = re.compile(
    rf"^(the )?{_ORDINAL} (annual )?(international )?conference on "
    r"(neural information processing systems|learning representations|machine learning)$",
    re.IGNORECASE,
)


def interim_source_of(booktitle: str, url: str = "", year: str = "") -> str:
    """``"cvf"`` or ``"openreview"`` if *booktitle* (or *url*) is that source's, else ``""``.

    CVF Open Access names start with "Proceedings of the" and end in the
    acronym; OpenReview names start with an ordinal ("The Thirteenth ...").
    ICLR before 2024 is not interim: OpenReview is its only proceedings.
    """
    text = " ".join(booktitle.replace("{", "").replace("}", "").split())
    if "openaccess.thecvf.com" in url or _CVF_NAME.match(text):
        return INTERIM_CVF
    if "openreview.net" in url or _OPENREVIEW_NAME.match(text):
        if "learning representations" in text.lower() and year.isdigit() and int(year) < ICLR_PROCEEDINGS_SINCE:
            return ""
        return INTERIM_OPENREVIEW
    return ""


def family_of(venue_name: str, year: str = "") -> str:
    """Conference family of a booktitle (see :func:`venue_family`)."""
    return venue_family(Record("inproceedings", {"booktitle": venue_name, "year": year}, source=""))[0]


def venue_family(record: Record) -> Tuple[str, str]:
    """``(family, conference year)`` of a record, e.g. ``("CVPRW", "2023")``.

    Taken from the DBLP key or OpenReview venue when the record has one,
    else from its booktitle or journal.
    """
    abbrev = record.extra.get("venue_abbrev", "")
    year = record.extra.get("venue_year", "") or record.fields.get("year", "")
    venue = record.fields.get("booktitle") or record.fields.get("journal") or ""
    if not abbrev and venue:
        abbrev = abbreviate_venue(venue)
        if re.search(r"\bworkshops?\b", venue, re.IGNORECASE) and abbrev in ("CVPR", "ICCV", "WACV"):
            abbrev += "W"
        if re.search(r"\blifelong learning agents\b", venue, re.IGNORECASE):
            abbrev = "CoLLAs"
        if re.match(r"^findings of\b", venue, re.IGNORECASE):
            abbrev = "Findings"
    canonical = {f.lower(): f for f in _KNOWN_FAMILIES}
    canonical["nips"] = "NeurIPS"
    return canonical.get(abbrev.lower(), abbrev), year


# ------------------------------------------------------------- providers


def _xplore(arnumber: str, download: bool) -> OfficialLookup:
    page = f"https://ieeexplore.ieee.org/document/{arnumber}"
    if not download:
        return OfficialLookup(official=Official("IEEE Xplore", page))
    url = (
        "https://ieeexplore.ieee.org/rest/search/citation/format"
        f"?recordIds={arnumber}&download-format=download-bibtex&lite=true"
    )
    # Without the Referer the export answers with an empty body.
    content, error = _get(url, headers={"Referer": page, "Accept": "application/json"})
    if error:
        return OfficialLookup(error=f"IEEE Xplore: {error}", manual_url=page)
    try:
        data = json.loads(content or "")
    except json.JSONDecodeError:
        return OfficialLookup(error="IEEE Xplore: unexpected response (bot protection?)", manual_url=page)
    text, error = _bibtex_or_error(str(data.get("data") or "").replace("\r\n", "\n"), "IEEE Xplore")
    if error:
        return OfficialLookup(error=error, manual_url=page)
    return OfficialLookup(official=Official("IEEE Xplore", page, text))


def _xplore_for_doi(doi: str, record: Optional[Record], download: bool) -> OfficialLookup:
    landing = record.extra.get("landing_url", "") if record else ""
    if "ieeexplore.ieee.org" not in landing:
        crossref, error = crossref_record(doi)
        if error and not error.startswith("DOI "):
            return OfficialLookup(error=f"CrossRef: {error}", manual_url=f"https://doi.org/{doi}")
        landing = crossref.extra.get("landing_url", "") if crossref else ""
    m = re.search(r"ieeexplore\.ieee\.org/document/(\d+)", landing)
    if not m:
        return OfficialLookup(reason="IEEE Xplore page not found", manual_url=f"https://doi.org/{doi}")
    return _xplore(m.group(1), download)


def _springer(doi: str, download: bool) -> OfficialLookup:
    page = f"https://link.springer.com/{doi}"
    if not download:
        return OfficialLookup(official=Official("Springer", page))
    url = (
        "https://citation-needed.springer.com/v2/references/"
        f"{urllib.parse.quote(doi, safe='/')}?format=bibtex&flavour=citation"
    )
    content, error = _get(url)
    if error and error.startswith("HTTP 404"):
        return OfficialLookup(reason="Springer has no BibTeX export for this DOI", manual_url=page)
    if error:
        return OfficialLookup(error=f"Springer: {error}", manual_url=page)
    text, error = _bibtex_or_error(content, "Springer")
    if error:
        return OfficialLookup(error=error, manual_url=page)
    return OfficialLookup(official=Official("Springer", page, text))


def _simple(provider: str, page: str, bib_url: str, download: bool, interim: str = "") -> OfficialLookup:
    if not download:
        return OfficialLookup(official=Official(provider, page, interim=interim))
    content, error = _get(bib_url)
    if error and error.startswith("HTTP 404"):
        return OfficialLookup(reason=f"{provider} has no BibTeX for this paper", manual_url=page)
    if error:
        return OfficialLookup(error=f"{provider}: {error}", manual_url=page)
    text, error = _bibtex_or_error(content, provider)
    if error:
        return OfficialLookup(error=error, manual_url=page)
    return OfficialLookup(official=Official(provider, page, text, interim=interim))


def _acl(anthology_id: str, download: bool) -> OfficialLookup:
    base = f"https://aclanthology.org/{anthology_id}"
    return _simple("ACL Anthology", f"{base}/", f"{base}.bib", download)


def _ijcai(year: str, number: str, download: bool) -> OfficialLookup:
    number = number.zfill(4)
    page = f"https://www.ijcai.org/proceedings/{year}/{number}"
    return _simple("IJCAI", page, f"https://www.ijcai.org/proceedings/{year}/bibtex/{number}", download)


def _arxiv(arxiv_id: str, download: bool) -> OfficialLookup:
    page = f"https://arxiv.org/abs/{arxiv_id}"
    return _simple("arXiv", page, f"https://arxiv.org/bibtex/{arxiv_id}", download)


# -------------------------------------------------------------- listings


def _bibref_text(block: str) -> str:
    """Text of a CVF ``bibref`` block; older pages break its lines with ``<br>`` tags."""
    text = re.sub(r"<br\s*/?>[ \t]*(?:\r?\n)?", "\n", block, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "", text)
    return html.unescape(text).strip()


def _cvf_entries(page: str) -> list[Tuple[str, str, str]]:
    """``(title, html_url, bibtex)`` for each paper of a CVF listing page."""
    out = []
    for chunk in page.split('<dt class="ptitle">')[1:]:
        link = re.search(r'<a href="([^"]+)">(.*?)</a>', chunk, re.S)
        bib = re.search(r'<div class="bibref[^"]*">(.*?)</div>', chunk, re.S)
        if link and bib:
            out.append((clean_text(link.group(2)), urllib.parse.urljoin(_CVF, link.group(1)),
                        _bibref_text(bib.group(1))))
    return out


def _cvf(title: str, family: str, year: str) -> OfficialLookup:
    if family not in ("CVPR", "ICCV", "WACV") or not year:
        return OfficialLookup(reason=f"CVF Open Access {family} pages are not searched")
    listing = f"{_CVF}/{family}{year}?day=all"
    content, error = _get(listing, timeout=_LISTING_TIMEOUT, cache=True)
    if error and error.startswith("HTTP 404"):
        return OfficialLookup(reason=f"CVF Open Access has no {family} {year} papers yet", manual_url=f"{_CVF}/menu")
    if error:
        return OfficialLookup(error=f"CVF Open Access: {error}", manual_url=listing)
    for paper_title, url, bibtex in _cvf_entries(content or ""):
        if titles_match(title, paper_title):
            return OfficialLookup(official=Official("CVF Open Access", url, bibtex, interim=INTERIM_CVF))
    return OfficialLookup(reason=f"not found in the CVF Open Access {family} {year} papers", manual_url=listing)


def _pmlr_volume(family: str, year: str) -> Tuple[Optional[str], Optional[str]]:
    content, error = _get(f"{_PMLR}/", timeout=_LISTING_TIMEOUT, cache=True)
    if error:
        return None, error
    for m in re.finditer(r'<a href="(v\d+)"><b>Volume \d+</b></a>\s*Proceedings of ([^<]+?)\s*</li>', content or ""):
        words = m.group(2).split()
        if words and words[0].lower() == family.lower() and year in words:
            return m.group(1), None
    return None, None


def _pmlr(title: str, family: str, year: str, download: bool) -> OfficialLookup:
    volume, error = _pmlr_volume(family, year)
    if error:
        return OfficialLookup(error=f"PMLR: {error}", manual_url=f"{_PMLR}/")
    if volume is None:
        return OfficialLookup(reason=f"PMLR has no {family} {year} volume yet", manual_url=f"{_PMLR}/")
    listing = f"{_PMLR}/{volume}/"
    content, error = _get(listing, timeout=_LISTING_TIMEOUT, cache=True)
    if error:
        return OfficialLookup(error=f"PMLR: {error}", manual_url=listing)
    for chunk in (content or "").split('<div class="paper">')[1:]:
        name = re.search(r'<p class="title">(.*?)</p>', chunk, re.S)
        link = re.search(r'href="([^"]+\.html)">abs</a>', chunk)
        if name and link and titles_match(title, clean_text(name.group(1))):
            return _pmlr_paper(urllib.parse.urljoin(listing, link.group(1)), download)
    return OfficialLookup(reason=f"not found in PMLR volume {volume[1:]} ({family} {year})", manual_url=listing)


def _pmlr_paper(url: str, download: bool) -> OfficialLookup:
    if not download:
        return OfficialLookup(official=Official("PMLR", url))
    content, error = _get(url)
    if error:
        return OfficialLookup(error=f"PMLR: {error}", manual_url=url)
    m = re.search(r'<code class="citecode" id="bibtex">(.*?)</code>', content or "", re.S)
    text, error = _bibtex_or_error(html.unescape(m.group(1)) if m else "", "PMLR")
    if error:
        return OfficialLookup(error=error, manual_url=url)
    return OfficialLookup(official=Official("PMLR", url, text))


def _proceedings_site(title: str, family: str, year: str, download: bool) -> OfficialLookup:
    site = _PROCEEDINGS_SITES[family]
    provider = f"{family} Proceedings"
    listing = f"{site}/paper_files/paper/{year}"
    content, error = _get(listing, timeout=_LISTING_TIMEOUT, cache=True)
    if error and error.startswith("HTTP 404"):
        return OfficialLookup(reason=f"the {family} {year} proceedings are not out yet", manual_url=site)
    if error:
        return OfficialLookup(error=f"{provider}: {error}", manual_url=listing)
    for m in re.finditer(r'<a title="paper title" href="([^"]+-Abstract[^"]*\.html)">(.*?)</a>', content or "", re.S):
        if titles_match(title, clean_text(m.group(2))):
            return _proceedings_paper(provider, urllib.parse.urljoin(site, m.group(1)), download)
    return OfficialLookup(reason=f"not in the {family} {year} proceedings yet", manual_url=listing)


def _proceedings_paper(provider: str, page: str, download: bool) -> OfficialLookup:
    if not download:
        return OfficialLookup(official=Official(provider, page))
    content, error = _get(page)
    if error:
        return OfficialLookup(error=f"{provider}: {error}", manual_url=page)
    m = re.search(r'href="([^"]+-Bibtex[^"]*\.bib)"', content or "")
    if m:
        bib_url = urllib.parse.urljoin(page, m.group(1))
    else:
        bib_url = re.sub(r"/hash/([0-9a-f]+)-Abstract[^/]*\.html$", r"/file/\1-Bibtex.bib", page)
    return _simple(provider, page, bib_url, download=True)


def _openreview(record: Record, title: str, family: str, year: str) -> OfficialLookup:
    bibtex = record.extra.get("bibtex", "")
    url = record.extra.get("openreview_url", "")
    if not bibtex:
        found, error = openreview_search(title, VenueLibrary())
        if error:
            return OfficialLookup(error=f"OpenReview: {error}", manual_url=url)
        if found:
            bibtex, url = found.extra.get("bibtex", ""), found.extra.get("openreview_url", "") or url
            if not bibtex:
                return OfficialLookup(
                    reason="OpenReview has the accepted paper but no BibTeX export for it", manual_url=url
                )
    if not bibtex:
        return OfficialLookup(reason="no accepted paper with this title on OpenReview", manual_url=url)
    official_here = family == "ICLR" and year.isdigit() and int(year) < ICLR_PROCEEDINGS_SINCE
    interim = "" if official_here or family not in OPENREVIEW_FAMILIES else INTERIM_OPENREVIEW
    return OfficialLookup(official=Official("OpenReview", url, bibtex.strip(), interim=interim))


# ---------------------------------------------------------------- lookup


def _by_doi(doi: str, record: Optional[Record], download: bool) -> Optional[OfficialLookup]:
    """Official BibTeX by DOI publisher, or None when the publisher is not routed."""
    prefix = doi.split("/", 1)[0]
    if prefix in BLOCKED_PREFIXES:
        return OfficialLookup(
            reason=f"{BLOCKED_PREFIXES[prefix]} blocks automated BibTeX downloads",
            manual_url=f"https://doi.org/{doi}",
        )
    if prefix == "10.1109":
        return _xplore_for_doi(doi, record, download)
    if prefix in ("10.1007", "10.1038"):
        return _springer(doi, download)
    m = re.match(r"^10\.18653/v1/(.+)$", doi, re.IGNORECASE)
    if m:
        return _acl(m.group(1), download)
    m = re.match(r"^10\.24963/ijcai\.(\d{4})/(\d+)$", doi, re.IGNORECASE)
    if m:
        return _ijcai(m.group(1), m.group(2), download)
    return None


def _first(*lookups) -> OfficialLookup:
    """First lookup that found something; else the last one, with earlier errors kept."""
    last = OfficialLookup()
    errors = []
    for make in lookups:
        last = make()
        if last.official:
            if errors:
                last.reason = "; ".join([*errors, last.reason]).strip("; ") + f"; used {last.official.provider} instead"
            return last
        if last.error:
            errors.append(last.error)
    if errors and not last.error:
        last.error = "; ".join(errors)
    return last


def find_official(record: Record, download: bool = True, interim: bool = True) -> OfficialLookup:
    """Locate (and by default download) the official BibTeX of *record*.

    With ``interim=False``, CVF Open Access and OpenReview are only used where
    they are the official source (ICLR before 2024).
    """
    title = record.fields.get("title", "")
    doi = normalize_doi(record.doi or record.fields.get("doi", ""))
    if is_arxiv_doi(doi):
        doi = ""
    family, year = venue_family(record)

    if doi:
        routed = _by_doi(doi, record, download)
        if routed is not None and routed.error and family in CVF_FAMILIES and interim:
            fallback = _cvf(title, family, year)
            if fallback.official:
                fallback.reason = f"IEEE Xplore failed ({routed.error}); used CVF Open Access instead"
                return fallback
        if routed is not None:
            return routed

    if family in CVF_FAMILIES:
        def from_xplore() -> OfficialLookup:
            found, error = crossref_search(title, prefix="10.1109")
            if found:
                return _xplore_for_doi(found.doi, found, download)
            return OfficialLookup(error=f"CrossRef: {error}" if error else "", reason="not in IEEE Xplore yet")
        steps = [from_xplore]
        if interim:
            steps.append(lambda: _cvf(title, family, year))
        return _first(*steps)

    if family == "ECCV":
        found, error = crossref_search(title, prefix="10.1007")
        if found:
            return _springer(found.doi, download)
        if error:
            return OfficialLookup(error=f"CrossRef: {error}")
        return OfficialLookup(reason="not on SpringerLink yet (the ECVA site has no BibTeX)",
                              manual_url="https://www.ecva.net/papers.php")

    if family in ("NeurIPS", "ICLR"):
        steps = []
        if family == "NeurIPS" or (year.isdigit() and int(year) >= ICLR_PROCEEDINGS_SINCE):
            steps.append(lambda: _proceedings_site(title, family, year, download))
        if interim or (family == "ICLR" and year.isdigit() and int(year) < ICLR_PROCEEDINGS_SINCE):
            steps.append(lambda: _openreview(record, title, family, year))
        return _first(*steps) if steps else OfficialLookup(reason=f"not in the {family} {year} proceedings yet")

    if family in PMLR_FAMILIES:
        steps = [lambda: _pmlr(title, family, year, download)]
        if family in OPENREVIEW_FAMILIES and interim:
            steps.append(lambda: _openreview(record, title, family, year))
        return _first(*steps)

    if family == "AAAI":
        return OfficialLookup(reason="AAAI blocks automated BibTeX downloads",
                              manual_url=f"https://doi.org/{doi}" if doi else "https://ojs.aaai.org/")
    if family in ("IJCAI", *ACL_FAMILIES) and not doi:
        prefix = "10.24963" if family == "IJCAI" else "10.18653"
        found, error = crossref_search(title, prefix=prefix)
        if found:
            routed = _by_doi(found.doi, found, download)
            if routed is not None:
                return routed
        if error:
            return OfficialLookup(error=f"CrossRef: {error}")

    if record.extra.get("bibtex"):
        return _openreview(record, title, family, year)

    if record.arxiv_id and record.entry_type == "misc" and not doi:
        return _arxiv(record.arxiv_id, download)

    if doi:
        publisher = record.fields.get("publisher") or f"DOI prefix {doi.split('/', 1)[0]}"
        return OfficialLookup(reason=f"no official BibTeX export is known for {publisher}",
                              manual_url=f"https://doi.org/{doi}")
    venue = f"{family} {year}".strip() or "this venue"
    return OfficialLookup(reason=f"no official BibTeX source is known for {venue}",
                          manual_url=record.fields.get("url", ""))


# ------------------------------------------------------------------- URLs

_URL_HINT = "pass the paper's DOI, arXiv ID, or title instead"


def official_from_url(url: str, download: bool = True) -> OfficialLookup:
    """Official BibTeX of the paper page at *url* (IEEE Xplore, CVF, PMLR, NeurIPS, ICLR, ACL, IJCAI)."""
    u = url.strip()
    m = re.search(r"ieeexplore\.ieee\.org/(?:abstract/)?document/(\d+)", u)
    if m:
        return _xplore(m.group(1), download)
    if "openaccess.thecvf.com" in u and re.search(r"/html/[^/]+\.html", u):
        content, error = _get(u)
        if error:
            return OfficialLookup(error=f"CVF Open Access: {error}", manual_url=u)
        m = re.search(r'<div class="bibref[^"]*">(.*?)</div>', content or "", re.S)
        text, error = _bibtex_or_error(_bibref_text(m.group(1)) if m else "", "CVF Open Access")
        if error:
            return OfficialLookup(error=error, manual_url=u)
        return OfficialLookup(official=Official("CVF Open Access", u, text, interim=INTERIM_CVF))
    if re.search(r"proceedings\.mlr\.press/v\d+/[^/]+\.html", u):
        return _pmlr_paper(u, download)
    m = re.match(r"^(?:https?://)?(?:www\.)?(papers\.nips\.cc|proceedings\.neurips\.cc|proceedings\.iclr\.cc)"
                 r"(?:/paper_files)?/paper/(\d{4}/hash/.+)$", u)
    if m:
        # Older NeurIPS links use the papers.nips.cc host or omit /paper_files; both redirect here.
        family = "ICLR" if "iclr" in m.group(1) else "NeurIPS"
        page = f"{_PROCEEDINGS_SITES[family]}/paper_files/paper/{m.group(2)}"
        return _proceedings_paper(f"{family} Proceedings", page, download)
    m = re.search(r"aclanthology\.org/([^/?#]+?)(?:\.pdf|\.bib)?/?$", u)
    if m:
        return _acl(m.group(1), download)
    m = re.search(r"ijcai\.org/proceedings/(\d{4})/(\d+)", u)
    if m:
        return _ijcai(m.group(1), m.group(2), download)
    if "openreview.net" in u:
        return OfficialLookup(error=f"OpenReview pages cannot be read automatically; {_URL_HINT}")
    return OfficialLookup(error=f"unsupported URL; {_URL_HINT}")


# ---------------------------------------------------------------- fields


def parse_bibtex(text: str) -> Tuple[str, Dict[str, str]]:
    """``(entry_type, raw fields)`` of the first entry in *text*; ``("", {})`` if none."""
    # Official keys can contain characters bibtexparser rejects (Springer uses the DOI).
    text = re.sub(r"^\s*@\s*(\w+)\s*([{(])\s*[^,\s]*\s*,", r"@\1\2OFFICIAL,", text.strip(), count=1)
    parser = bibtexparser.bparser.BibTexParser(common_strings=True)
    entries = bibtexparser.loads(text, parser=parser).entries
    if not entries:
        return "", {}
    entry = entries[0]
    fields = {k.lower(): v for k, v in entry.items() if k not in ("ID", "ENTRYTYPE")}
    return entry["ENTRYTYPE"].lower(), fields


def official_fields(text: str) -> Tuple[str, Dict[str, str]]:
    """``(entry_type, fields)`` of official BibTeX, cleaned for a bibliography.

    Drops :data:`DROPPED_FIELDS` and empty fields, puts each value on one
    line, writes page ranges with ``--``, and splits PMLR's ``21--27 Jul``
    month into ``month`` and ``day``.
    """
    entry_type, raw = parse_bibtex(text)
    fields: Dict[str, str] = {}
    for name, value in raw.items():
        value = " ".join(str(value).split())
        if name in DROPPED_FIELDS or not value:
            continue
        fields[name] = value
    if fields.get("pages"):
        fields["pages"] = page_range(fields["pages"])
    month = fields.get("month", "")
    m = re.match(r"^(\d{1,2}(?:\s*-+\s*\d{1,2})?)\s+([A-Za-z]+)\.?$", month)
    if m and month_macro(m.group(2)):
        fields["month"] = m.group(2)
        fields.setdefault("day", page_range(m.group(1).replace(" ", "")))
    return entry_type, fields


def record_from_official(official: Official) -> Optional[Record]:
    """A :class:`Record` with the identifying fields of downloaded official BibTeX."""
    entry_type, fields = official_fields(official.text)
    if not entry_type:
        return None
    plain = {k: clean_text(v.replace("{", "").replace("}", "")) for k, v in fields.items()}
    doi = normalize_doi(plain.get("doi", ""))
    record = Record(entry_type=entry_type, fields=plain, source=official.provider, doi=doi)
    record.arxiv_id = plain.get("eprint", "") if plain.get("archiveprefix", "").lower() == "arxiv" else ""
    return record
