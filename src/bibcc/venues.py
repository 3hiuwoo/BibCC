"""
Venue library: reusable metadata for journals and conference proceedings.

The library is a YAML file (``data/venues.yaml`` by default) with two lists::

    journals:                 # year-agnostic, matched by name, alias, or ISSN
      - name: Pattern Recognition
        aliases: [Pattern Recognit.]
        fields:
          publisher: Elsevier
          issn: 0031-3203
    proceedings:              # matched by name or alias AND publication year
      - name: Computer Vision -- ECCV 2024
        year: "2025"
        fields:
          venue: Milan, Italy
          series: Lecture Notes in Computer Science

``year`` is the entry's publication year, which may differ from the edition
in the name (ECCV 2024 proceedings were published in 2025).

Usage:
    from bibcc.venues import VenueLibrary

    library = VenueLibrary.load()
    result = library.lookup("Pattern Recognition", year="2024", kind="journal")
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Mapping, Optional

import yaml

JOURNAL = "journal"
PROCEEDINGS = "proceedings"

DEFAULT_LIBRARY_PATH = Path(__file__).parent / "data" / "venues.yaml"
LIBRARY_ENV_VAR = "BIBCC_VENUES"

_LIBRARY_HEADER = """\
# BibCC venue library.
#
# journals:    matched by name, any alias, or ISSN (year-agnostic).
# proceedings: matched by name or alias AND the entry's publication year.
#
# This file is rewritten by `bibcc complete --update-venues`; comments other
# than this header are not preserved.
"""


def default_library_path() -> Path:
    """Return ``$BIBCC_VENUES`` if set, else the bundled library."""
    env = os.environ.get(LIBRARY_ENV_VAR)
    return Path(env).expanduser() if env else DEFAULT_LIBRARY_PATH


def normalize_venue(text: Optional[str]) -> str:
    """Normalize a venue name for matching.

    Drops braces, unescapes ``\\&``, collapses whitespace, and casefolds, so
    ``{IEEE} Trans.\\ \\& X`` and ``IEEE Trans. & X`` compare equal.
    """
    if not text:
        return ""
    text = text.replace("{", "").replace("}", "").replace("\\&", "&")
    return " ".join(text.split()).casefold()


def normalize_issn(text: Optional[str]) -> List[str]:
    """Split an ISSN field (possibly several, comma-separated) into bare digits."""
    if not text:
        return []
    return [
        re.sub(r"[^0-9X]", "", match.upper())
        for match in re.findall(r"\d{4}\s*-?\s*\d{3}[\dXx]", text)
    ]


@dataclass
class Venue:
    """One reusable venue record."""

    kind: str
    name: str
    fields: Dict[str, str] = field(default_factory=dict)
    year: Optional[str] = None
    aliases: List[str] = field(default_factory=list)

    @property
    def label(self) -> str:
        """Human-readable identity for logs and reports."""
        return f"{self.name} ({self.year})" if self.year else self.name

    def names(self) -> set[str]:
        """Normalized name plus aliases."""
        return {normalize_venue(n) for n in [self.name, *self.aliases]}

    def to_dict(self) -> Dict:
        """Serialize in the library's field order."""
        data: Dict = {"name": self.name}
        if self.kind == PROCEEDINGS:
            data["year"] = str(self.year or "")
        if self.aliases:
            data["aliases"] = list(self.aliases)
        data["fields"] = dict(self.fields)
        return data


@dataclass
class LookupResult:
    """Outcome of matching an entry against the library."""

    venue: Optional[Venue] = None
    ambiguous: List[Venue] = field(default_factory=list)


def _year_sort_key(venue: Venue) -> tuple:
    digits = "".join(ch for ch in str(venue.year or "") if ch.isdigit())
    return (-int(digits) if digits else 1, venue.name.casefold())


def _clean_fields(raw: Optional[Dict]) -> Dict[str, str]:
    """Keep non-empty fields as single-line strings."""
    out: Dict[str, str] = {}
    for key, value in (raw or {}).items():
        if value is None:
            continue
        text = " ".join(str(value).split())
        if text:
            out[str(key).lower()] = text
    return out


