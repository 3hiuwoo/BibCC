"""
Venue schemas: the per-paper fields that a venue's official BibTeX has.

A venue library record (a journal, a family of proceedings, or one edition)
can carry ``entry_fields``, the fields such as ``pages``, ``doi``, and
``url`` that the official BibTeX of every paper of the venue has (see
:mod:`bibcc.venues`).  With a schema in the library, ``check editions``
compares each entry with its venue's schema instead of with the other
entries you happen to have, and ``check missing`` doesn't ask for a field
that the venue never exports.

Schemas are learned, not written by hand:

* ``bibcc check official FILE --learn`` learns them from the official
  BibTeX it downloads, the reliable source;
* ``bibcc check editions FILE --learn`` learns them by comparing the entries
  of each venue with one another, for venues whose BibTeX BibCC can't
  download (AAAI, ACM, Elsevier).

A schema leaves out the fields every entry has (title, author, year, and
the venue name), the fields the venue library supplies (publisher, ISSN,
and so on, and a conference's month), and exporter bookkeeping.  A field counts when at least
:data:`SHARE` of the observed entries have it.  For proceedings, the latest
year's fields become the family's schema, and a year whose fields differ
gets its own schema on its edition record, when the library has one.

An article not yet in an issue (IEEE Early Access, Springer Online First)
has no volume, number, or pages yet; :func:`awaiting_issue` says so, such
an article doesn't count toward a schema, and the checks don't expect
those fields from it.

Usage:
    from bibcc.schemas import observe, propose, apply_proposals

    seen = [observe(entry, library, fields) for entry, fields in pairs]
    proposals = propose([s for s in seen if s], library, OFFICIAL)
    apply_proposals(target_library, proposals, log)
"""

from __future__ import annotations

import datetime
import re
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Callable, Dict, Iterable, List, Mapping, Optional, Set, Tuple, Union

from bibcc.missing_venues import JOURNAL_FIELDS, PROCEEDINGS_FIELDS, MissingVenue, guess_publisher
from bibcc.venues import (
    JOURNAL,
    PROCEEDINGS,
    SCOPES,
    Family,
    Venue,
    VenueLibrary,
    edition_group,
    family_label,
    normalize_venue,
    venue_kind,
)

# Fields a schema never lists: every compared entry has them, BibCC writes
# them itself, or exporters add them for bookkeeping.
IGNORED_FIELDS: Tuple[str, ...] = (
    "title", "author", "year", "booktitle", "journal",
    "citation",
    "annote", "bibsource", "biburl", "copyright", "mendeley-groups", "timestamp", "urldate",
)
# Entry types that belong to a journal or a conference; a book chapter's
# booktitle names a book, not a venue with editions.
VENUE_TYPES = ("article", "inproceedings", "conference", "proceedings")
# Fields an article gets only once it's in an issue.
ISSUE_FIELDS = ("volume", "number", "pages")

SHARE = 0.75  # share of the observed entries that must have a field
MIN_PEERS = 3  # entries of a journal, or of one conference year, that a peer comparison needs

OFFICIAL = "official BibTeX"
PEERS = "peer comparison"

# Issue types of a proposal, in the official_venues.txt and edition_schemas.txt reports.
SCHEMA_LACKS = "schema_lacks"  # the library has no schema for the venue
SCHEMA_DIFFERS = "schema_differs"  # the library's schema differs from what the BibTeX shows
SCHEMA_STATUSES = (SCHEMA_LACKS, SCHEMA_DIFFERS)


def awaiting_issue(entry: Mapping[str, str]) -> bool:
    """Whether a journal entry isn't in an issue yet (no volume): Early Access or Online First."""
    if venue_kind(entry.get("ENTRYTYPE", ""), entry) != JOURNAL:
        return False
    return not str(entry.get("volume", "")).strip()


