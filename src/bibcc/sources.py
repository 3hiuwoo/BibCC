"""
Fetch bibliographic records from CrossRef, arXiv, Semantic Scholar, and OpenReview.

Every fetcher returns ``(record_or_None, error_or_None)``; ``(None, None)``
means the source answered but had no match.  Records hold plain-text field
values (no BibTeX escaping or casing); :mod:`bibcc.adder` turns them into
entries.

DBLP is not queried: its API sits behind a bot challenge.  Semantic Scholar
exposes the DBLP key of a paper (``conf/iclr/WuPHW25``), which is enough to
identify the venue and year of conference papers without a DOI.

Set ``S2_API_KEY`` to use a Semantic Scholar API key (higher rate limits).

Usage:
    from bibcc.sources import resolve

    result = resolve("2501.13198", library)
    if result.record:
        print(result.record.fields)
"""

from __future__ import annotations

import html
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

from bibcc import __version__
from bibcc.checkers.citation_keys import VENUE_ABBREVIATIONS, _keyword_in
from bibcc.venues import VenueLibrary, normalize_venue

USER_AGENT = f"BibCC/{__version__} (https://github.com/3hiuwoo/BibCC)"
S2_API_KEY_ENV = "S2_API_KEY"
S2_FIELDS = "title,year,venue,externalIds,authors,publicationVenue,publicationDate"
_S2_BASE = "https://api.semanticscholar.org/graph/v1/paper"
_ARXIV_API = "https://export.arxiv.org/api/query"
# Error prefix from arxiv_record() when arXiv answered but has no such paper.
ARXIV_MISSING = "arXiv has no paper"
_ATOM = {"atom": "http://www.w3.org/2005/Atom", "arxiv": "http://arxiv.org/schemas/atom"}

# DBLP conference stream names whose key abbreviation differs from upper-casing.
_DBLP_ABBREVIATIONS = {"nips": "NeurIPS", "neurips": "NeurIPS", "interspeech": "Interspeech"}


@dataclass
class Record:
    """A paper's metadata as plain text, before BibTeX formatting."""

    entry_type: str
    fields: Dict[str, str]
    source: str
    doi: str = ""
    arxiv_id: str = ""
    extra: Dict[str, str] = field(default_factory=dict)
    notes: List[str] = field(default_factory=list)


@dataclass
class Resolution:
    """Outcome of resolving one identifier."""

    record: Optional[Record] = None
    error: Optional[str] = None


# --------------------------------------------------------------------- HTTP


def fetch_url(
    url: str,
    headers: Optional[Dict[str, str]] = None,
    timeout: int = 15,
    retries: int = 0,
) -> Tuple[Optional[str], Optional[str]]:
    """Fetch *url* and return ``(content, error)``.

    HTTP 429/503 responses are retried *retries* times with exponential
    backoff (or the server's ``Retry-After``).
    """
    attempt = 0
    while True:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, **(headers or {})})
            with urllib.request.urlopen(req, timeout=timeout) as response:
                return response.read().decode("utf-8"), None
        except urllib.error.HTTPError as e:
            if e.code in (429, 503) and attempt < retries:
                retry_after = e.headers.get("Retry-After", "") if e.headers else ""
                delay = float(retry_after) if retry_after.isdigit() else 3.0 * 2**attempt
                time.sleep(min(delay, 60.0))
                attempt += 1
                continue
            return None, f"HTTP {e.code}: {e.reason}"
        except urllib.error.URLError as e:
            return None, f"Network error: {e.reason}"
        except TimeoutError:
            return None, "Request timed out"
        except Exception as e:  # noqa: BLE001 - report any failure as a fetch error
            return None, f"{type(e).__name__}: {e}"


def looks_like_html(content: Optional[str]) -> bool:
    """True if *content* is an HTML page (e.g. a bot challenge) rather than data."""
    head = (content or "").lstrip()[:100].lower()
    return head.startswith("<!doctype html") or head.startswith("<html")