class VenueLibrary:
    """In-memory venue library with YAML load/save and lookup."""

    def __init__(
        self,
        journals: Optional[List[Venue]] = None,
        proceedings: Optional[List[Venue]] = None,
        path: Optional[Path] = None,
    ):
        self.journals: List[Venue] = journals or []
        self.proceedings: List[Venue] = proceedings or []
        self.path = path

    # ------------------------------------------------------------------ I/O

    @classmethod
    def load(cls, path: Optional[str | Path] = None) -> "VenueLibrary":
        """Load a library; a missing file yields an empty library."""
        lib_path = Path(path) if path else default_library_path()
        if not lib_path.exists():
            return cls(path=lib_path)
        data = yaml.safe_load(lib_path.read_text(encoding="utf-8")) or {}
        if not isinstance(data, dict):
            raise ValueError(f"{lib_path}: expected 'journals' and 'proceedings' lists")
        lib = cls(path=lib_path)
        for kind, key in ((JOURNAL, "journals"), (PROCEEDINGS, "proceedings")):
            for i, raw in enumerate(data.get(key) or []):
                lib._add(_venue_from_dict(raw, kind, f"{lib_path}: {key}[{i}]"))
        return lib

    def save(self, path: Optional[str | Path] = None) -> Path:
        """Write the library as sorted YAML and return the path written."""
        out = Path(path) if path else (self.path or default_library_path())
        out.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "journals": [v.to_dict() for v in sorted(self.journals, key=lambda v: v.name.casefold())],
            "proceedings": [v.to_dict() for v in sorted(self.proceedings, key=_year_sort_key)],
        }
        body = yaml.safe_dump(
            data, sort_keys=False, allow_unicode=True, width=1000, default_flow_style=False
        )
        out.write_text(_LIBRARY_HEADER + "\n" + body, encoding="utf-8")
        return out

    # --------------------------------------------------------------- access

    def _bucket(self, kind: str) -> List[Venue]:
        return self.journals if kind == JOURNAL else self.proceedings

    def _add(self, venue: Venue) -> None:
        self._bucket(venue.kind).append(venue)

    def __len__(self) -> int:
        return len(self.journals) + len(self.proceedings)

    def find_exact(self, kind: str, name: str, year: Optional[str] = None) -> Optional[Venue]:
        """Find a record by its canonical name (and year for proceedings)."""
        norm = normalize_venue(name)
        for venue in self._bucket(kind):
            if normalize_venue(venue.name) != norm:
                continue
            if kind == PROCEEDINGS and str(venue.year).strip() != str(year or "").strip():
                continue
            return venue
        return None

    def lookup(
        self,
        venue_text: str,
        year: Optional[str],
        kind: str,
        issn: Optional[str] = None,
    ) -> LookupResult:
        """Match an entry's journal/booktitle against the library.

        Journals match by name, alias, or ISSN; proceedings by name or alias
        plus publication year.  When several distinct records match, nothing
        is chosen and all candidates are returned as ``ambiguous``.
        """
        norm = normalize_venue(venue_text)
        year_text = str(year or "").strip()
        entry_issns = set(normalize_issn(issn))
        candidates: List[Venue] = []
        for venue in self._bucket(kind):
            if kind == PROCEEDINGS:
                if str(venue.year).strip() != year_text or norm not in venue.names():
                    continue
            else:
                by_name = bool(norm) and norm in venue.names()
                by_issn = bool(entry_issns & set(normalize_issn(venue.fields.get("issn"))))
                if not (by_name or by_issn):
                    continue
            candidates.append(venue)
        if len(candidates) == 1:
            return LookupResult(venue=candidates[0])
        return LookupResult(ambiguous=candidates)

    def upsert(self, venue: Venue) -> str:
        """Add *venue* or merge its fields into the existing record.

        Returns ``"added"``, ``"updated"``, or ``"unchanged"``.
        """
        existing = self.find_exact(venue.kind, venue.name, venue.year)
        if existing is None:
            self._add(venue)
            return "added"
        merged = {**existing.fields, **venue.fields}
        aliases = list(dict.fromkeys([*existing.aliases, *venue.aliases]))
        if merged == existing.fields and aliases == existing.aliases:
            return "unchanged"
        existing.fields = merged
        existing.aliases = aliases
        return "updated"


