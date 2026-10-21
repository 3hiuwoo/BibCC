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

The family facts behind this routing (which families PMLR publishes, the
ICLR proceedings year, the DOI prefixes, and the blocked publishers) live in
the provider table of :mod:`bibcc.families`, which a venue library's family
records can extend; this module holds only the code for each provider.

*Interim* BibTeX comes from a site the paper appears on before (or instead
of) the published proceedings; :attr:`Official.interim` names the source
(``cvf`` or ``openreview``) so ``bibcc upgrade`` can replace the entry once
the proceedings are out.  OpenReview is the official source for ICLR up to
2023, which has no other proceedings.

Listing pages (CVF, PMLR, NeurIPS, ICLR) are large, so each is fetched once
per run; :func:`clear_cache` empties the cache.  A paper's own BibTeX
export is also kept on disk for later runs (see :mod:`bibcc.cache`).

Usage:
    from bibcc.official import find_official, official_fields

    found = find_official(record)
    if found.official:
        entry_type, fields = official_fields(found.official.text)
"""

from __future__ import annotations

import datetime
import html
import json
import re
import urllib.parse
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional, Tuple

import bibtexparser

from bibcc import cache as disk_cache
from bibcc import sources
from bibcc.bibedit import month_macro, page_range
from bibcc.families import (
    ACL,
    BLOCKED,
    IJCAI,
    OPENREVIEW,
    PMLR,
    PROCEEDINGS_SITE,
    SPRINGER,
    XPLORE,
    Registry,
    Spec,
    registry,
)
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
from bibcc.venues import VenueLibrary, is_conference_journal

INTERIM_CVF = "cvf"
INTERIM_OPENREVIEW = "openreview"

_CVF = "https://openaccess.thecvf.com"
_CVF_LISTED = ("CVPR", "ICCV", "WACV")  # families with a CVF Open Access listing page
_PMLR = "https://proceedings.mlr.press"
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
    site could not be reached, so trying again later may help.  ``waiting``
    says that the official BibTeX does not exist yet (the proceedings are
    not out), so no one can get it now.
    """

    official: Optional[Official] = None
    reason: str = ""
    manual_url: str = ""
    error: str = ""
    waiting: bool = False


# What to do next about a paper or entry; the ``next`` column of the add, upgrade, and published reports.
NEXT_RETRY = "retry"  # a site could not be reached: run the command again later
NEXT_BY_HAND = "by hand"  # the official BibTeX exists but BibCC cannot download it: get it from the URL
NEXT_WAIT = "wait"  # no official BibTeX exists yet: `bibcc upgrade` picks it up once it is out
NEXT_CHECK = "check"  # the paper was not found: check the identifier
NEXT_UPGRADE = "upgrade"  # a better official BibTeX can be downloaded now: run `bibcc upgrade`

NEXT_VALUES = (NEXT_RETRY, NEXT_BY_HAND, NEXT_WAIT, NEXT_CHECK, NEXT_UPGRADE)
"""Every value of the ``next`` column, in report order."""


def next_step(lookup: OfficialLookup) -> str:
    """The ``next`` value for a lookup that found no official BibTeX (``""`` if it found one)."""
    if lookup.official is not None:
        return ""
    if lookup.error:
        return NEXT_RETRY
    return NEXT_WAIT if lookup.waiting else NEXT_BY_HAND


_TRANSIENT = re.compile(r"Network error|timed out|HTTP (?:429|5\d\d)|ConnectionResetError|SSLError|bot protection",
                        re.I)


def next_for_error(error: str) -> str:
    """The ``next`` value for a paper that failed with *error*: retry for network trouble, else check."""
    return NEXT_RETRY if _TRANSIENT.search(error or "") else NEXT_CHECK


def clear_cache() -> None:
    """Forget the listing pages fetched so far."""
    _cache.clear()


