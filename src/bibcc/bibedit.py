"""
Safe, minimal edits to raw BibTeX text.

bibtexparser is used to *read* entries, but writing its output back would
reformat the whole file.  This module instead locates each entry and field in
the original text with a brace-aware scanner and patches only the targeted
byte ranges, so comments, field order, alignment, and LaTeX stay untouched.

Every edited text is re-parsed with bibtexparser and checked before it is
returned: the same citation keys in the same order, untouched fields
unchanged, and every edited field holding its new value.  If any check fails,
:class:`BibEditError` is raised and nothing should be written.

Usage:
    from bibcc.bibedit import read_bib, set_fields, write_bib

    text = read_bib("refs.bib")
    new_text, applied = set_fields(text, {"Key_Doe_CVPR2025": {"month": "June"}})
    write_bib("refs.bib", new_text)
"""

from __future__ import annotations

import difflib
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import bibtexparser

_SKIPPED_TYPES = {"comment", "string", "preamble"}
_ENTRY_START = re.compile(r"@\s*([A-Za-z][\w-]*)\s*([{(])")
_FIELD_NAME = re.compile(r"[^\s=,{}()\"#%]+")
_BARE_VALUE = re.compile(r"[^\s,#{}()\"%]+")
_MONTH_NAMES = [
    "january", "february", "march", "april", "may", "june",
    "july", "august", "september", "october", "november", "december",
]


class BibEditError(Exception):
    """Raised when text cannot be scanned or an edit fails verification."""


@dataclass
class FieldSpan:
    """Location of one ``name = value`` pair in the raw text."""

    name: str
    start: int
    value_start: int
    value_end: int


@dataclass
class EntrySpan:
    """Location of one entry (``@type{key, ...}``) in the raw text."""

    entry_type: str
    key: str
    start: int
    key_end: int
    closer: int
    end: int
    fields: Dict[str, FieldSpan] = field(default_factory=dict)


@dataclass
class AppliedEdit:
    """One field change that was applied."""

    key: str
    field: str
    action: str  # "added" or "replaced"
    old: Optional[str]
    new: str


def month_macro(value: Optional[str]) -> Optional[str]:
    """``jun`` for ``6``, ``June``, ``Jun.``, or ``{jun}``; None if not a month."""
    text = (value or "").strip().strip("{}").strip().rstrip(".").lower()
    if text.isdigit():
        return _MONTH_NAMES[int(text) - 1][:3] if 1 <= int(text) <= 12 else None
    for name in _MONTH_NAMES:
        if len(text) >= 3 and name.startswith(text):
            return name[:3]
    return None


_RANGE_PART = re.compile(r"^(\s*)([A-Za-z]*\d+[A-Za-z]*)\s*[-‐‑–—−]\s*([A-Za-z]*\d+[A-Za-z]*)(\s*)$")


def page_range(value: str) -> str:
    """``12--15`` for ``12-15``, ``12 – 15``, or ``S1-S9``; other values unchanged.

    Comma-separated lists of ranges are handled part by part.
    """
    parts = value.split(",")
    fixed = [_RANGE_PART.sub(r"\1\2--\3\4", part) for part in parts]
    return ",".join(fixed)


def _render(name: str, value: str) -> str:
    """Raw value text for *value*: months as bare macros, everything else braced."""
    if name.lower() == "month":
        macro = month_macro(value)
        if macro:
            return macro
    return f"{{{value}}}"


def _line_of(text: str, pos: int) -> int:
    return text.count("\n", 0, pos) + 1


def _skip_ws(text: str, i: int) -> int:
    n = len(text)
    while i < n and text[i].isspace():
        i += 1
    return i


def _match_braces(text: str, i: int) -> int:
    """Return the index just past the brace group opening at ``text[i]``."""
    depth = 0
    for j in range(i, len(text)):
        ch = text[j]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return j + 1
    raise BibEditError(f"unbalanced braces starting at line {_line_of(text, i)}")


