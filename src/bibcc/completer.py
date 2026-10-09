"""
BibTeX Completer — fill missing metadata fields from the venue library.

Each journal article or conference paper is matched against the venue
library (``bibcc/data/venues.yaml`` by default, see :mod:`bibcc.venues`).
Fields the entry lacks are added; fields that differ are reported as
conflicts and never overwritten.

Workflow for venues missing from the library:
1. ``bibcc complete refs.bib`` writes ``.bibcc/refs.bib.missing_venues.yaml``
   with fields pre-filled from the bib entries, the previous edition of the
   same conference, and venue-name guesses.
2. Fill in the remaining fields in that YAML file.
3. ``bibcc complete refs.bib --output out.bib --update-venues`` merges the
   YAML into the library and completes with the updated library.
"""

from __future__ import annotations

import argparse
import functools
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import bibtexparser

from bibcc.bibedit import BibEditError, month_macro, read_bib, set_fields, unified_diff, write_bib
from bibcc.helptext import ENV_VENUES, VENUES_HELP, HelpFormatter, epilog
from bibcc.logging_utils import Logger, get_output_dir, write_report
from bibcc.venues import (
    EDITION_STABLE_FIELDS,
    JOURNAL,
    PROCEEDINGS,
    Venue,
    VenueLibrary,
    merge_missing_venues,
    normalize_venue,
    previous_edition,
    venue_kind,
)


def normalize_text(text: Optional[str]) -> str:
    """Normalize text for comparison by removing braces and lowercasing."""
    if not text:
        return ""
    return text.replace("{", "").replace("}", "").strip().lower()


# Publisher inference from venue name patterns
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

# Known conference month patterns
_CONFERENCE_MONTHS: Dict[str, str] = {
    "cvpr": "June",
    "iccv": "October",
    "eccv": "October",
    "neurips": "December",
    "nips": "December",
    "icml": "July",
    "iclr": "May",
    "aaai": "February",
    "ijcai": "August",
    "acl": "July",
    "emnlp": "November",
    "naacl": "June",
    "kdd": "August",
    "sigir": "July",
    "www": "May",
    "mm": "October",
    "interspeech": "September",
    "bmvc": "November",
    "wacv": "January",
    "miccai": "October",
    "coling": "October",
}


# Fields to collect from bib entries for pre-filling the missing-venues YAML
_JOURNAL_COLLECT_FIELDS = ["publisher", "issn", "address"]
_PROCEEDINGS_COLLECT_FIELDS = [
    "venue",
    "publisher",
    "month",
    "isbn",
    "issn",
    "editor",
    "series",
    "address",
]

def _guess_publisher(venue: str) -> str:
    """Infer publisher from venue name patterns. Returns empty string if unknown."""
    lower = venue.lower()
    for pattern, publisher in _PUBLISHER_PATTERNS:
        if pattern in lower:
            return publisher
    return ""


def _guess_month(venue: str) -> str:
    """Infer conference month from known conference name patterns."""
    lower = venue.lower()
    for pattern, month in _CONFERENCE_MONTHS.items():
        if re.search(rf"\b{re.escape(pattern)}\b", lower):
            return month
    return ""


def _yaml_str(value: str) -> str:
    """Quote a string as a YAML double-quoted scalar (JSON escaping is valid YAML)."""
    return json.dumps(value, ensure_ascii=False)


def _yaml_field(
    name: str,
    collected: Dict[str, str],
    prior: Optional[Venue],
    guessed: str = "",
    hint: str = "",
    optional: bool = False,
) -> str:
    """One ``name: value  # source`` line of a missing-venue record."""
    value, comment = "", f"  {hint}" if hint else ""
    if collected.get(name):
        value, comment = collected[name], "  # from bib"
    elif prior and name in EDITION_STABLE_FIELDS and prior.fields.get(name):
        value, comment = prior.fields[name], f"  # from {prior.year} edition"
    elif guessed:
        value, comment = guessed, "  # auto-guessed"
    prefix = "# " if optional and not value else ""
    return f"      {prefix}{name}: {_yaml_str(value)}{comment}"