def _get(url: str, headers: Optional[Dict[str, str]] = None, timeout: int = 30, cache: bool = False,
         keep: Optional[Callable[[str], bool]] = None):
    """``(content, error)`` of *url*.

    *cache* keeps the answer for the rest of the run (listing pages).
    *keep* says whether an answer is a paper's BibTeX export worth keeping
    on disk for later runs; such answers are read from the disk cache first.
    """
    if cache and url in _cache:
        return _cache[url]
    if keep is not None:
        stored = disk_cache.get(url)
        if stored is not None:
            return stored, None
    # Looked up on the module so tests can replace sources.fetch_url.
    result = sources.fetch_url(url, headers=headers, timeout=timeout, retries=1)
    if cache:
        _cache[url] = result
    if keep is not None and not result[1] and result[0] and keep(result[0]):
        disk_cache.put(url, result[0])
    return result


def _is_bibtex(text: str) -> bool:
    return text.strip().startswith("@")


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


def interim_source_of(booktitle: str, url: str = "", year: str = "",
                      library: Optional[VenueLibrary] = None) -> str:
    """``"cvf"`` or ``"openreview"`` if *booktitle* (or *url*) is that source's, else ``""``.

    CVF Open Access names start with "Proceedings of the" and end in the
    acronym; OpenReview names start with an ordinal ("The Thirteenth ...").
    A family whose ``interim_since`` year is later than *year* (ICLR before
    2024) is not interim: OpenReview is its only proceedings.
    """
    text = " ".join(booktitle.replace("{", "").replace("}", "").split())
    if "openaccess.thecvf.com" in url or _CVF_NAME.match(text):
        return INTERIM_CVF
    if "openreview.net" in url or _OPENREVIEW_NAME.match(text):
        if year and registry(library).interim_is_official(text, year, library):
            return ""
        return INTERIM_OPENREVIEW
    return ""


def family_of(venue_name: str, year: str = "", library: Optional[VenueLibrary] = None) -> str:
    """Conference family of a booktitle (see :func:`venue_family`)."""
    return venue_family(Record("inproceedings", {"booktitle": venue_name, "year": year}, source=""), library)[0]


def venue_family(record: Record, library: Optional[VenueLibrary] = None) -> Tuple[str, str]:
    """``(family, conference year)`` of a record, e.g. ``("CVPRW", "2023")``.

    Taken from the DBLP key or OpenReview venue when the record has one,
    else from its booktitle or journal (see :meth:`bibcc.families.Registry.acronym_of`).
    """
    reg = registry(library)
    abbrev = record.extra.get("venue_abbrev", "")
    year = record.extra.get("venue_year", "") or record.fields.get("year", "")
    venue = record.fields.get("booktitle") or record.fields.get("journal") or ""
    if not abbrev and venue:
        abbrev = reg.acronym_of(venue, library)
    return reg.canonical(abbrev), year


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
    content, error = _get(url, headers={"Referer": page, "Accept": "application/json"},
                          keep=lambda text: '"data"' in text and "@" in text)
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
    remembered = disk_cache.get(f"xplore-document:{doi.lower()}")
    if remembered:
        return _xplore(remembered, download)
    landing = record.extra.get("landing_url", "") if record else ""
    if "ieeexplore.ieee.org" not in landing:
        crossref, error = crossref_record(doi)
        if error and not error.startswith("DOI "):
            return OfficialLookup(error=f"CrossRef: {error}", manual_url=f"https://doi.org/{doi}")
        landing = crossref.extra.get("landing_url", "") if crossref else ""
    m = re.search(r"ieeexplore\.ieee\.org/document/(\d+)", landing)
    if not m:
        return OfficialLookup(reason="IEEE Xplore page not found", manual_url=f"https://doi.org/{doi}")
    disk_cache.put(f"xplore-document:{doi.lower()}", m.group(1))
    return _xplore(m.group(1), download)