def _match_quote(text: str, i: int) -> int:
    """Return the index just past the quoted string opening at ``text[i]``."""
    depth = 0
    for j in range(i + 1, len(text)):
        ch = text[j]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
        elif ch == '"' and depth == 0:
            return j + 1
    raise BibEditError(f"unterminated quoted value at line {_line_of(text, i)}")


def _scan_value(text: str, i: int) -> int:
    """Return the end of a field value (tokens joined by ``#``) starting at *i*."""
    while True:
        if i >= len(text):
            raise BibEditError("unexpected end of file inside a field value")
        ch = text[i]
        if ch == "{":
            i = _match_braces(text, i)
        elif ch == '"':
            i = _match_quote(text, i)
        else:
            m = _BARE_VALUE.match(text, i)
            if not m:
                raise BibEditError(f"expected a field value at line {_line_of(text, i)}")
            i = m.end()
        j = _skip_ws(text, i)
        if j < len(text) and text[j] == "#":
            i = _skip_ws(text, j + 1)
            continue
        return i


def value_tokens(raw: str) -> List[str]:
    """Top-level tokens of a raw field value; more than one means ``#`` concatenation."""
    tokens: List[str] = []
    i = 0
    while i < len(raw):
        if raw[i].isspace() or raw[i] == "#":
            i += 1
            continue
        if raw[i] == "{":
            end = _match_braces(raw, i)
        elif raw[i] == '"':
            end = _match_quote(raw, i)
        else:
            end = i
            while end < len(raw) and not raw[end].isspace() and raw[end] != "#":
                end += 1
        tokens.append(raw[i:end])
        i = end
    return tokens


def unwrap(token: str) -> str:
    """*token* without one pair of enclosing ``{...}`` or ``"..."``."""
    token = token.strip()
    if len(token) >= 2 and (token[0], token[-1]) in (("{", "}"), ('"', '"')):
        return token[1:-1]
    return token


def balanced(text: str) -> bool:
    """True if every ``{`` in *text* has a matching ``}``."""
    depth = 0
    for ch in text:
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth < 0:
                return False
    return depth == 0


def _in_comment_line(text: str, pos: int) -> bool:
    line_start = text.rfind("\n", 0, pos) + 1
    return text[line_start:pos].lstrip().startswith("%")


def scan(text: str) -> List[EntrySpan]:
    """Locate every entry in *text* (``@comment``/``@string``/``@preamble`` skipped)."""
    entries: List[EntrySpan] = []
    i = 0
    n = len(text)
    while True:
        at = text.find("@", i)
        if at < 0:
            return entries
        m = _ENTRY_START.match(text, at)
        if not m or _in_comment_line(text, at):
            i = at + 1
            continue
        entry_type, opener = m.group(1), m.group(2)
        open_pos = m.end() - 1
        if entry_type.lower() in _SKIPPED_TYPES:
            i = _match_braces(text, open_pos) if opener == "{" else text.find(")", open_pos) + 1
            if i <= 0:
                raise BibEditError(f"unterminated @{entry_type} at line {_line_of(text, at)}")
            continue

        closer_char = "}" if opener == "{" else ")"
        p = _skip_ws(text, open_pos + 1)
        key_start = p
        while p < n and text[p] not in ",}" + closer_char and not text[p].isspace():
            p += 1
        key = text[key_start:p]
        key_end = p
        if not key:
            raise BibEditError(f"entry without a citation key at line {_line_of(text, at)}")

        fields: Dict[str, FieldSpan] = {}
        while True:
            p = _skip_ws(text, p)
            if p >= n:
                raise BibEditError(f"entry '{key}' is not closed (line {_line_of(text, at)})")
            if text[p] == ",":
                p += 1
                continue
            if text[p] == closer_char:
                break
            name_m = _FIELD_NAME.match(text, p)
            if not name_m:
                raise BibEditError(
                    f"entry '{key}': expected a field name at line {_line_of(text, p)}"
                )
            name_start = p
            p = _skip_ws(text, name_m.end())
            if p >= n or text[p] != "=":
                raise BibEditError(
                    f"entry '{key}': expected '=' after '{name_m.group()}' "
                    f"at line {_line_of(text, p)}"
                )
            p = _skip_ws(text, p + 1)
            value_start = p
            p = _scan_value(text, p)
            canonical = name_m.group().lower()
            if canonical in fields:
                raise BibEditError(f"entry '{key}' has a duplicate '{canonical}' field")
            fields[canonical] = FieldSpan(name_m.group(), name_start, value_start, p)

        entries.append(EntrySpan(entry_type, key, at, key_end, p, p + 1, fields))
        i = p + 1


