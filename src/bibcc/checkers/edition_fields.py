"""
Schema check for BibTeX entries: the per-paper fields their venue exports.

The venue library can hold each venue's *schema*, the fields (such as
``pages``, ``doi``, and ``url``) that the official BibTeX of every paper of
the venue has (see :mod:`bibcc.schemas`).  This check reports, for each
entry of a .bib file, the fields of its venue's schema that the entry
lacks (``missing``).  A journal article not yet in an issue isn't expected
to have a volume, number, or pages.

For a venue without a schema, the check compares the entries of the
venue, in the file and in the ``--against`` files, with one another, and
proposes the schema that most of them share (``schema_lacks``).  It never
reports an entry from that comparison alone: ``learn`` writes the proposals
into the venue library first, and the entries are then checked against
them.  A schema learned from official BibTeX (``bibcc check official
--learn``) is the more reliable one; the comparison is for venues whose
BibTeX BibCC can't download.

An entry whose venue has no schema still gets ``default_missing`` rows when
its publisher has a *default schema*: the fields that most of the library's
schemas of the same publisher and kind share (see
:func:`bibcc.schemas.publisher_defaults`).  A default is a labeled guess:
it never replaces a venue's own schema, ``--strict`` doesn't count it, and
``learn`` never writes it.

Fields in :data:`DEFAULT_IGNORED_FIELDS` (the fields every compared entry
has, BibCC's own ``citation``, and exporter bookkeeping) are never compared.
Entries that cite an interim (CVF or OpenReview) booktitle, entries built
from metadata, and empty entries are left out: they lack fields by design.

Usage:
    from bibcc.checkers.edition_fields import check_edition_fields

    result = check_edition_fields("refs.bib", library, against=["bib/"])
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional, Sequence, Set, Tuple

import bibtexparser

from bibcc.bibedit import read_bib
from bibcc.logging_utils import SEPARATOR_LIGHT, SEPARATOR_WIDTH
from bibcc.schemas import (
    IGNORED_FIELDS,
    ISSUE_FIELDS,
    MIN_PEERS,
    PEERS,
    VENUE_TYPES,
    Observation,
    Proposal,
    PublisherDefault,
    apply_proposals,
    awaiting_issue,
    default_for,
    expected_fields,
    observe,
    propose,
    publisher_defaults,
)
from bibcc.venues import PROCEEDINGS, VenueLibrary, family_label, has_no_month, venue_kind

DEFAULT_IGNORED_FIELDS: Tuple[str, ...] = IGNORED_FIELDS

MISSING = "missing"
# A field of the publisher default (see bibcc.schemas.publisher_defaults) that an
# entry of a venue without a schema lacks: a hint, not counted by --strict.
DEFAULT_MISSING = "default_missing"
FIELD_STATUSES = (MISSING, DEFAULT_MISSING)

Row = Tuple[str, str, str, str, str, str]  # (entry_id, venue, year, field, issue_type, evidence)
SchemaRow = Tuple[str, str, str, str, str, str, str]  # (venue, year, level, issue_type, entries, fields, detail)

FIELDS_HEADER = "edition fields: entry_id\tvenue\tyear\tfield\tissue_type\tevidence"
SCHEMAS_HEADER = "edition schemas: venue\tyear\tlevel\tissue_type\tentries\tfields\tdetail"


@dataclass
class EditionCheck:
    """What :func:`check_edition_fields` found."""

    fields: List[Row] = field(default_factory=list)
    schemas: List[SchemaRow] = field(default_factory=list)
    proposals: List[Proposal] = field(default_factory=list)
    checked: int = 0  # input entries whose venue has a schema
    unschematized: Dict[str, List[str]] = field(default_factory=dict)  # venue label -> input keys
    learned: int = 0
    guessed: int = 0  # entries without a schema that lack fields of their publisher's default

    @property
    def missing(self) -> int:
        """The ``missing`` rows, the findings that --strict counts."""
        return sum(row[4] == MISSING for row in self.fields)


@dataclass
class _Entry:
    entry: Dict[str, str]
    fields: Set[str]
    in_input: bool


def _bib_files(paths: Iterable[str | Path], exclude: Path, log: Callable[[str], None]) -> List[Path]:
    excluded = exclude.resolve()
    files: List[Path] = []
    for raw in paths:
        path = Path(raw)
        if path.is_dir():
            found = sorted(
                p for p in path.rglob("*.bib")
                if not any(part.startswith(".") for part in p.relative_to(path).parts)
            )
        elif path.is_file():
            found = [path]
        else:
            log(f"⚠️  --against path not found: {path}")
            continue
        files += [p for p in found if p.resolve() != excluded and p not in files]
    return files


def _entries(
    path: Path,
    in_input: bool,
    library: VenueLibrary,
    out: List[_Entry],
    skipped: Dict[str, int],
    seen: Set[str],
) -> int:
    # Imported here: bibcc.adder and bibcc.official import this package.
    from bibcc.adder import metadata_keys
    from bibcc.official import interim_source_of

    text = read_bib(path)
    parser = bibtexparser.bparser.BibTexParser(common_strings=True)
    entries = bibtexparser.loads(text, parser=parser).entries
    built = metadata_keys(text)
    for entry in entries:
        # A key seen before (the input itself, or a copy of it) would count one paper twice.
        if entry["ID"] in seen:
            continue
        seen.add(entry["ID"])
        year = entry.get("year", "").strip()
        venue = (entry.get("booktitle") or entry.get("journal") or "").strip()
        if not year or not venue:
            continue
        if entry["ID"] in built:
            skipped["metadata"] += in_input
            continue
        kind = venue_kind(entry.get("ENTRYTYPE", ""), entry)
        if library.lookup(venue, year, kind, issn=entry.get("issn")).interim_source or (
            kind == PROCEEDINGS and interim_source_of(venue, url=entry.get("url", ""), year=year, library=library)
        ):
            skipped["interim"] += in_input
            continue
        fields = {k.lower() for k, v in entry.items() if k not in ("ID", "ENTRYTYPE") and str(v).strip()}
        out.append(_Entry(entry, fields, in_input))
    return len(entries)


def _missing_rows(item: _Entry, library: VenueLibrary, ignored: Set[str]) -> Tuple[Optional[List[Row]], str]:
    """``(rows, venue label)``; rows is None when the entry's venue has no schema."""
    entry = item.entry
    schema, origin, record = expected_fields(entry, library)
    venue = record.name if record is not None else (entry.get("booktitle") or entry.get("journal") or "").strip()
    label = venue if venue_kind(entry.get("ENTRYTYPE", ""), entry) != PROCEEDINGS else family_label(venue)
    if not schema:
        return None, label
    skip = set(ignored)
    if awaiting_issue(entry):
        skip |= set(ISSUE_FIELDS)
    if record is not None and has_no_month(library.fields_of(record)):
        skip |= {"month", "day"}
    year = entry.get("year", "").strip()
    rows = [
        (entry["ID"], venue, year, name, MISSING, f"in the schema of {origin}")
        for name in schema if name not in item.fields and name not in skip
    ]
    return rows, label