def _springer(doi: str, download: bool) -> OfficialLookup:
    page = f"https://link.springer.com/{doi}"
    if not download:
        return OfficialLookup(official=Official("Springer", page))
    url = (
        "https://citation-needed.springer.com/v2/references/"
        f"{urllib.parse.quote(doi, safe='/')}?format=bibtex&flavour=citation"
    )
    content, error = _get(url, keep=_is_bibtex)
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
    content, error = _get(bib_url, keep=_is_bibtex)
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
    if family not in _CVF_LISTED or not year:
        return OfficialLookup(reason=f"CVF Open Access {family} pages are not searched")
    listing = f"{_CVF}/{family}{year}?day=all"
    content, error = _get(listing, timeout=_LISTING_TIMEOUT, cache=True)
    if error and error.startswith("HTTP 404"):
        return OfficialLookup(reason=f"CVF Open Access has no {family} {year} papers yet", manual_url=f"{_CVF}/menu",
                              waiting=True)
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
        return OfficialLookup(reason=f"PMLR has no {family} {year} volume yet", manual_url=f"{_PMLR}/", waiting=True)
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
    content, error = _get(url, keep=lambda text: 'id="bibtex"' in text)
    if error:
        return OfficialLookup(error=f"PMLR: {error}", manual_url=url)
    m = re.search(r'<code class="citecode" id="bibtex">(.*?)</code>', content or "", re.S)
    text, error = _bibtex_or_error(html.unescape(m.group(1)) if m else "", "PMLR")
    if error:
        return OfficialLookup(error=error, manual_url=url)
    return OfficialLookup(official=Official("PMLR", url, text))


def _proceedings_site(title: str, family: str, year: str, download: bool, site: str) -> OfficialLookup:
    site = site.rstrip("/")
    provider = f"{family} Proceedings"
    listing = f"{site}/paper_files/paper/{year}"
    content, error = _get(listing, timeout=_LISTING_TIMEOUT, cache=True)
    if error and error.startswith("HTTP 404"):
        return OfficialLookup(reason=f"the {family} {year} proceedings are not out yet", manual_url=site, waiting=True)
    if error:
        return OfficialLookup(error=f"{provider}: {error}", manual_url=listing)
    for m in re.finditer(r'<a title="paper title" href="([^"]+-Abstract[^"]*\.html)">(.*?)</a>', content or "", re.S):
        if titles_match(title, clean_text(m.group(2))):
            return _proceedings_paper(provider, urllib.parse.urljoin(site, m.group(1)), download)
    if not _recent(year):
        # The proceedings of an older year are complete: a paper missing from them won't be added.
        return OfficialLookup(reason=f"not found in the {family} {year} proceedings", manual_url=listing)
    return OfficialLookup(reason=f"not in the {family} {year} proceedings yet", manual_url=listing, waiting=True)


def _recent(year: str) -> bool:
    """Whether the proceedings of *year* may still be growing: this year's or last year's."""
    return not year.isdigit() or int(year) >= datetime.date.today().year - 1


def _proceedings_paper(provider: str, page: str, download: bool) -> OfficialLookup:
    if not download:
        return OfficialLookup(official=Official(provider, page))
    content, error = _get(page, keep=lambda text: "-Bibtex" in text)
    if error:
        return OfficialLookup(error=f"{provider}: {error}", manual_url=page)
    m = re.search(r'href="([^"]+-Bibtex[^"]*\.bib)"', content or "")
    if m:
        bib_url = urllib.parse.urljoin(page, m.group(1))
    else:
        bib_url = re.sub(r"/hash/([0-9a-f]+)-Abstract[^/]*\.html$", r"/file/\1-Bibtex.bib", page)
    return _simple(provider, page, bib_url, download=True)


def _openreview(record: Record, title: str, year: str, spec: Optional[Spec]) -> OfficialLookup:
    bibtex = record.extra.get("bibtex", "")
    url = record.extra.get("openreview_url", "")
    if not url and "openreview.net/" in record.fields.get("url", ""):
        url = record.fields["url"]  # the entry's own forum page, where a person can get the BibTeX
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
    is_interim = spec is not None and spec.interim == INTERIM_OPENREVIEW and not spec.interim_is_official(year)
    return OfficialLookup(official=Official("OpenReview", url, bibtex.strip(),
                                            interim=INTERIM_OPENREVIEW if is_interim else ""))


# ---------------------------------------------------------------- lookup


def _by_doi(doi: str, record: Optional[Record], download: bool, reg: Registry) -> Optional[OfficialLookup]:
    """Official BibTeX by DOI publisher, or None when the publisher is not routed."""
    prefix = doi.split("/", 1)[0]
    if prefix in reg.blocked_prefixes:
        return OfficialLookup(
            reason=f"{reg.blocked_prefixes[prefix]} blocks automated BibTeX downloads",
            manual_url=f"https://doi.org/{doi}",
        )
    provider = reg.doi_prefixes.get(prefix, "")
    if provider == XPLORE:
        return _xplore_for_doi(doi, record, download)
    if provider == SPRINGER:
        return _springer(doi, download)
    if provider == ACL:
        m = re.match(r"^10\.\d+/v1/(.+)$", doi, re.IGNORECASE)
        if m:
            return _acl(m.group(1), download)
    if provider == IJCAI:
        m = re.match(r"^10\.\d+/ijcai\.(\d{4})/(\d+)$", doi, re.IGNORECASE)
        if m:
            return _ijcai(m.group(1), m.group(2), download)
    return None