@dataclass
class Observation:
    """The fields one entry (or its official BibTeX) has, and the venue it belongs to."""

    key: str
    kind: str
    year: str
    group: str
    label: str
    fields: Set[str]
    record: Optional[Venue] = None
    family: Optional[Family] = None
    venue_name: str = ""
    # Values of the fields a venue record holds (publisher, ISSN, and so on), for a record the library lacks.
    values: Dict[str, str] = field(default_factory=dict)


def observe(entry: Mapping[str, str], library: VenueLibrary, fields: Iterable[str],
            ignored: Optional[Iterable[str]] = None,
            values: Optional[Mapping[str, str]] = None) -> Optional[Observation]:
    """An :class:`Observation` of *fields* for *entry*'s venue, or None when it can't count.

    *fields* are the non-empty field names seen (the entry's own, or its
    official BibTeX's).  *ignored* (default: :data:`IGNORED_FIELDS`) and the
    fields the library supplies are dropped.  An entry without a venue or a
    year, a book or chapter (not one of :data:`VENUE_TYPES`), or a journal
    article not in an issue yet, isn't observed.  *values* (default: the
    entry) holds the values of the record fields, for :func:`missing_records`.
    """
    venue = (entry.get("booktitle") or entry.get("journal") or "").strip()
    year = str(entry.get("year", "")).strip()
    entry_type = str(entry.get("ENTRYTYPE", "")).lower()
    if not venue or not year or (entry_type and entry_type not in VENUE_TYPES):
        return None
    fields = {f.lower() for f in fields}
    kind = venue_kind(entry.get("ENTRYTYPE", ""), entry)
    if kind == JOURNAL and "volume" not in fields:
        return None
    record = library.lookup(venue, year, kind, issn=entry.get("issn")).venue
    name = record.name if record is not None else venue
    family = library.family_of(name) if kind == PROCEEDINGS else None
    if kind == JOURNAL:
        group, label = "journal:" + normalize_venue(name), name
    else:
        group = edition_group(library, name)
        label = family.label if family is not None else family_label(name)
    drop = {f.lower() for f in (IGNORED_FIELDS if ignored is None else ignored)} | {"id", "entrytype"}
    record_fields = JOURNAL_FIELDS if kind == JOURNAL else PROCEEDINGS_FIELDS
    drop |= set(record_fields)
    if record is not None:
        drop |= set(library.fields_of(record))
    source = entry if values is None else values
    seen = {n: " ".join(str(source.get(n, "")).split()) for n in record_fields}
    return Observation(
        key=str(entry.get("ID", "")), kind=kind, year=year, group=group, label=label,
        fields=fields - drop, record=record, family=family, venue_name=name,
        values={n: v for n, v in seen.items() if v},
    )