def venue_kind(entry_type: str, fields: Mapping[str, str]) -> str:
    """``JOURNAL`` or ``PROCEEDINGS`` for an entry, by type, then by venue field."""
    entry_type = (entry_type or "").lower()
    if entry_type == "article":
        return JOURNAL
    if entry_type in ("inproceedings", "proceedings", "conference"):
        return PROCEEDINGS
    if fields.get("journal"):
        return JOURNAL
    return PROCEEDINGS


_ORDINAL_WORDS = (
    r"\b(first|second|third|fourth|fifth|sixth|seventh|eighth|ninth|tenth|"
    r"eleventh|twelfth|thirteenth|fourteenth|fifteenth|sixteenth|seventeenth|"
    r"eighteenth|nineteenth|twentieth|thirtieth|fortieth)\b"
)

# Fields that usually stay the same from one conference edition to the next.
EDITION_STABLE_FIELDS = ["publisher", "issn", "month", "series", "address"]


def edition_key(name: str) -> str:
    """Venue name with years and ordinals removed, to relate editions."""
    text = normalize_venue(name)
    text = re.sub(r"\b(19|20)\d{2}\b", "#", text)
    text = re.sub(r"\b\d+(st|nd|rd|th)\b", "#", text)
    text = re.sub(_ORDINAL_WORDS, "#", text)
    text = re.sub(r"\b(twenty|thirty|forty)-#", "#", text)
    return " ".join(text.split())


def previous_edition(library: VenueLibrary, name: str, year: str) -> Optional[Venue]:
    """Most recent earlier proceedings record of the same conference series."""
    key = edition_key(name)
    best: Optional[Venue] = None
    for venue in library.proceedings:
        if edition_key(venue.name) != key or not str(venue.year).isdigit():
            continue
        if year.isdigit() and int(venue.year) >= int(year):
            continue
        if best is None or int(venue.year) > int(best.year):
            best = venue
    return best


def _venue_from_dict(raw: Dict, kind: str, where: str) -> Venue:
    """Build a Venue from a YAML mapping, validating required keys."""
    if not isinstance(raw, dict) or not str(raw.get("name") or "").strip():
        raise ValueError(f"{where}: every record needs a 'name'")
    year = raw.get("year")
    if kind == PROCEEDINGS and not str(year or "").strip():
        raise ValueError(f"{where}: proceedings record '{raw['name']}' needs a 'year'")
    aliases = raw.get("aliases") or []
    if isinstance(aliases, str):
        aliases = [aliases]
    return Venue(
        kind=kind,
        name=str(raw["name"]).strip(),
        fields=_clean_fields(raw.get("fields")),
        year=str(year).strip() if kind == PROCEEDINGS else None,
        aliases=[str(a).strip() for a in aliases if str(a).strip()],
    )


def load_missing_venues(path: str | Path) -> List[Venue]:
    """Read a ``*.missing_venues.yaml`` file (same schema as the library)."""
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    venues: List[Venue] = []
    for kind, key in ((JOURNAL, "journals"), (PROCEEDINGS, "proceedings")):
        for i, raw in enumerate(data.get(key) or []):
            venues.append(_venue_from_dict(raw, kind, f"{path}: {key}[{i}]"))
    return venues


def merge_missing_venues(
    library: VenueLibrary,
    missing_path: str | Path,
    log=print,
) -> Dict[str, int]:
    """Merge filled-in records from *missing_path* into *library* (in memory).

    Records whose fields are all empty are skipped so they keep being
    reported as missing instead of silently matching with nothing to add.
    """
    counts = {"added": 0, "updated": 0, "unchanged": 0, "skipped": 0}
    for venue in load_missing_venues(missing_path):
        if not venue.fields:
            counts["skipped"] += 1
            log(f"⏭️  Skipped (no fields filled in): {venue.label}")
            continue
        status = library.upsert(venue)
        counts[status] += 1
        icon = {"added": "➕", "updated": "📝", "unchanged": "⏭️ "}[status]
        log(f"{icon} {status.capitalize()} {venue.kind}: {venue.label}")
    return counts