def _first(*lookups) -> OfficialLookup:
    """First lookup that found something; else the last one, with earlier errors kept."""
    last = OfficialLookup()
    errors = []
    waiting = False
    for make in lookups:
        last = make()
        if last.official:
            if errors:
                last.reason = "; ".join([*errors, last.reason]).strip("; ") + f"; used {last.official.provider} instead"
            return last
        if last.error:
            errors.append(last.error)
        waiting = waiting or last.waiting
    if errors and not last.error:
        last.error = "; ".join(errors)
    # The proceedings that would have it are not out yet, even if a later source did not have it either.
    last.waiting = waiting
    return last


def find_official(record: Record, download: bool = True, interim: bool = True,
                  library: Optional[VenueLibrary] = None) -> OfficialLookup:
    """Locate (and by default download) the official BibTeX of *record*.

    With ``interim=False``, CVF Open Access and OpenReview are only used where
    they are the official source (ICLR before 2024).  The family records of
    *library* extend the provider table (see :mod:`bibcc.families`).
    """
    title = record.fields.get("title", "")
    doi = normalize_doi(record.doi or record.fields.get("doi", ""))
    if is_arxiv_doi(doi):
        doi = ""
    reg = registry(library)
    family, year = venue_family(record, library)
    spec = reg.get(family)
    provider = spec.provider if spec is not None else ""
    cvf_interim = spec is not None and spec.interim == INTERIM_CVF
    openreview_interim = spec is not None and spec.interim == INTERIM_OPENREVIEW
    openreview_official = openreview_interim and spec.interim_is_official(year)

    if doi:
        routed = _by_doi(doi, record, download, reg)
        if routed is not None and routed.error and cvf_interim and interim:
            fallback = _cvf(title, family, year)
            if fallback.official:
                fallback.reason = f"IEEE Xplore failed ({routed.error}); used CVF Open Access instead"
                return fallback
        if routed is not None:
            return routed

    if provider == XPLORE:
        def from_xplore() -> OfficialLookup:
            found, error = crossref_search(title, prefix=reg.search_prefix(XPLORE))
            if found:
                return _xplore_for_doi(found.doi, found, download)
            return OfficialLookup(error=f"CrossRef: {error}" if error else "", reason="not in IEEE Xplore yet",
                                  waiting=not error)
        steps = [from_xplore]
        if interim and cvf_interim:
            steps.append(lambda: _cvf(title, family, year))
        return _first(*steps)

    if provider == SPRINGER:
        found, error = crossref_search(title, prefix=reg.search_prefix(SPRINGER))
        if found:
            return _springer(found.doi, download)
        if error:
            return OfficialLookup(error=f"CrossRef: {error}")
        hint = " (the site there has no BibTeX)" if spec.manual_url else ""
        return OfficialLookup(reason=f"not on SpringerLink yet{hint}", manual_url=spec.manual_url, waiting=True)

    if provider == PROCEEDINGS_SITE:
        steps = []
        if spec.site and not openreview_official:
            steps.append(lambda: _proceedings_site(title, family, year, download, spec.site))
        if openreview_interim and (interim or openreview_official):
            steps.append(lambda: _openreview(record, title, year, spec))
        return _first(*steps) if steps else OfficialLookup(reason=f"not in the {family} {year} proceedings yet",
                                                           waiting=True)

    if provider == PMLR:
        steps = [lambda: _pmlr(title, family, year, download)]
        page = record.fields.get("url", "")
        if re.search(r"proceedings\.mlr\.press/v\d+/[^/]+\.html", page):
            # The entry's own PMLR page: its year can be the publication year, not the edition's (CoLLAs).
            # If the page fails, the volume listing decides.
            def from_page() -> OfficialLookup:
                found = _pmlr_paper(page, download)
                return found if found.official else OfficialLookup()
            steps.insert(0, from_page)
        if openreview_interim and interim:
            steps.append(lambda: _openreview(record, title, year, spec))
        return _first(*steps)

    if provider == OPENREVIEW:
        return _openreview(record, title, year, spec)

    if provider == BLOCKED:
        return OfficialLookup(reason=f"{spec.blocked_by or family} blocks automated BibTeX downloads",
                              manual_url=f"https://doi.org/{doi}" if doi else spec.manual_url)
    if provider in (IJCAI, ACL) and not doi:
        found, error = crossref_search(title, prefix=reg.search_prefix(provider))
        if found:
            routed = _by_doi(found.doi, found, download, reg)
            if routed is not None:
                return routed
        if error:
            return OfficialLookup(error=f"CrossRef: {error}")

    if record.extra.get("bibtex"):
        return _openreview(record, title, year, spec)

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
        content, error = _get(u, keep=lambda text: "bibref" in text)
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
        spec = registry().get(family)
        site = (spec.site if spec is not None and spec.site else f"https://{m.group(1)}").rstrip("/")
        page = f"{site}/paper_files/paper/{m.group(2)}"
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


