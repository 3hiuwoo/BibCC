"""
Fill-in YAML for venues missing from the venue library.

``bibcc complete``, ``bibcc add``, and ``bibcc upgrade`` all write
``.bibcc/<file>/missing_venues.yaml`` in the library's schema, so
``bibcc complete <file> --update-venues`` can merge it once it is filled in.

Each field is pre-filled from, highest priority first:

1. the entries themselves: the bib file, or the official BibTeX that
   ``add`` and ``upgrade`` downloaded (``# from bib`` / ``# from official BibTeX``);
2. the previous edition of the same conference in the library
   (``# from <year> edition``), except the month, which can change from one
   edition to the next;
3. CrossRef, when the command looked the paper up there (``# from CrossRef``),
   which gives the month only when the event starts and ends in it;
4. a guess of the publisher from the venue name (``# auto-guessed``).

A ``month`` of ``none`` (:data:`bibcc.venues.NO_MONTH`) says that the venue's
entries have no month: a conference held across two months, or a journal
without monthly issues.

A record's ``# entries:`` comment names the entries that cite the venue.

A record may also carry ``interim`` booktitles (see :mod:`bibcc.venues`):
the CVF or OpenReview name of the same proceedings, with the paper that
links the two names as evidence.  Merging such a record renames a library
record stored under the interim name.

The file is merged, never overwritten: records already in it keep their
text (and whatever you filled in), new records are appended, and records the
library now covers are dropped.  Suggested corrections to existing library
records (``bibcc complete --online``) go in a commented-out section at the
end; uncomment a record there to apply it.
"""

from __future__ import annotations

import copy
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import yaml

from bibcc.venues import (
    EDITION_STABLE_FIELDS,
    JOURNAL,
    NO_MONTH,
    PROCEEDINGS,
    Venue,
    VenueLibrary,
    _venue_from_dict,
    find_project_library,
    normalize_venue,
    previous_edition,
)

JOURNAL_FIELDS = ["publisher", "issn", "address"]
PROCEEDINGS_FIELDS = ["venue", "publisher", "month", "isbn", "issn", "editor", "series", "address"]
_OPTIONAL_FIELDS = {"address", "isbn", "issn", "editor", "series"}
_JOURNAL_OPTIONAL = {"address", "month"}
MONTH_HINT = f"# the event month, such as June, if the whole event falls in it; {NO_MONTH} if it runs across two months"
JOURNAL_MONTH_HINT = f"# optional; {NO_MONTH} for a journal without monthly issues"
_SUGGESTIONS_MARKER = "# ---- Suggested corrections to library records"

_PUBLISHER_PATTERNS: List[Tuple[str, str]] = [
    ("ieee", "IEEE"),
    ("acm", "Association for Computing Machinery"),
    ("springer", "Springer"),
    ("lecture notes", "Springer"),
    ("elsevier", "Elsevier"),
    ("aaai", "AAAI Press"),
    ("pmlr", "PMLR"),
    ("jmlr", "JMLR"),
    ("nature", "Springer Nature"),
    ("wiley", "Wiley"),
    ("mdpi", "MDPI"),
    ("oxford", "Oxford University Press"),
    ("cambridge", "Cambridge University Press"),
]


def guess_publisher(venue: str) -> str:
    """Publisher implied by the venue name, or ``""``."""
    lower = venue.lower()
    for pattern, publisher in _PUBLISHER_PATTERNS:
        if pattern in lower:
            return publisher
    return ""


def yaml_str(value: str) -> str:
    """Quote a string as a YAML double-quoted scalar (JSON escaping is valid YAML)."""
    return json.dumps(value, ensure_ascii=False)


@dataclass
class MissingVenue:
    """A venue record to propose, with the values known for it so far."""

    kind: str
    name: str
    year: str = ""
    # Values seen in the entries (or their official BibTeX).
    collected: Dict[str, str] = field(default_factory=dict)
    collected_label: str = "from bib"
    # The entries each collected value comes from, for the YAML comment.
    collected_from: Dict[str, List[str]] = field(default_factory=dict)
    # The entries that cite this venue, for the record's '# entries:' comment.
    entries: List[str] = field(default_factory=list)
    crossref: Dict[str, str] = field(default_factory=dict)
    interim: Dict[str, List[str]] = field(default_factory=dict)
    # Comment lines explaining where the record comes from (e.g. the paper linking two names).
    notes: List[str] = field(default_factory=list)
    # Only adds interim booktitles to an existing library record; its fields stay as they are.
    link_only: bool = False

    @property
    def key(self) -> Tuple[str, str, str]:
        return (self.kind, normalize_venue(self.name), self.year if self.kind == PROCEEDINGS else "")