def fetch_json(
    url: str, headers: Optional[Dict[str, str]] = None, retries: int = 2
) -> Tuple[Optional[Any], Optional[str]]:
    """Fetch and decode JSON, returning ``(data, error)``."""
    content, error = fetch_url(url, headers=headers, retries=retries)
    if error:
        return None, error
    if looks_like_html(content):
        return None, "received an HTML page instead of data (bot protection?)"
    try:
        return json.loads(content or ""), None
    except json.JSONDecodeError as e:
        return None, f"JSON parse error: {e}"


# ------------------------------------------------------------- identifiers

_ARXIV_NEW = re.compile(r"^(\d{4}\.\d{4,5})(?:v\d+)?$")
# Pre-2007 IDs: archive, optional subject class (not part of the ID), YYMMNNN.
_ARXIV_OLD = re.compile(r"^([a-z\-]+)(?:\.[A-Za-z]{2})?/(\d{7})(?:v\d+)?$", re.IGNORECASE)
_ARXIV_IN_TEXT = re.compile(
    r"\barxiv(?:\s+preprint)?[:\s/]*(?:arxiv:\s*)?"
    r"(\d{4}\.\d{4,5}|[a-z\-]+(?:\.[A-Za-z]{2})?/\d{7})(?:v\d+)?(?!\d)",
    re.IGNORECASE,
)
_DOI_PREFIX = re.compile(r"^(?:doi:\s*|https?://(?:dx\.)?doi\.org/)", re.IGNORECASE)
_ARXIV_DOI = re.compile(r"^10\.48550/arxiv\.(.+)$", re.IGNORECASE)


def normalize_doi(text: Optional[str]) -> str:
    """Bare DOI (``10.x/y``) from a DOI, ``doi:`` string, or doi.org URL."""
    doi = _DOI_PREFIX.sub("", (text or "").strip())
    doi = urllib.parse.unquote(doi).rstrip(".,;")
    return doi if re.match(r"^10\.\d{4,9}/\S+$", doi) else ""


def normalize_arxiv_id(text: Optional[str]) -> str:
    """Bare arXiv ID without version from an ID, ``arXiv:`` string, URL, or arXiv DOI."""
    t = (text or "").strip()
    m = re.search(r"arxiv\.org/(?:abs|pdf|html)/([^\s?#]+)", t, re.IGNORECASE)
    if m:
        t = re.sub(r"\.pdf$", "", m.group(1))
    t = re.sub(r"^arxiv:\s*", "", t, flags=re.IGNORECASE)
    m = _ARXIV_DOI.match(normalize_doi(t) or t)
    if m:
        t = m.group(1)
    m = _ARXIV_NEW.match(t)
    if m:
        return m.group(1)
    m = _ARXIV_OLD.match(t)
    if m:
        return f"{m.group(1).lower()}/{m.group(2)}"
    return ""


def is_arxiv_doi(doi: Optional[str]) -> bool:
    return bool(_ARXIV_DOI.match(doi or ""))


def parse_identifier(text: str) -> Tuple[str, str]:
    """Classify *text* as ``("arxiv"|"doi"|"url"|"title", value)``."""
    t = text.strip()
    arxiv_id = normalize_arxiv_id(t)
    if arxiv_id:
        return "arxiv", arxiv_id
    doi = normalize_doi(t)
    if doi:
        return "doi", doi
    if re.match(r"^https?://", t, re.IGNORECASE):
        return "url", t
    return "title", t


def entry_arxiv_id(entry: Dict[str, str]) -> str:
    """arXiv ID referenced by a parsed BibTeX entry, if any."""
    eprint = entry.get("eprint", "")
    prefix = entry.get("archiveprefix", "").lower()
    if eprint and (not prefix or "arxiv" in prefix or _ARXIV_NEW.match(eprint.strip())):
        found = normalize_arxiv_id(eprint)
        if found:
            return found
    for name in ("url", "doi"):
        found = normalize_arxiv_id(entry.get(name, ""))
        if found:
            return found
    for name in ("journal", "note", "howpublished", "booktitle"):
        m = _ARXIV_IN_TEXT.search(entry.get(name, ""))
        if m:
            return normalize_arxiv_id(m.group(1))
    return ""