def _default_rows(item: _Entry, library: VenueLibrary, ignored: Set[str],
                  defaults: Dict[Tuple[str, str], PublisherDefault]) -> List[Row]:
    """``default_missing`` rows: the fields of the publisher default that an entry without a schema lacks."""
    entry = item.entry
    venue = (entry.get("booktitle") or entry.get("journal") or "").strip()
    year = entry.get("year", "").strip()
    record = library.lookup(venue, year, venue_kind(entry.get("ENTRYTYPE", ""), entry),
                            issn=entry.get("issn")).venue
    default = default_for(entry, library, record, defaults)
    if default is None:
        return []
    skip = set(ignored) | (set(ISSUE_FIELDS) if awaiting_issue(entry) else set())
    if record is not None:
        skip |= set(library.entry_fields_of(record, entry))
        if has_no_month(library.fields_of(record)):
            skip |= {"month", "day"}
    name = record.name if record is not None else venue
    return [
        (entry["ID"], name, year, field_name, DEFAULT_MISSING, default.evidence())
        for field_name in default.fields if field_name not in item.fields and field_name not in skip
    ]


def _schema_rows(proposals: Sequence[Proposal], seen: Dict[str, Observation], inputs: Set[str]) -> List[SchemaRow]:
    rows: List[SchemaRow] = []
    for p in proposals:
        lacking = []
        for key in p.entries:
            if key not in inputs or key not in seen:
                continue
            gap = sorted(set(p.fields) - seen[key].fields)
            if gap:
                lacking.append(f"{key} ({', '.join(gap)})")
        detail = p.detail() + (f"; lacking: {'; '.join(lacking)}" if lacking else "")
        rows.append((p.venue, p.year, p.level, p.status, str(len(p.entries)), ", ".join(p.fields), detail))
    return rows


