"""
Venue library: reusable metadata for journals and conference proceedings.

BibCC ships no library.  Each user builds their own, in two scopes:

* the **user** library, ``$BIBCC_VENUES`` if set, else
  ``$XDG_CONFIG_HOME/bibcc/venues.yaml`` (``~/.config/bibcc/venues.yaml``);
* the **project** library, the nearest ``.bibcc-venues.yaml`` in the folder
  of the ``.bib`` file or one of its parents.

Commands read both, merged by :func:`load_library`: a record defined in both
gets the project's value for every field both define.  Commands write one
scope only, through :func:`open_library` (the user library unless the
project scope is asked for).  ``--venues FILE`` replaces both with one file.
Shared libraries to start from live in the repository's ``examples/venues/``.

A library is a YAML file with two lists::

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

A proceedings record's ``name`` is the booktitle of the published proceedings
(IEEE Xplore, Springer, PMLR, the NeurIPS and ICLR proceedings sites).  Papers
are often cited earlier under another booktitle: CVF Open Access for CVPR,
ICCV, and WACV, or OpenReview for ICLR, NeurIPS, and ICML.  ``interim`` maps
each such source to the booktitle (or list of booktitles) it uses for the
same proceedings::

      - name: 2025 IEEE/CVF Conference on Computer Vision and Pattern Recognition (CVPR)
        year: "2025"
        interim:
          cvf:
            - Proceedings of the Computer Vision and Pattern Recognition Conference (CVPR)
            - Proceedings of the IEEE/CVF Conference on Computer Vision and Pattern Recognition (CVPR)

An entry whose booktitle is an interim name still matches the record, but
:meth:`VenueLibrary.lookup` says so (``interim_source``): such an entry is
not the published version, so it only receives the fields describing the
event itself (:data:`EVENT_FIELDS`), and ``bibcc upgrade`` can replace it.
A venue whose proceedings are not out yet keeps the interim booktitle as its
``name`` until they are.

Usage:
    from bibcc.venues import load_library, open_library

    library = load_library(start="bib/refs.bib")      # user + project, read-only
    result = library.lookup("Pattern Recognition", year="2024", kind="journal")

    target = open_library("project", start="bib/refs.bib")  # one file, writable
    target.upsert(venue)
    target.save()
"""

from __future__ import annotations

import copy
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Mapping, Optional, Tuple

import yaml

JOURNAL = "journal"
PROCEEDINGS = "proceedings"

USER_SCOPE = "user"
PROJECT_SCOPE = "project"
FILE_SCOPE = "file"  # a library named with --venues FILE
SCOPES = (USER_SCOPE, PROJECT_SCOPE)

LIBRARY_ENV_VAR = "BIBCC_VENUES"
PROJECT_LIBRARY_NAME = ".bibcc-venues.yaml"
USER_LIBRARY_DISPLAY = "~/.config/bibcc/venues.yaml"

_LIBRARY_HEADER = """\
# BibCC venue library.
#
# journals:    matched by name, any alias, or ISSN (year-agnostic).
# proceedings: matched by name or alias AND the entry's publication year.
#              name is the published proceedings' booktitle; interim maps a
#              source (cvf, openreview) to the booktitle it uses before or
#              instead of the proceedings.
#
# This file is rewritten by `bibcc complete --update-venues` and
# `bibcc venues import`; comments other than this header are not preserved.
"""


class LibraryNotFound(LookupError):
    """The scope asked for has no library file (only raised for the project scope)."""


def user_library_path() -> Path:
    """``$BIBCC_VENUES`` if set, else ``$XDG_CONFIG_HOME/bibcc/venues.yaml`` (``~/.config`` by default)."""
    env = os.environ.get(LIBRARY_ENV_VAR)
    if env:
        return Path(env).expanduser()
    config_home = os.environ.get("XDG_CONFIG_HOME") or "~/.config"
    return Path(config_home).expanduser() / "bibcc" / "venues.yaml"