@dataclass
class Proposal:
    """A schema the observations support for one venue (a journal, a family, or one edition)."""

    level: str  # "journal", "family", or "edition"
    label: str
    year: str  # the edition's year; "" for a journal or a family
    fields: List[str]
    current: List[str]
    entries: List[str]
    years: List[str]
    source: str
    target: Union[Venue, Family, None] = None
    # For a family the library doesn't have yet: the name it would get, and its venue names.
    new_family_name: str = ""
    venue_names: List[str] = field(default_factory=list)
    # A family schema that moves down to an edition keeps where it was learned.
    origin: str = ""
    # For a journal or an edition the library has no record of: the record
    # fields every observed entry agrees on, and the entries they come from.
    values: Dict[str, str] = field(default_factory=dict)
    value_keys: Dict[str, List[str]] = field(default_factory=dict)

    @property
    def needs_record(self) -> bool:
        """A journal or edition schema without its record in the library: it waits in missing_venues.yaml."""
        return self.level != "family" and self.target is None

    @property
    def status(self) -> str:
        return SCHEMA_LACKS if not self.current else SCHEMA_DIFFERS

    @property
    def changes(self) -> bool:
        return sorted(self.fields) != sorted(self.current)

    @property
    def learned_from(self) -> str:
        if self.origin:
            return self.origin
        n = len(self.entries)
        years = ", ".join(sorted(set(self.years)))
        return f"{self.source} of {n} entr{'y' if n == 1 else 'ies'} ({years}), {datetime.date.today().isoformat()}"

    @property
    def where(self) -> str:
        """The record the schema belongs to, for logs and reports."""
        if isinstance(self.target, Venue):
            return self.target.label
        if self.level == "family":
            name = self.target.label if isinstance(self.target, Family) else self.new_family_name
            return f"family {name}"
        return f"{self.venue} ({self.year})" if self.year else self.venue

    @property
    def venue(self) -> str:
        """The report's venue column: the record's name, or the family's."""
        if isinstance(self.target, Venue):
            return self.target.name
        if isinstance(self.target, Family):
            return self.target.label
        if self.needs_record and self.venue_names:
            return self.venue_names[0]
        return self.new_family_name or self.label

    def detail(self) -> str:
        new = ", ".join(self.fields) or "(none)"
        years = ", ".join(sorted(set(self.years)))
        level = "family" if self.level == "family" else "record"
        text = f"{self.source} ({years}): {new}"
        if self.current:
            return f"library {level}: {', '.join(self.current)}; {text}"
        if self.level == "family" and not isinstance(self.target, Family):
            return f"no family record yet; {text}"
        if self.needs_record:
            return f"no record yet; {text}"
        return text

    def can_apply(self) -> bool:
        return not self.needs_record


def _shared(observations: List[Observation], share: float) -> List[str]:
    counts: Dict[str, int] = defaultdict(int)
    for item in observations:
        for name in item.fields:
            counts[name] += 1
    return sorted(n for n, c in counts.items() if c / len(observations) >= share)


def _agreed(observations: List[Observation]) -> Tuple[Dict[str, str], Dict[str, List[str]]]:
    """The record field values that every observation having them agrees on, and their entries."""
    values: Dict[str, str] = {}
    keys: Dict[str, List[str]] = {}
    for name in sorted({n for item in observations for n in item.values}):
        having = [item for item in observations if item.values.get(name)]
        if len({normalize_venue(item.values[name]) for item in having}) == 1:
            values[name] = having[0].values[name]
            keys[name] = [item.key for item in having]
    return values, keys


def _record_proposal(level: str, items: List[Observation], year: str, fields: List[str],
                     source: str) -> Proposal:
    """A schema for a journal or an edition that the library has no record of."""
    counts: Dict[str, int] = defaultdict(int)
    for item in items:
        counts[item.venue_name] += 1
    name = max(sorted(counts), key=lambda n: counts[n])
    values, keys = _agreed(items)
    return Proposal(
        level, items[0].label, year, fields, [], [i.key for i in items], [i.year for i in items],
        source, None, venue_names=[name], values=values, value_keys=keys,
    )


def _year_number(year: str) -> int:
    return int(year) if year.isdigit() else -1


def learned_years(learned_from: str) -> List[int]:
    """The years in a ``learned_from`` note ("official BibTeX of 5 entries (2023, 2024), DATE")."""
    match = re.search(r"\(([^)]*)\)", learned_from or "")
    return sorted(int(y) for y in re.findall(r"\b(?:19|20)\d{2}\b", match.group(1))) if match else []


def _newer_schema(record: Union[Venue, Family, None], year: str) -> bool:
    """Whether *record*'s schema was learned from a later year than *year*: older evidence keeps it."""
    if record is None or not record.entry_fields:
        return False
    years = learned_years(record.learned_from)
    return bool(years) and years[-1] > _year_number(year)


def _editions_of(library: VenueLibrary, group: str, year: int) -> List[Venue]:
    return [v for v in library.proceedings
            if _year_number(str(v.year or "").strip()) == year and edition_group(library, v.name) == group]