def check_edition_fields(
    input_path: str,
    library: VenueLibrary,
    against: Sequence[str | Path] = (),
    ignore_fields: Iterable[str] = (),
    include_fields: Iterable[str] = (),
    learn: Optional[VenueLibrary] = None,
    log: Optional[Callable[[str], None]] = None,
) -> EditionCheck:
    """Check the entries of *input_path* against their venues' schemas, and propose missing schemas.

    Args:
        input_path: Path to the BibTeX file whose entries are reported.
        library: Venue library that holds the schemas (a merged view is fine).
        against: Other ``.bib`` files or directories whose entries join the
            comparison that proposes schemas (their own gaps aren't reported).
        ignore_fields: Fields to ignore in addition to :data:`DEFAULT_IGNORED_FIELDS`.
        include_fields: Fields of :data:`DEFAULT_IGNORED_FIELDS` to compare anyway.
        learn: The library file to write the proposed schemas into; the
            caller saves it.  The check then uses them too.
        log: Optional logging callback; falls back to ``print``.
    """
    log = log or print
    ignored = (set(DEFAULT_IGNORED_FIELDS) - {f.lower() for f in include_fields}) | {
        f.lower() for f in ignore_fields
    }
    result = EditionCheck()
    log(f"🧬 Checking the entries of {input_path} against the schemas of their venues...")
    log(f"   Ignored fields: {', '.join(sorted(ignored))}\n")

    items: List[_Entry] = []
    skipped = {"interim": 0, "metadata": 0}
    seen_keys: Set[str] = set()
    _entries(Path(input_path), True, library, items, skipped, seen_keys)
    files = _bib_files(against, Path(input_path), log)
    others = 0
    for file in files:
        try:
            others += _entries(file, False, library, items, skipped, seen_keys)
        except Exception as e:  # noqa: BLE001 - a broken file should not stop the run
            log(f"⚠️  Could not read {file}: {e}")
    if files:
        log(f"   Compared with {others} entries in {len(files)} other files.")
    if skipped["interim"] or skipped["metadata"]:
        log(f"   Left out {skipped['interim']} entries with an interim booktitle and "
            f"{skipped['metadata']} entries built from metadata.")

    # Peers propose a schema only where none applies: they can't tell a
    # lost field from a change of the venue's export, official BibTeX can.
    observations: Dict[str, Observation] = {}
    for item in items:
        if expected_fields(item.entry, library)[0]:
            continue
        seen = observe(item.entry, library, item.fields, ignored)
        if seen is not None:
            observations[seen.key] = seen
    result.proposals = [
        p for p in propose(observations.values(), library, PEERS, min_entries=MIN_PEERS)
        if not p.current
    ]
    inputs = {i.entry["ID"] for i in items if i.in_input}
    result.schemas = _schema_rows(result.proposals, observations, inputs)
    if learn is not None and result.proposals:
        log(f"🧠 Writing the proposed schemas into {learn.path}...")
        result.learned = apply_proposals(learn, result.proposals, log)
        # The check uses them in this run too.
        apply_proposals(library, result.proposals, lambda _: None)

    unschematized: Dict[str, List[str]] = defaultdict(list)
    defaults = publisher_defaults(library)
    for item in items:
        if not item.in_input:
            continue
        rows, label = _missing_rows(item, library, ignored)
        if rows is None:
            if str(item.entry.get("ENTRYTYPE", "")).lower() in VENUE_TYPES:
                unschematized[label].append(item.entry["ID"])
                guessed = _default_rows(item, library, ignored, defaults)
                result.fields.extend(guessed)
                result.guessed += bool(guessed)
            continue
        result.checked += 1
        result.fields.extend(rows)
    result.unschematized = dict(sorted(unschematized.items()))
    _log_result(result, learn is not None, log)
    return result


def _log_result(result: EditionCheck, learning: bool, log: Callable[[str], None]) -> None:
    if result.fields:
        log(f"{'ID':<40} | {'Year':<4} | {'Field':<10} | Schema")
        log(SEPARATOR_LIGHT * SEPARATOR_WIDTH)
        venue = None
        for entry_id, name, year, field_name, _, evidence in sorted(result.fields, key=lambda r: (r[1], r[2], r[0])):
            if name != venue:
                venue = name
                log(f"📚 {name}")
            log(f"{entry_id:<40} | {year:<4} | {field_name:<10} | {evidence}")
        log(SEPARATOR_LIGHT * SEPARATOR_WIDTH)
    if result.schemas:
        log("\n📐 Proposed schemas, from the entries of each venue:")
        for venue, year, level, _, entries, fields, _ in result.schemas:
            when = f" ({year})" if year else ""
            log(f"   {venue}{when} [{level}, {entries} entries]: {fields or '(none)'}")
        if not learning:
            log("   To write them into the venue library and check the entries against them, "
                "run with --learn. A schema from 'bibcc check official --learn' is more reliable.")
    if result.unschematized:
        count = sum(len(keys) for keys in result.unschematized.values())
        log(f"\nℹ️  {count} entries of {len(result.unschematized)} venues have no schema to check against: "
            + "; ".join(f"{venue} ({len(keys)})" for venue, keys in result.unschematized.items()))
        log("   To learn one, run 'bibcc check official FILE --learn', or compare more entries of "
            "the venue with --against.")
    if result.guessed:
        log(f"\n💡 {result.guessed} entries without a schema lack fields of their publisher's default schema "
            f"({DEFAULT_MISSING}), which most of the library's schemas of the same publisher share. A default "
            "is a guess: it never replaces a venue's own schema, and --learn never writes it.")
    missing = [r for r in result.fields if r[4] == MISSING]
    if result.missing:
        log(f"⚠️  Found {len(missing)} missing fields in {len({r[0] for r in missing})} entries.")
    elif result.checked:
        log(f"✅ The {result.checked} entries with a schema have every field of it.")