@dataclass
class OfficialFields:
    """Official BibTeX cleaned for a bibliography, and what the cleaning changed."""

    entry_type: str
    fields: Dict[str, str]
    # The month value dropped because it gives a period across two months
    # (PMLR's "29 Jul--01 Aug"), or "".
    dropped_period: str = ""
    # The entry type the export used, when it was changed (AAAI's "article"), or "".
    retyped_from: str = ""

    def notes(self) -> List[str]:
        """Report lines that say what the cleaning changed."""
        out = []
        if self.dropped_period:
            out.append(f"month: the official BibTeX gives '{self.dropped_period}', a period across two "
                       "months, so the entry has no month")
        if self.retyped_from:
            out.append(f"type: the official BibTeX is @{self.retyped_from} for conference proceedings "
                       f"'{self.fields.get('booktitle', '')}', so the entry is @{self.entry_type} "
                       "with the name as its booktitle")
        return out


def _months_in(value: str) -> List[str]:
    return list(dict.fromkeys(m for m in map(month_macro, re.findall(r"[A-Za-z]+", value)) if m))


def clean_official(text: str) -> OfficialFields:
    """Official BibTeX cleaned for a bibliography.

    Keeps every field of the export, empty ones included, puts each value
    on one line, writes page ranges with ``--``, and splits PMLR's
    ``21--27 Jul`` month into ``month`` and ``day``.  The one field removed
    is a month that gives a period across two months (``29 Jul--01 Aug``),
    with its ``day``; the month and day that a journal export gives are
    kept.  Conference proceedings exported as ``@article`` (AAAI) become
    ``@inproceedings``, with the ``journal`` value as the ``booktitle``.
    """
    entry_type, raw = parse_bibtex(text)
    fields: Dict[str, str] = {}
    for name, value in raw.items():
        fields[name] = " ".join(str(value).split())
    if fields.get("pages"):
        fields["pages"] = page_range(fields["pages"])
    cleaned = OfficialFields(entry_type, fields)
    month = fields.get("month", "")
    m = re.match(r"^(\d{1,2}(?:\s*-+\s*\d{1,2})?)\s+([A-Za-z]+)\.?$", month)
    if len(_months_in(month)) > 1:
        cleaned.dropped_period = month
        fields.pop("month")
        fields.pop("day", None)
    elif m and month_macro(m.group(2)):
        fields["month"] = m.group(2)
        fields.setdefault("day", page_range(m.group(1).replace(" ", "")))
    if entry_type == "article" and "booktitle" not in fields and is_conference_journal(fields.get("journal")):
        cleaned.retyped_from = entry_type
        cleaned.entry_type = "inproceedings"
        cleaned.fields = {("booktitle" if k == "journal" else k): v for k, v in fields.items()}
    return cleaned


def official_fields(text: str) -> Tuple[str, Dict[str, str]]:
    """``(entry_type, fields)`` of official BibTeX, cleaned by :func:`clean_official`."""
    cleaned = clean_official(text)
    return cleaned.entry_type, cleaned.fields


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