# ------------------------------------------------------------------- text


def clean_title_for_search(title: str) -> str:
    """Strip BibTeX braces and LaTeX commands from a title for search queries."""
    if not title:
        return ""
    title = re.sub(r"[{}\[\]]", "", title)
    title = title.replace(r"\&", "&")
    title = title.replace(r"\'", "'")
    title = title.replace(r"\$", "")
    title = title.replace(r"\textasciicircum", "^")
    title = re.sub(r"\\[a-zA-Z]+", "", title)
    return re.sub(r"\s+", " ", title).strip()


def normalize_for_comparison(text: str) -> str:
    """Normalize text for comparison (lowercase, remove special chars)."""
    if not text:
        return ""
    text = re.sub(r"[{}\[\]]", "", text).replace("\\&", "&")
    text = re.sub(r"\s+", " ", text).strip().lower()
    text = re.sub(r"[:\-–—,.'\"?!]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def titles_match(title1: str, title2: str) -> bool:
    """Check if two titles are essentially the same."""
    return normalize_for_comparison(title1) == normalize_for_comparison(title2)


def clean_text(text: Optional[str]) -> str:
    """Plain single-line text: HTML tags/entities removed, whitespace collapsed."""
    text = html.unescape(re.sub(r"</?[a-zA-Z][^>]*>", "", text or ""))
    return " ".join(text.replace("\u00a0", " ").split())


def _date_parts(msg: Dict[str, Any], *keys: str) -> Tuple[str, str]:
    for key in keys:
        parts = ((msg.get(key) or {}).get("date-parts") or [[None]])[0]
        if parts and parts[0]:
            month = str(parts[1]) if len(parts) > 1 and parts[1] else ""
            return str(parts[0]), month
    return "", ""


# --------------------------------------------------------------- CrossRef

_SERIES_TITLE = re.compile(r"^(lecture notes|communications in computer)", re.IGNORECASE)
_CONFERENCE_WORDS = re.compile(
    r"\b(proceedings|conference|workshops?|symposium|eccv|accv|miccai|icpr)\b", re.IGNORECASE
)


def _crossref_name(author: Dict[str, Any]) -> str:
    family, given = clean_text(author.get("family")), clean_text(author.get("given"))
    if family and given:
        return f"{family}, {given}"
    return family or clean_text(author.get("name"))


def _first_issn(msg: Dict[str, Any]) -> str:
    typed = msg.get("issn-type") or []
    for wanted in ("electronic", "print"):
        for item in typed:
            if item.get("type") == wanted and item.get("value"):
                return item["value"]
    issns = msg.get("ISSN") or []
    return issns[0] if issns else ""


def record_from_crossref(msg: Dict[str, Any]) -> Record:
    """Build a Record from a CrossRef ``works`` message."""
    ctype = msg.get("type", "")
    containers = [clean_text(c) for c in msg.get("container-title") or [] if clean_text(c)]
    series = [c for c in containers if _SERIES_TITLE.match(c)]
    books = [c for c in containers if not _SERIES_TITLE.match(c)]

    if ctype == "journal-article" and containers and containers[0].lower().startswith("proceedings of"):
        # AAAI, IJCAI, and PMLR register conference papers as journal articles.
        entry_type = "inproceedings"
    elif ctype == "journal-article":
        entry_type = "article"
    elif ctype == "proceedings-article":
        entry_type = "inproceedings"
    elif ctype == "book-chapter":
        is_conference = series or any(_CONFERENCE_WORDS.search(c) for c in containers)
        entry_type = "inproceedings" if is_conference else "incollection"
    elif ctype in ("book", "monograph", "edited-book"):
        entry_type = "book"
    else:
        entry_type = "misc"

    title = clean_text((msg.get("title") or [""])[0])
    subtitle = clean_text((msg.get("subtitle") or [""])[0])
    if subtitle and subtitle.lower() not in title.lower():
        title = f"{title}: {subtitle}"

    fields: Dict[str, str] = {
        "title": title,
        "author": " and ".join(n for n in map(_crossref_name, msg.get("author") or []) if n),
    }
    if entry_type == "article":
        fields["journal"] = containers[0] if containers else ""
    elif entry_type in ("inproceedings", "incollection"):
        fields["booktitle"] = books[-1] if books else (containers[-1] if containers else "")
        if series:
            fields["series"] = series[0]

    year, month = _date_parts(msg, "published-print", "issued", "published-online", "published")
    fields["year"] = year
    fields["month"] = month
    fields["volume"] = clean_text(msg.get("volume"))
    fields["number"] = clean_text(msg.get("issue"))
    pages = clean_text(msg.get("page"))
    fields["pages"] = re.sub(r"\s*[-‐‑–—]+\s*", "--", pages)
    fields["publisher"] = clean_text(msg.get("publisher"))
    if entry_type == "article":
        fields["issn"] = _first_issn(msg)
    location = clean_text((msg.get("event") or {}).get("location"))
    if entry_type == "inproceedings" and location:
        fields["venue"] = location
    doi = clean_text(msg.get("DOI"))
    fields["doi"] = doi

    return Record(
        entry_type=entry_type,
        fields={k: v for k, v in fields.items() if v},
        source="CrossRef",
        doi=doi,
    )


def crossref_record(doi: str) -> Tuple[Optional[Record], Optional[str]]:
    """Fetch a DOI's metadata from CrossRef."""
    url = f"https://api.crossref.org/works/{urllib.parse.quote(doi, safe='/')}"
    data, error = fetch_json(url)
    if error:
        if error.startswith("HTTP 404"):
            return None, f"DOI {doi} is not registered with CrossRef"
        return None, error
    msg = (data or {}).get("message")
    if not isinstance(msg, dict):
        return None, "unexpected CrossRef response"
    record = record_from_crossref(msg)
    # CrossRef often lower-cases DOIs; keep the casing the caller gave.
    if record.doi.lower() == doi.lower():
        record.doi = record.fields["doi"] = doi
    return record, None


def crossref_search(title: str) -> Tuple[Optional[Record], Optional[str]]:
    """Search CrossRef by title; only an exact (normalized) title match counts."""
    query = urllib.parse.quote(clean_title_for_search(title))
    data, error = fetch_json(f"https://api.crossref.org/works?query.bibliographic={query}&rows=5")
    if error:
        return None, error
    for item in ((data or {}).get("message") or {}).get("items") or []:
        if titles_match(title, clean_text((item.get("title") or [""])[0])):
            return record_from_crossref(item), None
    return None, None


# ------------------------------------------------------------------ arXiv


def _arxiv_records(content: str) -> List[Record]:
    root = ET.fromstring(content)
    records = []
    for elem in root.findall("atom:entry", _ATOM):
        raw_id = elem.findtext("atom:id", "", _ATOM)
        arxiv_id = normalize_arxiv_id(raw_id)
        if not arxiv_id:
            continue
        published = elem.findtext("atom:published", "", _ATOM)
        primary = elem.find("arxiv:primary_category", _ATOM)
        authors = [
            clean_text(a.findtext("atom:name", "", _ATOM)) for a in elem.findall("atom:author", _ATOM)
        ]
        fields = {
            "title": clean_text(elem.findtext("atom:title", "", _ATOM)),
            "author": " and ".join(a for a in authors if a),
            "year": published[:4],
            "eprint": arxiv_id,
            "archiveprefix": "arXiv",
            "primaryclass": primary.get("term", "") if primary is not None else "",
            "url": f"https://arxiv.org/abs/{arxiv_id}",
        }
        extra = {
            "comment": clean_text(elem.findtext("arxiv:comment", "", _ATOM)),
            "journal_ref": clean_text(elem.findtext("arxiv:journal_ref", "", _ATOM)),
            "doi": clean_text(elem.findtext("arxiv:doi", "", _ATOM)),
        }
        records.append(
            Record(
                entry_type="misc",
                fields={k: v for k, v in fields.items() if v},
                source="arXiv",
                arxiv_id=arxiv_id,
                extra={k: v for k, v in extra.items() if v},
            )
        )
    return records


def arxiv_record(arxiv_id: str) -> Tuple[Optional[Record], Optional[str]]:
    """Fetch one arXiv paper by ID."""
    url = f"{_ARXIV_API}?id_list={urllib.parse.quote(arxiv_id, safe='/')}"
    content, error = fetch_url(url, retries=2)
    if error:
        return None, error
    try:
        records = _arxiv_records(content or "")
    except ET.ParseError as e:
        return None, f"XML parse error: {e}"
    for record in records:
        if record.arxiv_id == arxiv_id:
            return record, None
    return None, f"{ARXIV_MISSING} {arxiv_id}"


def arxiv_search(title: str) -> Tuple[Optional[Record], Optional[str]]:
    """Search arXiv by title; only an exact (normalized) title match counts."""
    words = re.sub(r"[^\w\s-]", " ", clean_title_for_search(title))
    query = urllib.parse.quote(f'ti:"{" ".join(words.split())}"')
    content, error = fetch_url(f"{_ARXIV_API}?search_query={query}&max_results=5", retries=2)
    if error:
        return None, error
    try:
        records = _arxiv_records(content or "")
    except ET.ParseError as e:
        return None, f"XML parse error: {e}"
    for record in records:
        if titles_match(title, record.fields.get("title", "")):
            return record, None
    return None, None


# --------------------------------------------------------- Semantic Scholar


def _s2_headers() -> Dict[str, str]:
    key = os.environ.get(S2_API_KEY_ENV, "").strip()
    return {"x-api-key": key} if key else {}


def s2_get(url: str) -> Tuple[Optional[Any], Optional[str]]:
    """GET a Semantic Scholar API URL with the API key and retries; a 404 is not an error."""
    data, error = fetch_json(url, headers=_s2_headers(), retries=3)
    if error and error.startswith("HTTP 404"):
        return None, None
    if error and error.startswith("HTTP 429"):
        hint = "" if _s2_headers() else f"; set {S2_API_KEY_ENV} for higher limits"
        return None, f"rate limited (HTTP 429){hint}"
    return data, error


def s2_paper(paper_id: str) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """Fetch a Semantic Scholar paper by ID (``arXiv:2501.13198``, ``DOI:10...``)."""
    return s2_get(f"{_S2_BASE}/{urllib.parse.quote(paper_id, safe=':/')}?fields={S2_FIELDS}")


def s2_match(title: str) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """Best Semantic Scholar title match, accepted only if the titles agree."""
    query = urllib.parse.quote(clean_title_for_search(title))
    data, error = s2_get(f"{_S2_BASE}/search/match?query={query}&fields={S2_FIELDS}")
    if error:
        return None, error
    for paper in (data or {}).get("data") or []:
        if titles_match(title, paper.get("title", "")):
            return paper, None
    return None, None


def dblp_venue(dblp_key: Optional[str]) -> Tuple[str, str]:
    """``(abbreviation, year)`` from a DBLP conference key like ``conf/iclr/WuP25``."""
    m = re.match(r"^conf/([a-z0-9]+)/.*?(\d{2})[a-z]?$", dblp_key or "")
    if not m:
        return "", ""
    stream = m.group(1)
    abbrev = _DBLP_ABBREVIATIONS.get(stream)
    if abbrev is None:
        abbrev = next((k for k in VENUE_ABBREVIATIONS if k.lower() == stream), stream.upper())
    return abbrev, f"20{m.group(2)}"


def library_booktitle(library: VenueLibrary, abbrev: str, year: str) -> Optional[str]:
    """Canonical booktitle of conference *abbrev* in *year*, if the library has exactly one."""
    keywords = VENUE_ABBREVIATIONS.get(abbrev)
    if not keywords:
        return None
    wants_workshop = abbrev.endswith("W")
    candidates = []
    for venue in library.proceedings:
        if str(venue.year).strip() != year:
            continue
        if ("workshop" in normalize_venue(venue.name)) != wants_workshop:
            continue
        if any(_keyword_in(kw, name) for name in venue.names() for kw in keywords):
            candidates.append(venue.name)
    return candidates[0] if len(candidates) == 1 else None


def published_from_s2(
    paper: Dict[str, Any], library: VenueLibrary
) -> Tuple[Optional[Record], Optional[str]]:
    """The published (non-arXiv) version of an S2 paper, if it has one.

    Uses the paper's DOI via CrossRef when available; otherwise a DBLP
    conference key plus the venue library's booktitle for that year.
    """
    ext = paper.get("externalIds") or {}
    arxiv_id = normalize_arxiv_id(ext.get("ArXiv", ""))
    doi = normalize_doi(ext.get("DOI", ""))
    error = None
    if doi and not is_arxiv_doi(doi):
        record, error = crossref_record(doi)
        if record:
            record.arxiv_id = arxiv_id
            record.source = "CrossRef (DOI from Semantic Scholar)"
            return record, None

    abbrev, year = dblp_venue(ext.get("DBLP"))
    if not abbrev:
        return None, error
    # OpenReview has the authors' own name spellings and the forum URL.
    record, _ = openreview_search(clean_text(paper.get("title")), library)
    if record:
        record.arxiv_id = arxiv_id
        return record, None
    booktitle = library_booktitle(library, abbrev, year)
    notes = []
    if booktitle is None:
        booktitle = clean_text(paper.get("venue")) or abbrev
        notes.append(
            f"booktitle '{booktitle}' comes from Semantic Scholar; "
            f"the venue library has no single {abbrev} {year} record"
        )
    authors = [clean_text(a.get("name")) for a in paper.get("authors") or []]
    fields = {
        "title": clean_text(paper.get("title")),
        "author": " and ".join(a for a in authors if a),
        "year": year,
        "booktitle": booktitle,
    }
    return (
        Record(
            entry_type="inproceedings",
            fields={k: v for k, v in fields.items() if v},
            source=f"Semantic Scholar (DBLP {ext.get('DBLP')})",
            arxiv_id=arxiv_id,
            notes=notes,
        ),
        None,
    )


# ------------------------------------------------------------- OpenReview

_OPENREVIEW_API = "https://api2.openreview.net/notes/search"
_OPENREVIEW_CONFERENCES = {
    "CVPR", "ICCV", "ECCV", "NeurIPS", "ICML", "ICLR", "AAAI", "MM", "WWW",
    "ACL", "EMNLP", "NAACL", "KDD", "Interspeech",
}
_UNACCEPTED = re.compile(r"\b(submitted|withdrawn|rejected|desk)\b", re.IGNORECASE)


def _note_value(content: Dict[str, Any], name: str) -> Any:
    value = content.get(name)
    return value.get("value") if isinstance(value, dict) else value


def openreview_search(
    title: str, library: VenueLibrary
) -> Tuple[Optional[Record], Optional[str]]:
    """Accepted conference paper on OpenReview with exactly this title.

    Covers venues whose papers have no DOI (ICLR, NeurIPS, ICML).  Notes
    whose venue says "Submitted to" or "Withdrawn" are ignored, and the
    conference's own note is preferred over a DBLP import.
    """
    query = urllib.parse.quote(clean_title_for_search(title))
    data, error = fetch_json(f"{_OPENREVIEW_API}?term={query}&content=title&source=forum&limit=10")
    if error:
        return None, error
    best = None
    for note in (data or {}).get("notes") or []:
        content = note.get("content") or {}
        if not titles_match(title, clean_text(_note_value(content, "title"))):
            continue
        venue = clean_text(_note_value(content, "venue"))
        m = re.match(r"^([A-Za-z]+)\s+(\d{4})\b", venue)
        if not m or _UNACCEPTED.search(venue):
            continue
        abbrev = next((k for k in _OPENREVIEW_CONFERENCES if k.lower() == m.group(1).lower()), None)
        if abbrev is None:
            continue
        official = not str(_note_value(content, "venueid") or "").startswith("dblp.org")
        if best is None or (official and not best[0]):
            best = (official, note, venue, abbrev, m.group(2))
    if best is None:
        return None, None

    _, note, venue, abbrev, year = best
    content = note.get("content") or {}
    notes = []
    booktitle = library_booktitle(library, abbrev, year)
    if booktitle is None:
        booktitle = f"{abbrev} {year}"
        notes.append(
            f"booktitle '{booktitle}' is a placeholder; the venue library has no single {abbrev} {year} record"
        )
    html_url = str(_note_value(content, "html") or "")
    if "openreview.net/forum" in html_url:
        url = html_url
    else:
        url = f"https://openreview.net/forum?id={note.get('forum') or note.get('id')}"
    authors = [clean_text(a) for a in _note_value(content, "authors") or []]
    fields = {
        "title": clean_text(_note_value(content, "title")),
        "author": " and ".join(a for a in authors if a),
        "year": year,
        "booktitle": booktitle,
        "url": url,
    }
    return (
        Record(
            entry_type="inproceedings",
            fields={k: v for k, v in fields.items() if v},
            source=f"OpenReview ({venue})",
            notes=notes,
        ),
        None,
    )


# ---------------------------------------------------------------- resolve


def _published_for_arxiv(
    arxiv_id: str, preprint: Optional[Record], library: VenueLibrary
) -> Tuple[Optional[Record], Optional[str]]:
    linked_doi = (preprint.extra.get("doi") if preprint else "") or ""
    if linked_doi and not is_arxiv_doi(linked_doi):
        record, _ = crossref_record(linked_doi)
        if record:
            record.source = "CrossRef (DOI linked from arXiv)"
            return record, None
    paper, error = s2_paper(f"arXiv:{arxiv_id}")
    if paper:
        record, _ = published_from_s2(paper, library)
        if record:
            # Semantic Scholar's own author names are often re-spelled; arXiv's are not.
            if record.source.startswith("Semantic Scholar") and preprint and preprint.fields.get("author"):
                record.fields["author"] = preprint.fields["author"]
            return record, None
    title = preprint.fields.get("title", "") if preprint else ""
    if title:
        known_venue = bool(paper and dblp_venue((paper.get("externalIds") or {}).get("DBLP"))[0])
        record, _ = find_published_by_title(title, library, skip_openreview=known_venue)
        if record:
            return record, None
    return None, error


def find_published_by_title(
    title: str, library: VenueLibrary, skip_openreview: bool = False
) -> Tuple[Optional[Record], Optional[str]]:
    """Accepted OpenReview paper or non-preprint CrossRef record with exactly *title*.

    Returns ``(record_or_None, crossref_error_or_None)``.
    """
    if not skip_openreview:
        record, _ = openreview_search(title, library)
        if record:
            return record, None
    record, error = crossref_search(title)
    if record and record.entry_type != "misc":
        record.source = "CrossRef (title search)"
        return record, None
    return None, error


def acceptance_note(preprint: Optional[Record]) -> str:
    """A note when the arXiv comment or journal-ref says the paper was published."""
    if preprint is None:
        return ""
    journal_ref = preprint.extra.get("journal_ref", "")
    if journal_ref:
        return f"arXiv journal-ref: '{journal_ref}' (published version not indexed yet)"
    comment = preprint.extra.get("comment", "")
    if re.search(r"\b(accepted|published|to appear)\b", comment, re.IGNORECASE):
        return f"arXiv comment says: '{comment}' (published version not indexed yet)"
    return ""


def find_published(
    arxiv_id: str, library: VenueLibrary, preprint: Optional[Record] = None
) -> Tuple[Optional[Record], Optional[str]]:
    """Published version of arXiv paper *arxiv_id*, or ``(None, error_or_None)``."""
    record, error = _published_for_arxiv(arxiv_id, preprint, library)
    if record:
        record.arxiv_id = arxiv_id
    return record, error


@dataclass
class ArxivResolution:
    """Outcome of looking up an arXiv paper and its published version."""

    published: Optional[Record] = None
    preprint: Optional[Record] = None
    # arXiv's error when there is no preprint, else the published-version search error.
    error: Optional[str] = None
    notes: List[str] = field(default_factory=list)


def resolve_arxiv(
    arxiv_id: str, library: VenueLibrary, fallback_title: Optional[str] = None
) -> ArxivResolution:
    """Fetch arXiv paper *arxiv_id* and look for its published version.

    When arXiv cannot be reached and *fallback_title* is given, a stand-in
    preprint with that title is used so title searches still run.  ``notes``
    explains a missing published version (e.g. an arXiv journal-ref).
    """
    preprint, error = arxiv_record(arxiv_id)
    if preprint is None and fallback_title is not None:
        preprint = Record("misc", {"title": fallback_title}, source="bib", arxiv_id=arxiv_id)
    published, pub_error = find_published(arxiv_id, library, preprint)
    if published:
        return ArxivResolution(published=published, preprint=preprint)
    note = acceptance_note(preprint)
    return ArxivResolution(
        preprint=preprint,
        error=pub_error if preprint else error,
        notes=[note] if note else [],
    )


def resolve(
    identifier: str,
    library: VenueLibrary,
    prefer_published: bool = True,
    log: Optional[Callable[[str], None]] = None,
) -> Resolution:
    """Fetch metadata for a DOI, arXiv ID/URL, or title.

    arXiv papers are replaced by their published version when one is found,
    unless *prefer_published* is False.
    """
    log = log or (lambda _msg: None)
    kind, value = parse_identifier(identifier)

    if kind == "url":
        return Resolution(error="unsupported URL; pass a DOI, an arXiv ID or URL, or a title")

    if kind == "doi":
        record, error = crossref_record(value)
        return Resolution(record=record, error=error)

    if kind == "arxiv":
        if not prefer_published:
            preprint, error = arxiv_record(value)
            return Resolution(record=preprint, error=error)
        log("   checking for a published version...")
        found = resolve_arxiv(value, library)
        if found.published:
            found.published.notes.append(f"published version of arXiv:{value}")
            return Resolution(record=found.published)
        if found.preprint is None:
            return Resolution(error=found.error)
        if found.error:
            found.preprint.notes.append(f"could not check for a published version: {found.error}")
        found.preprint.notes.extend(found.notes)
        return Resolution(record=found.preprint)

    errors: List[str] = []
    paper, error = s2_match(value)
    if error:
        errors.append(f"Semantic Scholar: {error}")
    published: Optional[Record] = None
    arxiv_id = ""
    if paper:
        published, _ = published_from_s2(paper, library)
        arxiv_id = normalize_arxiv_id((paper.get("externalIds") or {}).get("ArXiv", ""))
    if published and prefer_published:
        return Resolution(record=published)

    def search_openreview(title: str) -> Tuple[Optional[Record], Optional[str]]:
        return openreview_search(title, library)

    searches: List[Tuple[str, Callable[[str], Tuple[Optional[Record], Optional[str]]]]] = [
        ("OpenReview", search_openreview),
        ("CrossRef", crossref_search),
        ("arXiv", arxiv_search),
    ]
    if prefer_published:
        record, error = search_openreview(value)
        if record:
            return Resolution(record=record)
        if error:
            errors.append(f"OpenReview: {error}")
        searches.pop(0)
    if arxiv_id:
        preprint, error = arxiv_record(arxiv_id)
        if preprint:
            return Resolution(record=preprint)
        errors.append(f"arXiv: {error}")
    if published:
        return Resolution(record=published)

    for name, search in searches:
        record, error = search(value)
        if record:
            if errors:
                record.notes.extend(errors)
            return Resolution(record=record)
        if error:
            errors.append(f"{name}: {error}")

    detail = "; ".join(errors) if errors else "no source has a paper with this exact title"
    return Resolution(error=f"not found ({detail})")