@dataclass
class Suggestion:
    """A CrossRef value for a library record's field that differs from the library."""

    venue: Venue
    name: str
    value: str
    evidence: str


def _field_line(name: str, mv: MissingVenue, prior: Optional[Venue], guessed: str, hint: str) -> str:
    value, comment = "", f"  {hint}" if hint else ""
    if mv.collected.get(name):
        keys = mv.collected_from.get(name) or []
        if len(keys) > 3:
            suffix = f" ({', '.join(keys[:3])}, and {len(keys) - 3} more)"
        elif keys:
            suffix = f" ({', '.join(keys)})"
        else:
            suffix = ""
        value, comment = mv.collected[name], f"  # {mv.collected_label}{suffix}"
    elif prior and name in EDITION_STABLE_FIELDS and prior.fields.get(name):
        value, comment = prior.fields[name], f"  # from {prior.year} edition"
    elif mv.crossref.get(name):
        value, comment = mv.crossref[name], "  # from CrossRef"
    elif guessed:
        value, comment = guessed, "  # auto-guessed"
    optional = name in (_JOURNAL_OPTIONAL if mv.kind == JOURNAL else _OPTIONAL_FIELDS)
    prefix = "# " if optional and not value else ""
    return f"      {prefix}{name}: {yaml_str(value)}{comment}"


def render(mv: MissingVenue, library: VenueLibrary) -> List[str]:
    """YAML lines of one record, indented for its section."""
    prior = previous_edition(library, mv.name, mv.year) if mv.kind == PROCEEDINGS else None
    lines = [f"  - name: {yaml_str(mv.name)}"]
    if mv.entries:
        lines.append(f"    # entries: {', '.join(mv.entries)}")
    for note in mv.notes:
        lines.append(f"    # {note}")
    if mv.kind == PROCEEDINGS:
        lines.append(f"    year: {yaml_str(mv.year)}")
    if not mv.link_only:
        lines.append("    # aliases: []  # other spellings of this venue")
    if mv.interim:
        lines.append("    interim:  # booktitles CVF Open Access or OpenReview use for these proceedings")
        for source, names in mv.interim.items():
            if len(names) == 1:
                lines.append(f"      {source}: {yaml_str(names[0])}")
            else:
                lines.append(f"      {source}:")
                lines.extend(f"        - {yaml_str(n)}" for n in names)
    if mv.link_only:
        lines.append("    fields: {}  # the library record keeps its fields; merging only adds the interim booktitle")
        lines.append("")
        return lines
    lines.append("    fields:")
    if mv.kind == JOURNAL:
        lines.append(_field_line("publisher", mv, prior, guess_publisher(mv.name),
                                 "# for example, IEEE, Elsevier, or Springer"))
        lines.append(_field_line("issn", mv, prior, "", ""))
        lines.append(_field_line("address", mv, prior, "", "# optional; for example, New York, NY, USA"))
        lines.append(_field_line("month", mv, prior, "", JOURNAL_MONTH_HINT))
    else:
        lines.append(_field_line("venue", mv, prior, "", "# for example, City, Country"))
        lines.append(_field_line("publisher", mv, prior, guess_publisher(mv.name), ""))
        lines.append(_field_line("month", mv, prior, "", MONTH_HINT))
        for name in ("isbn", "issn", "editor", "series", "address"):
            lines.append(_field_line(name, mv, prior, "", ""))
    lines.append("")
    return lines


def _render_suggestions(suggestions: List[Suggestion]) -> List[str]:
    by_venue: Dict[int, List[Suggestion]] = {}
    for s in suggestions:
        by_venue.setdefault(id(s.venue), []).append(s)
    lines = [
        _SUGGESTIONS_MARKER,
        "# CrossRef disagrees with these library values. To apply one, move the record",
        "# into its section earlier in this file (journals: or proceedings:) and remove the '# '.",
        "#",
    ]
    for group in by_venue.values():
        venue = group[0].venue
        lines.append(f"#  - name: {yaml_str(venue.name)}")
        if venue.kind == PROCEEDINGS:
            lines.append(f"#    year: {yaml_str(str(venue.year))}")
        lines.append("#    fields:")
        for s in group:
            lines.append(
                f"#      {s.name}: {yaml_str(s.value)}  # library has {yaml_str(venue.fields.get(s.name, ''))}; "
                f"{s.evidence}"
            )
        lines.append("#")
    return lines