def propose(observations: Iterable[Observation], library: VenueLibrary, source: str,
            min_entries: int = 1, share: float = SHARE) -> List[Proposal]:
    """The schemas that *observations* support and that the library doesn't have yet.

    Journals get one schema; proceedings get the schema of their latest
    observed year at the family level, and a year that differs gets an
    edition-level schema on its record.  A journal, or a year of a
    conference, with fewer than *min_entries* observations is left out.

    A journal, or an edition whose schema differs from its family's, that
    the library has no record of still gets a proposal (see
    :attr:`Proposal.needs_record` and :func:`missing_records`).

    Evidence never replaces a schema learned from a later year: a journal
    keeps it, and a family keeps it while each observed year is compared
    with it as an edition.  When a later year replaces a family schema, the
    old schema moves to the edition records of the years it was learned
    from that have none, so those editions keep being checked against it.
    """
    groups: Dict[str, List[Observation]] = defaultdict(list)
    for item in observations:
        groups[item.group].append(item)
    proposals: List[Proposal] = []
    for _, items in sorted(groups.items()):
        if len(items) < min_entries:
            continue
        first = items[0]
        if first.kind == JOURNAL:
            record = next((i.record for i in items if i.record is not None), None)
            if _newer_schema(record, max((i.year for i in items), key=_year_number)):
                continue
            if record is None:
                proposals.append(_record_proposal("journal", items, "", _shared(items, share), source))
                continue
            proposals.append(Proposal(
                "journal", first.label, "", _shared(items, share),
                list(record.entry_fields) if record is not None else [],
                [i.key for i in items], [i.year for i in items], source, record,
            ))
            continue
        by_year: Dict[str, List[Observation]] = defaultdict(list)
        for item in items:
            by_year[item.year].append(item)
        by_year = {y: group for y, group in by_year.items() if len(group) >= min_entries}
        if not by_year:
            continue
        latest = max(by_year, key=lambda y: (y.isdigit(), y))
        family = next((i.family for i in items if i.family is not None), None)
        if family is not None and _newer_schema(family, latest):
            family_fields = list(family.entry_fields)
            latest = ""
        else:
            family_fields = _shared(by_year[latest], share)
            names = sorted({i.venue_name for i in items})
            newest = max(items, key=lambda i: i.year)
            proposals.append(Proposal(
                "family", first.label, "", family_fields,
                list(family.entry_fields) if family is not None else [],
                [i.key for i in by_year[latest]], [latest], source, family,
                new_family_name="" if family is not None else family_label(newest.venue_name),
                venue_names=names,
            ))
            if family is not None and family.entry_fields and sorted(family.entry_fields) != family_fields:
                for old in learned_years(family.learned_from):
                    if str(old) in by_year:
                        continue
                    for record in _editions_of(library, first.group, old):
                        if not record.entry_fields:
                            proposals.append(Proposal(
                                "edition", first.label, str(old), list(family.entry_fields), [],
                                [], [str(old)], source, record, origin=family.learned_from,
                            ))
        for year, group in sorted(by_year.items()):
            if year == latest:
                continue
            record = next((i.record for i in group if i.record is not None), None)
            fields = _shared(group, share)
            if record is None:
                if fields != family_fields:
                    proposals.append(_record_proposal("edition", group, year, fields, source))
                continue
            if fields == family_fields and not record.entry_fields:
                continue
            proposals.append(Proposal(
                "edition", first.label, year, fields, list(record.entry_fields),
                [i.key for i in group], [year], source, record,
            ))
    return [p for p in proposals if p.changes]