def _check_value(value: str) -> None:
    if not balanced(value):
        raise BibEditError(f"value has unbalanced braces: {value!r}")


def _layout(text: str, entry: EntrySpan) -> Tuple[str, Optional[int]]:
    """Return the entry's field indent and '=' alignment width (if aligned)."""
    indents: Counter = Counter()
    widths = set()
    natural = True
    for f in entry.fields.values():
        line_start = text.rfind("\n", 0, f.start) + 1
        prefix = text[line_start : f.start]
        if prefix.strip():
            continue
        indents[prefix] += 1
        width = text.index("=", f.start) - f.start
        widths.add(width)
        natural &= width == len(f.name) + 1
    indent = indents.most_common(1)[0][0] if indents else "  "
    # "name = value" everywhere means no column alignment to imitate.
    aligned = len(widths) == 1 and not natural
    return indent, widths.pop() if aligned else None


def _format_field(name: str, value: str, width: Optional[int]) -> str:
    if width and len(name) < width:
        return f"{name.ljust(width)}= {_render(name, value)}"
    return f"{name} = {_render(name, value)}"


def _parse_entries(text: str) -> List[Dict[str, str]]:
    parser = bibtexparser.bparser.BibTexParser(common_strings=True)
    return bibtexparser.loads(text, parser=parser).entries


def _norm(value: Optional[str]) -> str:
    return " ".join((value or "").split())


def _verify(old_text: str, new_text: str, changed: Dict[str, Dict[str, str]]) -> None:
    """Re-parse and compare; raise BibEditError on any unintended difference."""
    old_keys = [e.key for e in scan(old_text)]
    new_keys = [e.key for e in scan(new_text)]
    if old_keys != new_keys:
        raise BibEditError("edit changed the sequence of citation keys")

    old_entries = _parse_entries(old_text)
    new_entries = _parse_entries(new_text)
    if [e["ID"] for e in old_entries] != [e["ID"] for e in new_entries]:
        raise BibEditError("edited text no longer parses to the same entries")
    for old, new in zip(old_entries, new_entries):
        targets = changed.get(old["ID"], {})
        for name in set(old) | set(new):
            if name in targets:
                continue
            if old.get(name) != new.get(name):
                raise BibEditError(f"edit changed untouched field '{name}' of '{old['ID']}'")
        for name, value in targets.items():
            if name == "month" and month_macro(value):
                if month_macro(new.get(name)) == month_macro(value):
                    continue
            if _norm(new.get(name)) != _norm(value):
                raise BibEditError(f"field '{name}' of '{old['ID']}' did not receive its new value")


