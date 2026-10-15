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
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Callable, Dict, Iterable, List, Mapping, Optional, Set, Tuple, Union

from bibcc.missing_venues import JOURNAL_FIELDS, PROCEEDINGS_FIELDS
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


def observe(entry: Mapping[str, str], library: VenueLibrary, fields: Iterable[str],
            ignored: Optional[Iterable[str]] = None) -> Optional[Observation]:
    """An :class:`Observation` of *fields* for *entry*'s venue, or None when it can't count.

    *fields* are the non-empty field names seen (the entry's own, or its
    official BibTeX's).  *ignored* (default: :data:`IGNORED_FIELDS`) and the
    fields the library supplies are dropped.  An entry without a venue or a
    year, or a journal article not in an issue yet, isn't observed.
    """
    venue = (entry.get("booktitle") or entry.get("journal") or "").strip()
    year = str(entry.get("year", "")).strip()
    if not venue or not year:
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
    drop |= set(JOURNAL_FIELDS if kind == JOURNAL else PROCEEDINGS_FIELDS)
    if record is not None:
        drop |= set(library.fields_of(record))
    return Observation(
        key=str(entry.get("ID", "")), kind=kind, year=year, group=group, label=label,
        fields=fields - drop, record=record, family=family, venue_name=name,
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

    @property
    def status(self) -> str:
        return SCHEMA_LACKS if not self.current else SCHEMA_DIFFERS

    @property
    def changes(self) -> bool:
        return sorted(self.fields) != sorted(self.current)

    @property
    def learned_from(self) -> str:
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
        return self.label

    @property
    def venue(self) -> str:
        """The report's venue column: the record's name, or the family's."""
        if isinstance(self.target, Venue):
            return self.target.name
        if isinstance(self.target, Family):
            return self.target.label
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
        return text

    def can_apply(self) -> bool:
        return self.level != "journal" or self.target is not None


def _shared(observations: List[Observation], share: float) -> List[str]:
    counts: Dict[str, int] = defaultdict(int)
    for item in observations:
        for name in item.fields:
            counts[name] += 1
    return sorted(n for n, c in counts.items() if c / len(observations) >= share)


def propose(observations: Iterable[Observation], library: VenueLibrary, source: str,
            min_entries: int = 1, share: float = SHARE) -> List[Proposal]:
    """The schemas that *observations* support and that the library doesn't have yet.

    Journals get one schema; proceedings get the schema of their latest
    observed year at the family level, and a year that differs gets an
    edition-level schema on its record.  A journal, or a year of a
    conference, with fewer than *min_entries* observations is left out.
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
        family_fields = _shared(by_year[latest], share)
        family = next((i.family for i in items if i.family is not None), None)
        names = sorted({i.venue_name for i in items})
        newest = max(items, key=lambda i: i.year)
        proposals.append(Proposal(
            "family", first.label, "", family_fields,
            list(family.entry_fields) if family is not None else [],
            [i.key for i in by_year[latest]], [latest], source, family,
            new_family_name="" if family is not None else family_label(newest.venue_name),
            venue_names=names,
        ))
        for year, group in sorted(by_year.items()):
            if year == latest:
                continue
            record = next((i.record for i in group if i.record is not None), None)
            if record is None:
                continue
            fields = _shared(group, share)
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
            log(f"   ⏭️  {where}: not in the venue library; to add the journal first, run "
                "bibcc complete FILE --update-venues")
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