def find_project_library(start: Optional[str | Path] = None) -> Optional[Path]:
    """The nearest ``.bibcc-venues.yaml`` in *start* (a file or folder; default: cwd) or its parents."""
    here = Path(start or Path.cwd()).expanduser().resolve()
    if not here.is_dir():
        here = here.parent
    for folder in (here, *here.parents):
        candidate = folder / PROJECT_LIBRARY_NAME
        if candidate.is_file():
            return candidate
    return None


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
    # source ("cvf", "openreview") -> booktitles that source uses for these proceedings
    interim: Dict[str, List[str]] = field(default_factory=dict)

    @property
    def label(self) -> str:
        """Human-readable identity for logs and reports."""
        return f"{self.name} ({self.year})" if self.year else self.name

    def names(self) -> set[str]:
        """Normalized name plus aliases."""
        return {normalize_venue(n) for n in [self.name, *self.aliases]}

    def interim_names(self) -> set[str]:
        """Normalized interim booktitles of every source."""
        return {normalize_venue(n) for names in self.interim.values() for n in names}

    def interim_source(self, venue_text: str) -> Optional[str]:
        """The source whose interim booktitle is *venue_text*, if any."""
        norm = normalize_venue(venue_text)
        for source, names in self.interim.items():
            if any(normalize_venue(n) == norm for n in names):
                return source
        return None

    def all_names(self) -> set[str]:
        """Normalized name, aliases, and interim booktitles."""
        return self.names() | self.interim_names()

    def add_interim(self, source: str, name: str) -> bool:
        """Record *name* as an interim booktitle of *source*; False if already known."""
        if normalize_venue(name) in self.all_names():
            return False
        self.interim.setdefault(source, []).append(name)
        return True

    def to_dict(self) -> Dict:
        """Serialize in the library's field order."""
        data: Dict = {"name": self.name}
        if self.kind == PROCEEDINGS:
            data["year"] = str(self.year or "")
        if self.aliases:
            data["aliases"] = list(self.aliases)
        if self.interim:
            data["interim"] = {s: n[0] if len(n) == 1 else list(n) for s, n in self.interim.items() if n}
        data["fields"] = dict(self.fields)
        return data


# Fields that describe the event rather than the publication; the only ones an
# entry citing an interim booktitle (CVF, OpenReview) receives from a record.
EVENT_FIELDS = ("venue", "month")


@dataclass
class LookupResult:
    """Outcome of matching an entry against the library."""

    venue: Optional[Venue] = None
    ambiguous: List[Venue] = field(default_factory=list)
    # Set when the entry matched through an interim booktitle of ``venue``.
    interim_source: Optional[str] = None


@dataclass
class LibrarySource:
    """One file a library was read from: its scope, path, and size."""

    scope: str
    path: Path
    exists: bool
    journals: int = 0
    proceedings: int = 0

    def describe(self, with_scope: bool = True) -> str:
        size = _counts(self.journals, self.proceedings) if self.exists else "not created yet"
        text = f"{self.path} ({size})"
        return f"{self.scope} {text}" if with_scope else text


@dataclass
class FieldConflict:
    """A field two records of the same venue give different values."""

    venue: str
    name: str
    kept: str
    other: str