def apply_proposals(target: VenueLibrary, proposals: Iterable[Proposal], log: Callable[[str], None]) -> int:
    """Write the schemas of *proposals* into *target* (one library file); returns how many changed.

    A journal schema needs the journal's record; a family schema creates
    the family record when the library has none.
    """
    # Imported here: bibcc.families imports bibcc.venues, which this module also needs first.
    from bibcc.families import registry

    reg = registry(target)
    changed = 0
    for proposal in proposals:
        where = proposal.where
        if not proposal.can_apply():
            log(f"   ⏭️  {where}: not in the venue library yet; its schema goes into the fill-in "
                "record in missing_venues.yaml")
            continue
        existing: Union[Venue, Family, None]
        if proposal.level == "family":
            source = proposal.target if isinstance(proposal.target, Family) else None
            if source is not None:
                existing = target.find_family(source)
            else:
                acronym = reg.acronym_of(proposal.new_family_name, target)
                new = Family(name=proposal.new_family_name, acronym=acronym if reg.get(acronym) else "")
                existing = target.find_family(new)
                if existing is None:
                    target.families.append(new)
                    existing = new
        else:
            assert isinstance(proposal.target, Venue)
            source = proposal.target
            existing = target.find_any(proposal.target)
        if existing is None:
            other = source.origin if source is not None and source.origin in SCOPES else ""
            hint = f"; to write there, pass --scope {other}" if other else ""
            log(f"   ⏭️  {where}: its record is in another venue library{hint}")
            continue
        if list(existing.entry_fields) == list(proposal.fields):
            continue
        existing.entry_fields = list(proposal.fields)
        existing.learned_from = proposal.learned_from if proposal.fields else ""
        changed += 1
        log(f"   📝 {where}: entry_fields {', '.join(proposal.fields) or '(none)'}")
    return changed


def missing_records(proposals: Iterable[Proposal], collected_label: str) -> List[MissingVenue]:
    """Fill-in records for the proposals whose journal or edition record the library lacks.

    Each record carries the schema and the record fields that its entries
    agree on (*collected_label*, such as ``from official BibTeX``), so one
    ``bibcc complete --update-venues`` adds both.
    """
    records: List[MissingVenue] = []
    for p in proposals:
        if not p.needs_record or not p.fields:
            continue
        records.append(MissingVenue(
            JOURNAL if p.level == "journal" else PROCEEDINGS, p.venue, p.year,
            collected=dict(p.values), collected_label=collected_label,
            collected_from={n: list(k) for n, k in p.value_keys.items()},
            entries=list(p.entries), entry_fields=list(p.fields), learned_from=p.learned_from,
        ))
    return records


MIN_DEFAULT_VENUES = 2  # schemas of one publisher and kind that a publisher default needs

# DOI-prefix providers (bibcc/data/families.yaml) whose name doesn't say the publisher.
_PROVIDER_PUBLISHERS = {"xplore": "IEEE"}


@dataclass
class PublisherDefault:
    """The schema most venues of one publisher and kind share: a guess for a venue without one."""

    publisher: str
    kind: str
    fields: List[str]
    venues: List[str]

    @property
    def label(self) -> str:
        what = "journals" if self.kind == JOURNAL else "proceedings"
        return f"{self.publisher} {what}"

    def evidence(self) -> str:
        names = ", ".join(self.venues[:3]) + (f", and {len(self.venues) - 3} more" if len(self.venues) > 3 else "")
        return f"in the default schema of {self.label}, from {len(self.venues)} venues ({names}); a guess"


def publisher_key(publisher: str) -> str:
    """The publisher a ``publisher`` value names, the same for its spellings ("Elsevier BV", "Elsevier")."""
    return guess_publisher(publisher) or " ".join(normalize_venue(publisher).split())