def _split(text: str) -> Tuple[Dict[str, List[str]], List[str]]:
    """Existing record blocks by section, and the suggestions section's lines."""
    sections: Dict[str, List[str]] = {"journals": [], "proceedings": []}
    suggestions: List[str] = []
    current: Optional[str] = None
    block: List[str] = []

    def flush() -> None:
        if current and block:
            sections[current].append("\n".join(block).rstrip("\n"))

    for line in text.splitlines():
        if line.startswith(_SUGGESTIONS_MARKER):
            flush()
            current, block = None, []
            suggestions = [line]
            continue
        if suggestions:
            suggestions.append(line)
            continue
        m = re.match(r"^(journals|proceedings):\s*$", line)
        if m:
            flush()
            current, block = m.group(1), []
            continue
        if current is None:
            continue
        if line.startswith("  - name:"):
            flush()
            block = [line]
        elif block:
            block.append(line)
    flush()
    return sections, suggestions


def _block_venue(block: str, kind: str) -> Optional[Venue]:
    try:
        data = yaml.safe_load(block)
        return _venue_from_dict(data[0], kind, "missing venues")
    except Exception:  # noqa: BLE001 - a hand-edited block may not parse; keep it as is
        return None


def _covered(library: VenueLibrary, venue: Venue) -> bool:
    """True if merging *venue* into the library would change nothing."""
    existing = library.find_any(venue)
    if existing is None:
        return False
    probe = VenueLibrary()
    probe._add(copy.deepcopy(existing))
    return probe.upsert(venue) == "unchanged"


HEADER = """\
# Venues missing from the BibCC venue library.
# Fill in the fields, and then run:
#   {rerun}
#
# '# from bib'             value found in your entries; the keys in parentheses say which
# '# from official BibTeX' value from the official BibTeX that bibcc add or bibcc upgrade downloaded
# '# from YEAR edition'    value copied from the previous edition in the library
# '# from CrossRef'        value that CrossRef reports for a paper of this venue
# '# auto-guessed'         value inferred from the venue name; verify it
# A record's '# entries:' comment names the entries that cite the venue.
# Merging skips records with no field (and no interim booktitle) filled in.
# Every run merges into this file and keeps what you fill in.
"""


def update_command(bib_file: str | Path, write: str = "--in-place") -> str:
    """The ``bibcc complete`` command that merges the filled-in YAML of *bib_file*.

    Names ``--scope project`` when *bib_file* has a project library, which is
    where its coauthors' venue records belong.
    """
    scope = " --scope project" if find_project_library(bib_file) is not None else ""
    return f"bibcc complete {bib_file} {write} --update-venues{scope}"


def write_missing_venues(
    path: Path,
    venues: List[MissingVenue],
    library: VenueLibrary,
    rerun: str,
    suggestions: Optional[List[Suggestion]] = None,
) -> Dict[str, int]:
    """Merge *venues* into the fill-in file at *path* (created if needed).

    Returns ``{"new": n, "kept": n, "dropped": n}``: records appended, records
    already in the file, and records dropped because the library covers them.
    Nothing is written when there is nothing to propose and no file yet.
    """
    existing_text = path.read_text(encoding="utf-8") if path.exists() else ""
    sections, old_suggestions = _split(existing_text)
    counts = {"new": 0, "kept": 0, "dropped": 0}
    kept: Dict[str, List[str]] = {"journals": [], "proceedings": []}
    seen = set()
    for section, kind in (("journals", JOURNAL), ("proceedings", PROCEEDINGS)):
        for block in sections[section]:
            venue = _block_venue(block, kind)
            if venue is not None and (venue.fields or venue.interim) and _covered(library, venue):
                counts["dropped"] += 1
                continue
            if venue is not None and not venue.fields and not venue.interim and library.find_any(venue):
                counts["dropped"] += 1
                continue
            if venue is not None:
                seen.add((kind, normalize_venue(venue.name), venue.year or ""))
            kept[section].append(block)
            counts["kept"] += 1
    for mv in venues:
        if mv.key in seen:
            continue
        seen.add(mv.key)
        section = "journals" if mv.kind == JOURNAL else "proceedings"
        kept[section].append("\n".join(render(mv, library)).rstrip("\n"))
        counts["new"] += 1

    suggestion_lines = _render_suggestions(suggestions) if suggestions else old_suggestions
    if not (kept["journals"] or kept["proceedings"] or suggestion_lines) and not path.exists():
        return counts
    out = [HEADER.format(rerun=rerun)]
    for section in ("journals", "proceedings"):
        if kept[section]:
            out.append(f"{section}:")
            out.extend(block + "\n" for block in kept[section])
    if suggestion_lines:
        out.append("\n".join(suggestion_lines).rstrip("\n") + "\n")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(out), encoding="utf-8")
    return counts