def _counts(journals: int, proceedings: int) -> str:
    return f"{journals} journal{'s' * (journals != 1)}, {proceedings} proceedings"


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
        # The file save() writes; None for a merged view, which is read-only.
        self.path = path
        self.scope = FILE_SCOPE
        self.sources: List[LibrarySource] = []
        # Fields the project library overrode in a merged view.
        self.overrides: List[FieldConflict] = []

    # ------------------------------------------------------------------ I/O

    @classmethod
    def load(cls, path: str | Path, scope: str = FILE_SCOPE) -> "VenueLibrary":
        """Load one library file; a missing file yields an empty library that saves there."""
        lib_path = Path(path).expanduser()
        text = lib_path.read_text(encoding="utf-8") if lib_path.exists() else ""
        lib = cls.loads(text, where=str(lib_path))
        lib.path = lib_path
        lib.scope = scope
        lib.sources = [LibrarySource(scope, lib_path, lib_path.exists(), len(lib.journals), len(lib.proceedings))]
        return lib

    @classmethod
    def loads(cls, text: str, where: str = "<string>") -> "VenueLibrary":
        """Parse a library from YAML text (with no path, so it cannot be saved as is)."""
        data = yaml.safe_load(text) or {}
        if not isinstance(data, dict):
            raise ValueError(f"{where}: expected 'journals' and 'proceedings' lists")
        lib = cls()
        for kind, key in ((JOURNAL, "journals"), (PROCEEDINGS, "proceedings")):
            for i, raw in enumerate(data.get(key) or []):
                lib._add(_venue_from_dict(raw, kind, f"{where}: {key}[{i}]"))
        return lib

    def save(self, path: Optional[str | Path] = None) -> Path:
        """Write the library as sorted YAML and return the path written."""
        if path is None and self.path is None:
            raise ValueError(
                "this library has no file to save to (a merged view is read-only; "
                "write through open_library())"
            )
        out = Path(path) if path else self.path
        out.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "journals": [v.to_dict() for v in sorted(self.journals, key=lambda v: v.name.casefold())],
            "proceedings": [v.to_dict() for v in sorted(self.proceedings, key=_year_sort_key)],
        }
        body = yaml.safe_dump(
            data, sort_keys=False, allow_unicode=True, width=1000, default_flow_style=False
        )
        out.write_text(_LIBRARY_HEADER + "\n" + body, encoding="utf-8")
        if out == self.path:
            self.sources = [LibrarySource(self.scope, out, True, len(self.journals), len(self.proceedings))]
        return out

    def describe(self) -> str:
        """Where the library was read from, for logs; with a hint when it is empty."""
        if self.sources:
            text = " + ".join(source.describe() for source in self.sources)
        else:
            text = f"{self.path or '(in memory)'} ({_counts(len(self.journals), len(self.proceedings))})"
        if self.overrides:
            text += f"; the project overrides {len(self.overrides)} user field{'s' * (len(self.overrides) != 1)}"
        if not len(self):
            text += (
                "\n   The library is empty: --update-venues adds the venues you fill in, or start "
                "from a shared library (bibcc venues examples)."
            )
        return text

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

    def find_any(self, venue: Venue) -> Optional[Venue]:
        """The record *venue* refers to: same name first, else any shared name, alias, or interim booktitle."""
        exact = self.find_exact(venue.kind, venue.name, venue.year)
        if exact is not None:
            return exact
        wanted = venue.all_names()
        for other in self._bucket(venue.kind):
            if venue.kind == PROCEEDINGS and str(other.year).strip() != str(venue.year or "").strip():
                continue
            if wanted & other.all_names():
                return other
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
        plus publication year, or else by an interim booktitle (then
        ``interim_source`` names the source).  When several distinct records
        match, nothing is chosen and all candidates are returned as
        ``ambiguous``.
        """
        norm = normalize_venue(venue_text)
        year_text = str(year or "").strip()
        entry_issns = set(normalize_issn(issn))
        candidates: List[Venue] = []
        interim: List[Venue] = []
        for venue in self._bucket(kind):
            if kind == PROCEEDINGS:
                if str(venue.year).strip() != year_text:
                    continue
                if norm in venue.names():
                    candidates.append(venue)
                elif norm and norm in venue.interim_names():
                    interim.append(venue)
                continue
            by_name = bool(norm) and norm in venue.names()
            by_issn = bool(entry_issns & set(normalize_issn(venue.fields.get("issn"))))
            if by_name or by_issn:
                candidates.append(venue)
        if not candidates and len(interim) == 1:
            return LookupResult(venue=interim[0], interim_source=interim[0].interim_source(venue_text))
        if len(candidates) == 1:
            return LookupResult(venue=candidates[0])
        return LookupResult(ambiguous=candidates or interim)

    def upsert(self, venue: Venue, overwrite: bool = True) -> str:
        """Add *venue* or merge it into the record it refers to (see :meth:`find_any`).

        Fields and aliases are merged, interim booktitles are added, and a
        record found through one of *venue*'s interim booktitles is renamed
        to *venue*'s name: its proceedings are out under that name.  A field
        both define gets *venue*'s value, or keeps the existing one unless
        *overwrite*.  Returns ``"added"``, ``"updated"``, or ``"unchanged"``.
        """
        existing = self.find_any(venue)
        if existing is None:
            self._add(venue)
            return "added"
        before = existing.to_dict()
        if normalize_venue(existing.name) != normalize_venue(venue.name):
            if normalize_venue(existing.name) in venue.interim_names():
                existing.name = venue.name
            elif normalize_venue(venue.name) not in existing.all_names():
                existing.aliases.append(venue.name)
        if overwrite:
            existing.fields = {**existing.fields, **venue.fields}
        else:
            new = {k: v for k, v in venue.fields.items() if k not in existing.fields}
            existing.fields = {**existing.fields, **new}
        for alias in venue.aliases:
            if normalize_venue(alias) not in existing.all_names():
                existing.aliases.append(alias)
        for source, names in venue.interim.items():
            for name in names:
                existing.add_interim(source, name)
        existing.aliases = [a for a in existing.aliases if normalize_venue(a) != normalize_venue(existing.name)]
        return "unchanged" if existing.to_dict() == before else "updated"


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
    raw_interim = raw.get("interim") or {}
    if not isinstance(raw_interim, dict):
        raise ValueError(f"{where}: 'interim' must map a source (cvf, openreview) to booktitles")
    interim: Dict[str, List[str]] = {}
    for source, names in raw_interim.items():
        names = [names] if isinstance(names, str) else list(names or [])
        cleaned = [" ".join(str(n).split()) for n in names if str(n or "").strip()]
        if cleaned:
            interim[str(source).strip().lower()] = cleaned
    return Venue(
        kind=kind,
        name=str(raw["name"]).strip(),
        fields=_clean_fields(raw.get("fields")),
        year=str(year).strip() if kind == PROCEEDINGS else None,
        aliases=[str(a).strip() for a in aliases if str(a).strip()],
        interim=interim,
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

    Records with no field and no interim booktitle filled in are skipped so
    they keep being reported as missing instead of silently matching with
    nothing to add.
    """
    counts = {"added": 0, "updated": 0, "unchanged": 0, "skipped": 0}
    for venue in load_missing_venues(missing_path):
        if not venue.fields and not venue.interim:
            counts["skipped"] += 1
            log(f"⏭️  Skipped (no fields filled in): {venue.label}")
            continue
        status = library.upsert(venue)
        counts[status] += 1
        icon = {"added": "➕", "updated": "📝", "unchanged": "⏭️ "}[status]
        log(f"{icon} {status.capitalize()} {venue.kind}: {venue.label}")
    return counts


