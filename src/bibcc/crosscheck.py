"""
Check bib entries and venue-library records against CrossRef.

Used by ``bibcc complete --online``.  CrossRef is never the source of an
entry's fields: ``complete`` only adds fields from the venue library.  Here
CrossRef serves two purposes:

* **Filling** the records proposed for venues missing from the library
  (``# from CrossRef`` in the missing-venues YAML): publisher, ISSN, ISBN,
  event location, and event month.
* **Validating**: for every entry with a (non-arXiv) DOI, the entry's value,
  the library record's value, and CrossRef's value of each
  :data:`CHECKED_FIELDS` field are compared.  Disagreements are reported;
  nothing is changed.  ISSN, ISBN, DOI, pages, volume, number, and year must
  match exactly (ignoring formatting); venue names, publishers, and
  locations match loosely (case, punctuation, and one containing the other).
  Titles and authors are not compared.  Entries without a DOI are listed as
  not checked.

Usage:
    from bibcc.crosscheck import check_entry, venue_fields_from_crossref
"""

from __future__ import annotations

import calendar
import re
import time
from dataclasses import dataclass
from typing import Dict, List, Mapping, Optional, Tuple

from bibcc.bibedit import month_macro
from bibcc.sources import Record, crossref_record, is_arxiv_doi, normalize_doi, normalize_for_comparison
from bibcc.venues import JOURNAL, PROCEEDINGS, Venue, is_no_month, normalize_issn

CHECKED_FIELDS = (
    "journal", "booktitle", "year", "volume", "number", "pages", "doi",
    "publisher", "issn", "isbn", "venue", "month",
)
_NAME_FIELDS = {"journal", "booktitle"}
_LOOSE_FIELDS = {"journal", "booktitle", "publisher", "venue"}


def _month_name(number: str) -> str:
    return calendar.month_name[int(number)] if number.isdigit() and 1 <= int(number) <= 12 else ""


def _split_list(text: str) -> List[str]:
    return [p.strip() for p in (text or "").split(",") if p.strip()]


def crossref_values(record: Record, kind: str) -> Dict[str, List[str]]:
    """CrossRef's value(s) for each checked field (several for ISSN and ISBN)."""
    f = record.fields
    values: Dict[str, List[str]] = {}
    container = record.extra.get("container", "")
    if kind == JOURNAL and (f.get("journal") or container):
        values["journal"] = [f.get("journal") or container]
    if kind == PROCEEDINGS and (f.get("booktitle") or container):
        values["booktitle"] = [f.get("booktitle") or container]
    for name in ("year", "volume", "number", "pages", "doi", "publisher"):
        if f.get(name):
            values[name] = [f[name]]
    issns = _split_list(record.extra.get("issn", "")) or ([f["issn"]] if f.get("issn") else [])
    if issns:
        values["issn"] = issns
    isbns = _split_list(record.extra.get("isbn", ""))
    if isbns:
        values["isbn"] = isbns
    if kind == PROCEEDINGS:
        if f.get("venue"):
            values["venue"] = [f["venue"]]
        month = _month_name(record.extra.get("event_month", ""))
        if month:
            values["month"] = [month]
    elif f.get("month"):
        values["month"] = [_month_name(f["month"]) or f["month"]]
    return values


def venue_fields_from_crossref(record: Record, kind: str) -> Dict[str, str]:
    """Venue-record fields CrossRef knows, for pre-filling a missing venue."""
    values = crossref_values(record, kind)
    wanted = ("publisher", "issn") if kind == JOURNAL else ("venue", "publisher", "month", "isbn", "issn")
    return {name: values[name][0] for name in wanted if values.get(name)}


def _loose(text: str) -> str:
    return normalize_for_comparison(text.replace("\\&", "&")).replace(" ", "")


def same_value(name: str, ours: str, theirs: List[str]) -> bool:
    """Whether *ours* agrees with any of CrossRef's values for field *name*."""
    if name == "issn":
        return bool(set(normalize_issn(ours)) & {d for t in theirs for d in normalize_issn(t)})
    if name == "isbn":
        digits = {re.sub(r"[^0-9X]", "", t.upper()) for t in theirs}
        return any(re.sub(r"[^0-9X]", "", part.upper()) in digits for part in _split_list(ours))
    if name == "month":
        return any(month_macro(ours) and month_macro(ours) == month_macro(t) for t in theirs)
    if name == "doi":
        return any(normalize_doi(ours).lower() == normalize_doi(t).lower() for t in theirs)
    if name == "pages":
        return any(re.sub(r"[^0-9A-Za-z]+", "-", ours) == re.sub(r"[^0-9A-Za-z]+", "-", t) for t in theirs)
    if name in _LOOSE_FIELDS:
        a = _loose(ours)
        return any(a and (a == _loose(t) or a in _loose(t) or _loose(t) in a) for t in theirs)
    return any(ours.strip().strip("{}").lower() == t.strip().lower() for t in theirs)


@dataclass
class Check:
    """One field compared across the entry, its library record, and CrossRef."""

    key: str
    name: str
    bib: str
    library: str
    crossref: str
    verdict: str  # "ok", "bib differs", "library differs", "bib and library differ"


def check_entry(
    key: str, entry: Mapping[str, str], kind: str, venue: Optional[Venue], record: Record,
    fields: Optional[Mapping[str, str]] = None,
) -> List[Check]:
    """Compare *entry* and its library record *venue* with CrossRef's *record*.

    *fields* are the record's fields with its family's (default: the record's own).
    """
    checks = []
    if venue is not None and fields is None:
        fields = venue.fields
    for name, theirs in crossref_values(record, kind).items():
        ours = " ".join(str(entry.get(name, "")).split())
        if venue is None:
            lib = ""
        elif name in _NAME_FIELDS:
            lib = venue.name
        else:
            lib = fields.get(name, "")
        if is_no_month(name, lib):
            lib = ""  # a statement about the venue, not a value CrossRef can confirm
        if not ours and not lib:
            continue
        bib_ok = not ours or same_value(name, ours, theirs)
        lib_ok = not lib or same_value(name, lib, theirs)
        if bib_ok and lib_ok:
            verdict = "ok"
        elif not bib_ok and not lib_ok:
            verdict = "bib and library differ"
        else:
            verdict = "bib differs" if not bib_ok else "library differs"
        checks.append(Check(key, name, ours, lib, " | ".join(theirs), verdict))
    return checks


class CrossrefCache:
    """CrossRef records by DOI, fetched at most once, *delay* seconds apart."""

    def __init__(self, delay: float = 1.0) -> None:
        self.delay = delay
        self._records: Dict[str, Tuple[Optional[Record], Optional[str]]] = {}
        self._last = 0.0

    def get(self, doi: str) -> Tuple[Optional[Record], Optional[str]]:
        doi = normalize_doi(doi)
        if not doi or is_arxiv_doi(doi):
            return None, "no DOI"
        if doi.lower() not in self._records:
            wait = self._last + self.delay - time.monotonic()
            if self._records and wait > 0:
                time.sleep(wait)
            self._records[doi.lower()] = crossref_record(doi)
            self._last = time.monotonic()
        return self._records[doi.lower()]


def entry_doi(entry: Mapping[str, str]) -> str:
    """The entry's DOI if it has a non-arXiv one, else ``""``."""
    doi = normalize_doi(entry.get("doi", ""))
    return "" if not doi or is_arxiv_doi(doi) else doi