def publisher_defaults(library: VenueLibrary, share: float = SHARE,
                       min_venues: int = MIN_DEFAULT_VENUES) -> Dict[Tuple[str, str], PublisherDefault]:
    """The default schema of each publisher and kind, from the schemas in *library*.

    Every journal, family, and edition schema counts once, under the
    publisher its record (or its family) names; a field counts when at least
    *share* of them list it.  A default is never written to the library.
    """
    units: Dict[Tuple[str, str], Dict[str, List[str]]] = defaultdict(dict)
    spelling: Dict[str, str] = {}  # publisher key -> how the library spells it, for display
    for publisher in [j.fields.get("publisher", "") for j in library.journals] + \
            [library.fields_of(v).get("publisher", "") for v in library.proceedings] + \
            [f.fields.get("publisher", "") for f in library.families]:
        if publisher_key(publisher):
            spelling.setdefault(publisher_key(publisher), guess_publisher(publisher) or publisher)
    for journal in library.journals:
        key = publisher_key(journal.fields.get("publisher", ""))
        if journal.entry_fields and key:
            units[(key, JOURNAL)][journal.name] = journal.entry_fields
    for family in library.families:
        if not family.entry_fields:
            continue
        publisher = family.fields.get("publisher", "")
        if not publisher:
            editions = [v for v in library.proceedings if library.family_of(v.name) is family]
            publisher = next((v.fields["publisher"] for v in editions if v.fields.get("publisher")), "")
        if publisher_key(publisher):
            units[(publisher_key(publisher), PROCEEDINGS)][family.label] = family.entry_fields
    for record in library.proceedings:
        key = publisher_key(library.fields_of(record).get("publisher", ""))
        if record.entry_fields and key:
            family = library.family_of(record.name)
            if family is None or not family.entry_fields:
                units[(key, PROCEEDINGS)].setdefault(family_label(record.name), record.entry_fields)
    defaults: Dict[Tuple[str, str], PublisherDefault] = {}
    for (key, kind), schemas in sorted(units.items()):
        if len(schemas) < min_venues:
            continue
        counts: Dict[str, int] = defaultdict(int)
        for fields in schemas.values():
            for name in fields:
                counts[name] += 1
        fields = sorted(n for n, c in counts.items() if c / len(schemas) >= share)
        if fields:
            defaults[(key, kind)] = PublisherDefault(spelling.get(key, key), kind, fields, sorted(schemas))
    return defaults


def entry_publisher(entry: Mapping[str, str], library: VenueLibrary, record: Optional[Venue]) -> str:
    """The publisher of an entry: its record's, its own, its venue name's, or its DOI prefix's."""
    if record is not None and library.fields_of(record).get("publisher"):
        return publisher_key(library.fields_of(record)["publisher"])
    if str(entry.get("publisher", "")).strip():
        return publisher_key(entry["publisher"])
    venue = entry.get("booktitle") or entry.get("journal") or ""
    if guess_publisher(venue):
        return guess_publisher(venue)
    # Imported here: bibcc.families imports bibcc.venues, which this module also needs first.
    from bibcc.families import registry
    from bibcc.sources import normalize_doi

    prefix = normalize_doi(entry.get("doi", "")).split("/", 1)[0]
    if not prefix:
        return ""
    reg = registry(library)
    name = reg.blocked_prefixes.get(prefix) or reg.doi_prefixes.get(prefix, "")
    return guess_publisher(_PROVIDER_PUBLISHERS.get(name, name))


def default_for(entry: Mapping[str, str], library: VenueLibrary, record: Optional[Venue],
                defaults: Mapping[Tuple[str, str], PublisherDefault]) -> Optional[PublisherDefault]:
    """The publisher default that applies to *entry*, or None."""
    if not defaults:
        return None
    publisher = entry_publisher(entry, library, record)
    return defaults.get((publisher, venue_kind(entry.get("ENTRYTYPE", ""), entry))) if publisher else None


def expected_fields(entry: Mapping[str, str], library: VenueLibrary) -> Tuple[List[str], str, Optional[Venue]]:
    """``(schema fields, where the schema comes from, record)`` for an entry; ``([], "", record)`` without one."""
    venue = (entry.get("booktitle") or entry.get("journal") or "").strip()
    year = str(entry.get("year", "")).strip()
    if not venue:
        return [], "", None
    kind = venue_kind(entry.get("ENTRYTYPE", ""), entry)
    result = library.lookup(venue, year, kind, issn=entry.get("issn"))
    record = result.venue
    if kind == JOURNAL and record is None:
        return [], "", None
    fields, origin = library.schema_of(record, venue)
    return fields, origin, record