# ------------------------------------------------------------------- scopes


def merge_records(
    target: VenueLibrary, venues: Iterable[Venue], overwrite: bool
) -> Tuple[Dict[str, int], List[FieldConflict]]:
    """Upsert copies of *venues* into *target*.

    Returns the ``added``/``updated``/``unchanged`` counts and the fields
    where a record of *target* and one of *venues* disagree; ``kept`` is the
    value *target* ends up with (the incoming one if *overwrite*).
    """
    counts = {"added": 0, "updated": 0, "unchanged": 0}
    conflicts: List[FieldConflict] = []
    for venue in venues:
        venue = copy.deepcopy(venue)
        existing = target.find_any(venue)
        if existing is not None:
            for name, value in venue.fields.items():
                old = existing.fields.get(name)
                if old is not None and old != value:
                    kept, other = (value, old) if overwrite else (old, value)
                    conflicts.append(FieldConflict(existing.label, name, kept, other))
        counts[target.upsert(venue, overwrite=overwrite)] += 1
    return counts, conflicts


def load_library(venues: Optional[str | Path] = None, start: Optional[str | Path] = None) -> VenueLibrary:
    """The library a command reads.

    With *venues*, that file alone.  Otherwise the user library merged with
    the nearest project library above *start* (a ``.bib`` file or folder;
    default: cwd): the project's records are merged into the user's, and
    where both define a field the project's value wins (listed in
    ``overrides``).  A merged view has no ``path`` and cannot be saved.
    """
    if venues:
        return VenueLibrary.load(venues)
    library = VenueLibrary.load(user_library_path(), scope=USER_SCOPE)
    project_path = find_project_library(start)
    if project_path is None:
        return library
    project = VenueLibrary.load(project_path, scope=PROJECT_SCOPE)
    _, library.overrides = merge_records(library, project.journals + project.proceedings, overwrite=True)
    library.sources += project.sources
    library.path = None
    library.scope = "merged"
    return library


def open_library(
    scope: str = USER_SCOPE,
    venues: Optional[str | Path] = None,
    start: Optional[str | Path] = None,
    create: bool = False,
) -> VenueLibrary:
    """The one library file a command writes to.

    *venues* names it directly.  Otherwise *scope* picks the user library or
    the nearest project library above *start*.  When there is no project
    library, :class:`LibraryNotFound` is raised, unless *create*: then the
    library is ``.bibcc-venues.yaml`` in the current directory (written on
    the first save).
    """
    if venues:
        return VenueLibrary.load(venues)
    if scope == USER_SCOPE:
        return VenueLibrary.load(user_library_path(), scope=USER_SCOPE)
    if scope != PROJECT_SCOPE:
        raise ValueError(f"unknown venue library scope {scope!r} (use one of {', '.join(SCOPES)})")
    path = find_project_library(start)
    if path is None:
        if not create:
            where = Path(start or Path.cwd()).expanduser().resolve()
            raise LibraryNotFound(
                f"no {PROJECT_LIBRARY_NAME} in {where} or its parent folders; create one in your "
                "project root with: bibcc venues init --scope project"
            )
        path = Path.cwd() / PROJECT_LIBRARY_NAME
    return VenueLibrary.load(path, scope=PROJECT_SCOPE)