def _write_yaml_missing_venues(
    path: Path,
    missing: Dict[Tuple[str, str], Tuple[str, str, str]],
    library: VenueLibrary,
    bib_collected: Optional[Dict[Tuple[str, str], Dict[str, str]]] = None,
) -> None:
    """Write venues missing from the library to a YAML file for the user to fill in.

    The file uses the library schema, so ``--update-venues`` can merge it
    directly. Fields are pre-filled from (highest priority first):
      1. Values found in the bib entries (``# from bib``)
      2. The previous edition of the same conference (``# from <year>``)
      3. Guesses from the venue name (``# auto-guessed``)
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    bib_collected = bib_collected or {}

    sections: Dict[str, List[str]] = {JOURNAL: [], PROCEEDINGS: []}

    for key, (venue_raw, year, entry_type) in missing.items():
        collected = bib_collected.get(key, {})
        prior = previous_edition(library, venue_raw, year) if entry_type == PROCEEDINGS else None
        lines = sections[entry_type]
        lines.append(f"  - name: {_yaml_str(venue_raw)}")
        if entry_type == PROCEEDINGS:
            lines.append(f"    year: {_yaml_str(year)}")
        lines.append("    # aliases: []  # other spellings of this venue")
        lines.append("    fields:")

        field_line = functools.partial(_yaml_field, collected=collected, prior=prior)
        guessed_publisher = _guess_publisher(venue_raw)
        if entry_type == JOURNAL:
            lines.append(field_line("publisher", guessed=guessed_publisher, hint="# e.g., IEEE, Elsevier, Springer"))
            lines.append(field_line("issn"))
            lines.append(field_line("address", hint="# optional, e.g., New York, NY, USA", optional=True))
        else:
            lines.append(field_line("venue", hint="# e.g., City, Country"))
            lines.append(field_line("publisher", guessed=guessed_publisher))
            lines.append(field_line("month", guessed=_guess_month(venue_raw), hint="# e.g., June, October"))
            for name in ("isbn", "issn", "editor", "series", "address"):
                lines.append(field_line(name, optional=True))
        lines.append("")

    out = [
        "# Venues missing from the BibCC venue library.",
        "# Fill in the fields, then run:",
        "#   bibcc complete <input.bib> --output <out.bib> --update-venues",
        "#",
        "# '# from bib'          value found in your entries",
        "# '# from <year> edition' value copied from the previous edition in the library",
        "# '# auto-guessed'      inferred from the venue name; please verify",
        "# Records whose fields are all empty are skipped when merging.",
        "",
    ]
    for kind, key in ((JOURNAL, "journals"), (PROCEEDINGS, "proceedings")):
        if sections[kind]:
            out.append(f"{key}:")
            out.extend(sections[kind])

    path.write_text("\n".join(out), encoding="utf-8")


def compute_completion(
    entries: List[Dict[str, Any]],
    library: VenueLibrary,
) -> Dict[str, Any]:
    """Match entries against the library and compute what to add.

    Returns a dict with:
      - ``patches``:    ``{entry_id: {field: value}}`` fields to add
      - ``conflicts``:  ``{entry_id: [(field, existing, library_value)]}``
      - ``ambiguous``:  ``[(entry_id, venue, [labels])]`` several records matched
      - ``missing``:    ``{(norm_venue, year): (venue, year, type)}`` not in library
      - ``collected``:  ``{key: {field: most common value}}`` for pre-filling
      - ``incomplete``: ``[(entry_id, venue, year)]`` entries lacking venue/year
    """
    patches: Dict[str, Dict[str, str]] = {}
    conflicts: Dict[str, List[Tuple[str, str, str]]] = {}
    ambiguous: List[Tuple[str, str, List[str]]] = []
    missing: Dict[Tuple[str, str], Tuple[str, str, str]] = {}
    counters: Dict[Tuple[str, str], Dict[str, Counter]] = {}
    incomplete: List[Tuple[str, str, str]] = []

    for entry in entries:
        entry_id = entry["ID"]
        year = entry.get("year", "")
        venue_raw = entry.get("booktitle") or entry.get("journal") or ""
        entry_type = venue_kind(entry.get("ENTRYTYPE", ""), entry)

        if not year or not venue_raw:
            incomplete.append((entry_id, venue_raw, year))
            continue

        result = library.lookup(venue_raw, year, entry_type, issn=entry.get("issn"))
        if result.ambiguous:
            ambiguous.append((entry_id, venue_raw, [v.label for v in result.ambiguous]))
            continue

        if result.venue is None:
            key = (normalize_venue(venue_raw), "" if entry_type == JOURNAL else normalize_text(year))
            missing.setdefault(key, (venue_raw, year, entry_type))
            collect_fields = (
                _JOURNAL_COLLECT_FIELDS if entry_type == JOURNAL else _PROCEEDINGS_COLLECT_FIELDS
            )
            entry_counters = counters.setdefault(key, {})
            for fname in collect_fields:
                val = entry.get(fname, "").strip()
                if val:
                    entry_counters.setdefault(fname, Counter())[val] += 1
            continue

        fields_to_add = {}
        entry_conflicts = []
        for k, v in result.venue.fields.items():
            if k not in entry:
                fields_to_add[k] = v
            elif k == "month" and month_macro(v) and month_macro(entry.get(k)) == month_macro(v):
                continue
            elif normalize_text(entry.get(k, "")) != normalize_text(v):
                entry_conflicts.append((k, entry.get(k, ""), v))

        if fields_to_add:
            patches[entry_id] = fields_to_add
        if entry_conflicts:
            conflicts[entry_id] = entry_conflicts

    collected = {
        key: {fname: counter.most_common(1)[0][0] for fname, counter in field_counters.items()}
        for key, field_counters in counters.items()
    }
    return {
        "patches": patches,
        "conflicts": conflicts,
        "ambiguous": ambiguous,
        "missing": missing,
        "collected": collected,
        "incomplete": incomplete,
    }


def main(
    input_path: str,
    output_path: str,
    dry_run: bool = False,
    log_dir: Path | None = None,
    library: Optional[VenueLibrary] = None,
    log: Optional[Callable[[str], None]] = None,
):
    """Complete *input_path* and write the result to *output_path* unless *dry_run*.

    Only the added fields change in the output; everything else in the file
    is kept byte for byte.  Raises :class:`BibEditError` (and writes nothing)
    if the edits cannot be applied safely.
    """
    log = log or print
    library = library if library is not None else VenueLibrary.load()
    log(f"Reading {input_path}...")
    log(
        f"📦 Venue library: {library.path} "
        f"({len(library.journals)} journals, {len(library.proceedings)} proceedings)"
    )

    with open(input_path, "r", encoding="utf-8") as f:
        parser = bibtexparser.bparser.BibTexParser(common_strings=True)
        bib_db = bibtexparser.load(f, parser=parser)

    result = compute_completion(bib_db.entries, library)
    patches = result["patches"]
    conflicts = result["conflicts"]
    ambiguous = result["ambiguous"]
    missing = result["missing"]
    incomplete_entries = result["incomplete"]

    log(f"  Identified {len(patches)} entries to patch.")

    text = read_bib(input_path)
    new_text, applied = set_fields(text, patches, replace=False)

    output_dir = get_output_dir(input_path, log_dir)
    base = Path(input_path).name
    conflict_log = output_dir / f"{base}.conflicts.txt"
    missing_txt_log = output_dir / f"{base}.missing_venues.txt"
    missing_yaml_log = output_dir / f"{base}.missing_venues.yaml"
    incomplete_log = output_dir / f"{base}.incomplete_entries.txt"
    diff_log = output_dir / f"{base}.complete.diff"

    conflict_rows: List[str] = []
    for eid, rows in conflicts.items():
        for k, existing_val, tmpl_val in rows:
            conflict_rows.append(f"{eid}\t{k}\tEXISTING={existing_val}\tLIBRARY={tmpl_val}")
    for eid, venue_raw, labels in ambiguous:
        conflict_rows.append(f"{eid}\t(venue)\tVENUE={venue_raw}\tAMBIGUOUS={' | '.join(labels)}")

    missing_rows = [f"{v}\t{y}\t{t}" for v, y, t in missing.values()]
    incomplete_rows = [
        f"{eid}\tvenue={venue or '(empty)'}\tyear={year or '(empty)'}"
        for eid, venue, year in incomplete_entries
    ]

    if dry_run:
        diff = unified_diff(text, new_text, input_path)
        if diff:
            log(f"\n🧪 Dry-run preview ({len(applied)} fields to add):")
            log(diff.rstrip("\n"))
            diff_log.write_text(diff, encoding="utf-8")
        else:
            log("\n🧪 Dry-run: no additions needed.")

        if conflicts:
            log("\n⚠️  Conflicts (existing value differs from library, not overwritten):")
            for eid, conflicts_fields in conflicts.items():
                log(f"Entry ID: {eid}")
                for k, existing_val, tmpl_val in conflicts_fields:
                    log(f"  field '{k}': existing='{existing_val}', library='{tmpl_val}'")
        else:
            log("\n✅ No conflicts detected.")

        if ambiguous:
            log("\n⚠️  Ambiguous venues (several library records match, nothing added):")
            for eid, venue_raw, labels in ambiguous:
                log(f"  🔸 {eid}: '{venue_raw}' matches {', '.join(labels)}")

        if incomplete_entries:
            log("\n📭 Incomplete entries (missing year or venue, e.g., arxiv/misc) - skipped:")
            for entry_id, venue, year in incomplete_entries:
                log(f"  🔸 {entry_id}: venue='{venue or '(empty)'}' year='{year or '(empty)'}'")

        if missing:
            log("\nℹ️  Venues not in the library (deduplicated):")
            for venue_raw, year, entry_type in missing.values():
                type_icon = "📰" if entry_type == JOURNAL else "📋"
                log(f"  {type_icon} [{entry_type}] venue='{venue_raw}' year='{year}'")
        else:
            log("\n✅ All complete entries matched the venue library.")

        write_report(conflict_log, "conflicts: entry_id\tfield\texisting\tlibrary", conflict_rows)
        write_report(missing_txt_log, "missing venues: venue\tyear\ttype", missing_rows)
        write_report(
            incomplete_log,
            "incomplete entries (missing year or venue): entry_id\tvenue\tyear",
            incomplete_rows,
        )

        if missing:
            _write_yaml_missing_venues(missing_yaml_log, missing, library, result["collected"])
            log(f"\n📝 Missing venues YAML created: {missing_yaml_log}")
            log(
                f"   Fill in the fields and run: bibcc complete {input_path} "
                "--output <out.bib> --update-venues"
            )

        saved = [conflict_log, missing_txt_log, incomplete_log] + ([diff_log] if diff else [])
        log(f"\nReports saved: {', '.join(str(p) for p in saved)}")
        log("💡 To write changes, run with --output <file.bib> or --in-place")
        return

    write_bib(output_path, new_text)
    entries_changed = len({a.key for a in applied})
    log(f"✅ Added {len(applied)} fields to {entries_changed} entries. Saved to {output_path}")
    if conflicts or ambiguous:
        log(f"⚠️  {len(conflicts)} conflicting and {len(ambiguous)} ambiguous entries left unchanged.")


def build_parser() -> argparse.ArgumentParser:
    """Build argument parser for BibTeX completer."""
    parser = argparse.ArgumentParser(
        description="""\