def set_fields(
    text: str,
    changes: Dict[str, Dict[str, str]],
    replace: bool = True,
) -> Tuple[str, List[AppliedEdit]]:
    """Set fields on entries, touching only the affected ranges of *text*.

    Args:
        text: Raw BibTeX text.
        changes: ``{citation_key: {field: value}}``. Values are written
            wrapped in braces, except recognisable months, which are
            written as bare macros (``month = jun``).
        replace: If False, fields that already exist are left alone.

    Returns:
        ``(new_text, applied_edits)``.

    Raises:
        BibEditError: if the text cannot be scanned, a key is missing or
            duplicated, a value is malformed, or verification fails.
    """
    entries = scan(text)
    key_counts = Counter(e.key for e in entries)
    by_key = {e.key: e for e in entries}
    for key in changes:
        if key not in by_key:
            raise BibEditError(f"no entry with key '{key}'")
        if key_counts[key] > 1:
            raise BibEditError(f"key '{key}' appears {key_counts[key]} times")

    newline = "\r\n" if "\r\n" in text else "\n"
    patches: List[Tuple[int, int, str]] = []
    applied: List[AppliedEdit] = []
    verified: Dict[str, Dict[str, str]] = {}

    for key, fields in changes.items():
        entry = by_key[key]
        inserts: List[Tuple[str, str]] = []
        for name, value in fields.items():
            value = str(value)
            _check_value(value)
            existing = entry.fields.get(name.lower())
            if existing is not None:
                if not replace:
                    continue
                old = text[existing.value_start : existing.value_end]
                new = _render(name, value)
                if old == new:
                    continue
                patches.append((existing.value_start, existing.value_end, new))
                applied.append(AppliedEdit(key, name.lower(), "replaced", old, new))
            else:
                inserts.append((name.lower(), value))
            verified.setdefault(key, {})[name.lower()] = value

        if inserts:
            indent, width = _layout(text, entry)
            anchor = max((f.value_end for f in entry.fields.values()), default=entry.key_end)
            between = text[anchor : entry.closer]
            if between.lstrip().startswith(","):
                pos = anchor + between.index(",") + 1
                chunk = "".join(
                    newline + indent + _format_field(n, v, width) + "," for n, v in inserts
                )
            else:
                pos = anchor
                chunk = "".join(
                    "," + newline + indent + _format_field(n, v, width) for n, v in inserts
                )
            patches.append((pos, pos, chunk))
            for n, v in inserts:
                applied.append(AppliedEdit(key, n, "added", None, _render(n, v)))

    new_text = _apply(text, patches)
    if new_text != text:
        _verify(text, new_text, verified)
    return new_text, applied


def replace_entry(text: str, key: str, new_entry: str) -> str:
    """Replace the whole entry *key* with *new_entry* (which must keep the key)."""
    entries = scan(text)
    matches = [e for e in entries if e.key == key]
    if len(matches) != 1:
        raise BibEditError(f"expected exactly one entry '{key}', found {len(matches)}")
    replacement = scan(new_entry)
    if len(replacement) != 1 or replacement[0].key != key:
        raise BibEditError(f"replacement for '{key}' must be one entry with the same key")
    entry = matches[0]
    new_text = text[: entry.start] + new_entry.strip() + text[entry.end :]
    if [e.key for e in scan(new_text)] != [e.key for e in entries]:
        raise BibEditError("replacement changed the sequence of citation keys")
    parsed = {e["ID"] for e in _parse_entries(new_text)}
    if key not in parsed:
        raise BibEditError(f"replacement entry '{key}' does not parse")
    return new_text


def _apply(text: str, patches: List[Tuple[int, int, str]]) -> str:
    ordered = sorted(patches, key=lambda p: (p[0], p[1]))
    for (_, e1, _), (s2, _, _) in zip(ordered, ordered[1:]):
        if s2 < e1:
            raise BibEditError("overlapping edits")
    out = text
    for start, end, replacement in reversed(ordered):
        out = out[:start] + replacement + out[end:]
    return out


def read_bib(path: str | Path) -> str:
    """Read a .bib file without newline translation (CRLF is preserved)."""
    with open(path, "r", encoding="utf-8", newline="") as f:
        return f.read()


def write_bib(path: str | Path, text: str) -> None:
    """Write a .bib file without newline translation."""
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(text)


def unified_diff(old: str, new: str, path: str | Path, new_path: str | Path | None = None) -> str:
    """Return a unified diff between *old* and *new* text."""
    return "".join(
        difflib.unified_diff(
            old.splitlines(keepends=True),
            new.splitlines(keepends=True),
            fromfile=f"a/{Path(path).name}",
            tofile=f"b/{Path(new_path or path).name}",
        )
    )