Fill missing venue fields (publisher, ISSN, venue location, month, ISBN,
series, ...) in a .bib file from the venue library. Journals are matched by
name, alias, or ISSN; proceedings by name or alias and the entry's year.

Existing fields are never overwritten; a different value is reported as a
conflict. Only the new fields are inserted, and the rest of the file stays
byte for byte. Without --output or --in-place this is a dry run that writes
the would-be changes as a diff.

Venues that are not in the library are written to a fill-in YAML file,
pre-filled from other entries of the same venue and from the previous
edition of a conference. Fill in the rest, then rerun with --update-venues
to add them to the library and complete the file in one step.""",
        epilog=epilog(
            examples=[
                ("preview the changes (writes .bibcc/refs.bib.complete.diff)", "bibcc complete refs.bib"),
                ("write the completed file elsewhere", "bibcc complete refs.bib --output out.bib"),
                ("complete the file itself", "bibcc complete refs.bib --in-place"),
                ("after filling in .bibcc/refs.bib.missing_venues.yaml: add those venues, then complete",
                 "bibcc complete refs.bib --in-place --update-venues"),
            ],
            outputs=[
                (".bibcc/<input>.complete.diff", "dry run: the changes that would be made"),
                (".bibcc/<input>.missing_venues.yaml", "fill-in records for venues not in the library"),
                (".bibcc/<input>.missing_venues.txt", "entries whose venue is not in the library"),
                (".bibcc/<input>.conflicts.txt", "fields whose value differs from the library"),
                (".bibcc/<input>.incomplete_entries.txt", "entries without a year or venue (skipped)"),
                (".bibcc/logs/<input>.completer.log", "everything printed to the terminal"),
            ],
            exit_status="0 on success, 1 if the edits could not be verified (nothing is written), 2 on usage errors.",
            env=[ENV_VENUES],
        ),
        formatter_class=HelpFormatter,
    )
    parser.add_argument("input", type=str, help="The .bib file to complete.")
    parser.add_argument(
        "--output",
        type=str,
        default="",
        metavar="FILE",
        help="Write the completed file here (omit both --output and --in-place for a dry run).",
    )
    parser.add_argument(
        "--in-place",
        action="store_true",
        help="Write the completed entries back to the input file.",
    )
    parser.add_argument(
        "--log-dir",
        type=str,
        default="",
        metavar="DIR",
        help="Directory for reports and logs (default: .bibcc/ next to the input file).",
    )
    parser.add_argument(
        "--venues",
        type=str,
        default="",
        metavar="FILE",
        help=VENUES_HELP,
    )
    parser.add_argument(
        "--update-venues",
        "--update-templates",
        dest="update_venues",
        action="store_true",
        help="First merge the filled-in .bibcc/<input>.missing_venues.yaml into the venue "
        "library (records with no field filled in are skipped), then complete.",
    )
    return parser


def run(args: argparse.Namespace) -> None:
    """Run completer with parsed arguments."""
    if args.in_place and args.output:
        build_parser().error("use either --output or --in-place, not both")
    output = args.input if args.in_place else args.output
    dry_run = not bool(output)
    log_dir = Path(args.log_dir) if args.log_dir else None

    with Logger("completer", input_file=args.input, log_dir=log_dir) as logger:
        library = VenueLibrary.load(args.venues or None)

        if args.update_venues:
            base = Path(args.input).name
            yaml_path = get_output_dir(args.input, log_dir) / f"{base}.missing_venues.yaml"
            if not yaml_path.exists():
                logger.log(f"ℹ️  No {yaml_path.name} found — run without --output first.")
            else:
                logger.log(f"🔄 Merging {yaml_path} into {library.path}...")
                counts = merge_missing_venues(library, yaml_path, log=logger.log)
                if counts["added"] or counts["updated"]:
                    library.save()
                    logger.log(
                        f"✅ Venue library updated: +{counts['added']} new, "
                        f"~{counts['updated']} updated, {counts['skipped']} skipped.\n"
                    )
                else:
                    logger.log("ℹ️  Nothing new to merge.\n")

        try:
            main(
                args.input,
                output or args.input,
                dry_run=dry_run,
                log_dir=log_dir,
                library=library,
                log=logger.log,
            )
        except BibEditError as e:
            logger.log(f"❌ Could not apply the edits safely: {e}")
            logger.log("   Nothing was written.")
            sys.exit(1)


if __name__ == "__main__":
    parser = build_parser()
    args = parser.parse_args()
    run(args)
