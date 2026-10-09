"""
Reformat .bib files in a consistent, bibtex-tidy-like style.

The default style matches the survey bibliography::

    @inproceedings{GKEAL_Zhuang_CVPR2023,
      title     = {{GKEAL}: {Gaussian} Kernel ...},
      year      = {2023},
      month     = jun,
      booktitle = {2023 {IEEE/CVF} Conference ...}
    }

Entry types and field names are lowercased, ``=`` signs are aligned, values
are braced (``"..."`` and bare numbers), months become bare macros, page
ranges use ``--``, and entries are separated by one blank line.  Field values are otherwise copied
verbatim.  Text between entries (``%`` comments, ``@string``/``@comment``
blocks) is kept; only the blank lines around it are normalised.

Every result is re-parsed with bibtexparser and compared with the input:
the same entries, types, fields, and values (up to the conversions above).
If anything else differs, :class:`~bibcc.bibedit.BibEditError` is raised and
nothing is written.

By default nothing is written: the changes are saved as a diff under
``.bibcc/``.  Use ``--in-place`` or ``--output`` to write them, or
``--check`` to fail (exit 1) when a file is not formatted.

Usage:
    bibcc format refs.bib
    bibcc format bib/ --in-place
    bibcc format bib/ --check
"""

from __future__ import annotations

import argparse
import re
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence, Set, Tuple

import bibtexparser
from bibtexparser.bibdatabase import BibDataString, BibDataStringExpression

from bibcc.adder import FIELD_ORDER
from bibcc.bibedit import (
    BibEditError,
    EntrySpan,
    balanced,
    month_macro,
    page_range,
    read_bib,
    scan,
    unified_diff,
    unwrap,
    value_tokens,
    write_bib,
)
from bibcc.logging_utils import (
    OUTPUT_DIR_NAME,
    SEPARATOR_THIN,
    SEPARATOR_WIDTH,
    Logger,
    get_output_dir,
)

_BOM = "\ufeff"
_HOISTED_BLOCK = re.compile(r"^[ \t]*@\s*(string|preamble)\s*[{(]", re.IGNORECASE | re.MULTILINE)


@dataclass
class FormatOptions:
    """Style settings for :func:`format_text`."""

    sort_fields: bool = False
    field_order: Sequence[str] = tuple(FIELD_ORDER)
    sort_entries: bool = False
    braces: bool = True  # "..." and bare numbers become {...}
    months: bool = True  # month values become bare macros (jun)
    pages: bool = True  # page ranges use "--" (12-15 -> 12--15)
    align: bool = True
    indent: str = "  "
    blank_lines: int = 1
    trailing_comma: bool = False
    drop_empty: bool = False


@dataclass
class FormatResult:
    """Outcome of formatting one text."""

    text: str
    entries: int
    changed: List[str] = field(default_factory=list)  # keys of reformatted entries
    reordered: bool = False

    def describe(self) -> str:
        if self.changed:
            detail = f"{len(self.changed)} of {self.entries} entries reformatted"
        else:
            detail = f"spacing between entries only ({self.entries} entries unchanged)"
        if self.reordered:
            detail += ", entries sorted"
        return detail


@dataclass
class _Block:
    """Non-entry text (comments, @string, ...) preceding an entry."""

    lines: List[str]
    attached: bool  # no blank line between the block and the entry after it

    @property
    def hoisted(self) -> bool:
        return bool(_HOISTED_BLOCK.search("\n".join(self.lines)))


# ----------------------------------------------------------------- values


def _is_empty(raw: str) -> bool:
    tokens = value_tokens(raw)
    return len(tokens) == 1 and tokens[0][:1] in '{"' and not unwrap(tokens[0]).strip()


def _convert(name: str, raw: str, options: FormatOptions) -> str:
    """Return the formatted value text for field *name* with raw value *raw*."""
    tokens = value_tokens(raw)
    if len(tokens) != 1:
        return raw
    token = tokens[0]
    if name == "month" and options.months:
        macro = month_macro(unwrap(token))
        if macro:
            return macro
    if name == "pages" and options.pages and token[:1] in '{"':
        token = token[0] + page_range(unwrap(token)) + token[-1]
    if options.braces:
        if token.startswith('"') and balanced(unwrap(token)):
            return "{" + unwrap(token) + "}"
        if token.isascii() and token.isdigit():
            return "{" + token + "}"
    return token


# --------------------------------------------------------------- entries


def _render_entry(text: str, entry: EntrySpan, options: FormatOptions) -> str:
    fields: List[Tuple[str, str]] = []
    for span in entry.fields.values():
        raw = text[span.value_start : span.value_end]
        if options.drop_empty and _is_empty(raw):
            continue
        name = span.name.lower()
        fields.append((name, _convert(name, raw, options)))

    if options.sort_fields:
        rank = {n.lower(): i for i, n in enumerate(options.field_order)}
        # sorted() is stable, so unlisted fields keep their source order.
        fields.sort(key=lambda f: rank.get(f[0], len(rank)))

    width = max((len(n) for n, _ in fields), default=0) if options.align else 0
    lines = [f"@{entry.entry_type.lower()}{{{entry.key},"]
    for i, (name, value) in enumerate(fields):
        comma = "," if i < len(fields) - 1 or options.trailing_comma else ""
        lines.append(f"{options.indent}{name.ljust(width)} = {value}{comma}")
    lines.append("}")
    return "\n".join(lines)


# ------------------------------------------------------------ layout text


def _is_blank(line: str) -> bool:
    return not line.strip()


def _block(lines: List[str]) -> Optional[_Block]:
    """Build a block from the lines between two entries.

    The last element of *lines* is the text before ``@`` on the next entry's
    line, so a blank last element is not a blank line.
    """
    content = [i for i, line in enumerate(lines) if not _is_blank(line)]
    if not content:
        return None
    first, last = content[0], content[-1]
    trailing_blank = len(lines) - 1 - last - 1
    return _Block(lines[first : last + 1], attached=trailing_blank <= 0)


def _split_gap(gap: str) -> Tuple[str, List[str]]:
    """Split the text after an entry into its same-line remainder and next lines."""
    parts = gap.split("\n")
    if len(parts) == 1:
        return "", parts
    return parts[0].rstrip(), parts[1:]


def _split_head(block: _Block) -> Tuple[Optional[_Block], Optional[_Block]]:
    """Split the text above the first entry into a file header and the
    paragraph directly attached to that entry (which moves with it when sorting).

    Without a blank line the whole block is treated as a file header.
    """
    blanks = [i for i, line in enumerate(block.lines) if _is_blank(line)]
    if not blanks:
        return block, None
    tail = _Block(block.lines[blanks[-1] + 1 :], attached=True)
    if tail.hoisted:
        return block, None
    head_lines = block.lines[: blanks[-1]]
    while head_lines and _is_blank(head_lines[-1]):
        head_lines.pop()
    return _Block(head_lines, attached=False), tail


def _outside_lines(text: str, entries: List[EntrySpan]) -> List[str]:
    """Non-blank stripped lines of the text outside entries."""
    pieces, pos = [], 0
    for entry in entries:
        pieces.append(text[pos : entry.start])
        pos = entry.end
    pieces.append(text[pos:])
    return [line.strip() for piece in pieces for line in piece.split("\n") if line.strip()]


def _render(
    text: str, entries: List[EntrySpan], options: FormatOptions
) -> Tuple[str, List[str], bool]:
    """Format LF text whose entries are *entries*.

    Returns ``(text, keys of reformatted entries, whether entries moved)``.
    """
    # blocks[i] precedes entries[i]; blocks[0] is the text at the top of the file.
    blocks: List[Optional[_Block]] = [_block(text[: entries[0].start].split("\n"))]
    remainders: List[str] = []
    rendered: List[str] = []
    changed: List[str] = []
    trailer: Optional[_Block] = None
    for i, entry in enumerate(entries):
        new_entry = _render_entry(text, entry, options)
        if new_entry != text[entry.start : entry.end]:
            changed.append(entry.key)
        rendered.append(new_entry)
        last = i + 1 == len(entries)
        remainder, lines = _split_gap(text[entry.end : len(text) if last else entries[i + 1].start])
        remainders.append(remainder)
        if last:
            trailer = _block(lines + [""])
        else:
            blocks.append(_block(lines))

    head, blocks[0] = blocks[0], None
    if head is not None and options.sort_entries and head.attached:
        head, blocks[0] = _split_head(head)
    top: List[_Block] = [head] if head else []
    order = list(range(len(entries)))
    if options.sort_entries:
        # @string/@preamble definitions must stay above the entries using them.
        for i, b in enumerate(blocks):
            if b is not None and b.hoisted:
                top.append(b)
                blocks[i] = None
        order.sort(key=lambda i: entries[i].key.lower())

    sep = "\n" * (options.blank_lines + 1)
    out: List[str] = []
    for n, b in enumerate(top):
        out.append("\n".join(b.lines))
        out.append("\n" if n == len(top) - 1 and b.attached else sep)
    for n, i in enumerate(order):
        if n:
            out.append(sep)
        b = blocks[i]
        if b is not None:
            out.append("\n".join(b.lines))
            out.append("\n" if b.attached else sep)
        out.append(rendered[i] + remainders[i])
    if trailer is not None:
        out.append(sep)
        out.append("\n".join(trailer.lines))
    out.append("\n")
    return "".join(out), changed, order != sorted(order)


# ------------------------------------------------------------ verification


def _parse(text: str):
    parser = bibtexparser.bparser.BibTexParser(
        common_strings=True, ignore_nonstandard_types=False, interpolate_strings=False
    )
    try:
        return bibtexparser.loads(text, parser=parser)
    except Exception as e:  # pyparsing and bibtexparser raise assorted types
        raise BibEditError(f"bibtexparser cannot parse the file: {e}") from e


def _canon(value) -> object:
    if isinstance(value, BibDataStringExpression):
        return tuple(
            ("macro", part.name.lower()) if isinstance(part, BibDataString) else ("text", part)
            for part in value.expr
        )
    if isinstance(value, BibDataString):
        return (("macro", value.name.lower()),)
    return value


def _month_of(value) -> Optional[str]:
    canon = _canon(value)
    if isinstance(canon, tuple):
        return month_macro(canon[0][1]) if len(canon) == 1 else None
    return month_macro(canon)


def _verify(old: str, new: str, options: FormatOptions) -> None:
    """Raise BibEditError unless *new* holds the same bibliography as *old*."""
    old_spans, new_spans = scan(old), scan(new)
    old_keys = [e.key for e in old_spans]
    expected = sorted(old_keys, key=str.lower) if options.sort_entries else old_keys
    if [e.key for e in new_spans] != expected:
        raise BibEditError("formatting changed the sequence of citation keys")

    old_lines, new_lines = _outside_lines(old, old_spans), _outside_lines(new, new_spans)
    if options.sort_entries:
        old_lines, new_lines = sorted(old_lines), sorted(new_lines)
    if old_lines != new_lines:
        raise BibEditError("formatting changed the text between entries")

    old_db, new_db = _parse(old), _parse(new)
    for label, db, keys in (("input", old_db, old_keys), ("output", new_db, expected)):
        parsed = [e["ID"] for e in db.entries]
        if sorted(parsed) != sorted(keys):
            missing = sorted(set(keys) - set(parsed)) or sorted(set(parsed) - set(keys))
            raise BibEditError(f"bibtexparser does not read entry '{missing[0]}' of the {label}")
    if {k: _canon(v) for k, v in old_db.strings.items()} != {
        k: _canon(v) for k, v in new_db.strings.items()
    } or old_db.preambles != new_db.preambles:
        raise BibEditError("formatting changed @string or @preamble definitions")

    new_by_key = {e["ID"]: e for e in new_db.entries}
    for old_entry in old_db.entries:
        key = old_entry["ID"]
        new_entry = new_by_key[key]
        if old_entry["ENTRYTYPE"].lower() != new_entry["ENTRYTYPE"].lower():
            raise BibEditError(f"formatting changed the type of '{key}'")
        for name in set(old_entry) | set(new_entry):
            if name in ("ID", "ENTRYTYPE"):
                continue
            if name not in new_entry:
                if options.drop_empty and _canon(old_entry[name]) == "":
                    continue
                raise BibEditError(f"formatting removed field '{name}' of '{key}'")
            if name not in old_entry:
                raise BibEditError(f"formatting added field '{name}' to '{key}'")
            old_value, new_value = old_entry[name], new_entry[name]
            if _canon(old_value) == _canon(new_value):
                continue
            if name == "month" and _month_of(old_value) and _month_of(old_value) == _month_of(new_value):
                continue
            if (
                name == "pages"
                and options.pages
                and isinstance(old_value, str)
                and page_range(old_value) == _canon(new_value)
            ):
                continue
            raise BibEditError(f"formatting changed field '{name}' of '{key}'")


# ---------------------------------------------------------------- public


def format_bib(text: str, options: Optional[FormatOptions] = None) -> FormatResult:
    """Format BibTeX *text*; the result is verified and idempotent.

    Raises:
        BibEditError: if the text cannot be scanned or parsed, has duplicate
            keys, or the formatted text fails verification.
    """
    options = options or FormatOptions()
    bom = _BOM if text.startswith(_BOM) else ""
    crlf = "\r\n" in text
    lf = text[len(bom) :].replace("\r\n", "\n")

    entries = scan(lf)
    if not entries:
        return FormatResult(text, 0)
    duplicates = [k for k, n in Counter(e.key for e in entries).items() if n > 1]
    if duplicates:
        raise BibEditError(f"duplicate citation key '{duplicates[0]}'")

    new_lf, changed, reordered = _render(lf, entries, options)
    _verify(lf, new_lf, options)
    again, _, _ = _render(new_lf, scan(new_lf), options)
    if again != new_lf:
        raise BibEditError("formatting is not idempotent for this file")

    new_text = bom + (new_lf.replace("\n", "\r\n") if crlf else new_lf)
    return FormatResult(new_text, len(entries), changed, reordered)


def format_text(text: str, options: Optional[FormatOptions] = None) -> str:
    """Return *text* formatted with *options* (see :func:`format_bib`)."""
    return format_bib(text, options).text


def collect_bib_files(paths: Sequence[str | Path]) -> Tuple[List[Path], List[str]]:
    """Expand files and directories (recursively) into .bib files.

    Returns ``(files, missing_paths)``; ``.bibcc/`` folders are skipped.
    """
    files: List[Path] = []
    missing: List[str] = []
    for raw in paths:
        path = Path(raw)
        if path.is_dir():
            found = (
                f
                for f in path.rglob("*.bib")
                if f.is_file() and OUTPUT_DIR_NAME not in f.relative_to(path).parts
            )
            files.extend(sorted(found))
        elif path.is_file():
            files.append(path)
        else:
            missing.append(str(raw))
    unique: List[Path] = []
    seen: Set[Path] = set()
    for f in files:
        if f.resolve() not in seen:
            seen.add(f.resolve())
            unique.append(f)
    return unique, missing


def format_paths(
    paths: Sequence[str | Path],
    options: FormatOptions,
    *,
    in_place: bool = False,
    output: Optional[str | Path] = None,
    check: bool = False,
    log_dir: Optional[Path] = None,
    log: Optional[Callable[[str], None]] = None,
) -> Dict[str, list]:
    """Format every .bib file under *paths*.

    Without *in_place*, *output*, or *check* this is a dry run that writes a
    ``.bibcc/<file>.format.diff`` per changed file.  *check* writes nothing.

    Returns ``{"changed": [path], "unchanged": [path], "failed": [(path, error)]}``.
    """
    log = log or print
    files, missing = collect_bib_files(paths)
    changed: List[str] = []
    unchanged: List[str] = []
    failed: List[Tuple[str, str]] = [(m, "no such file or directory") for m in missing]
    for m in missing:
        log(f"❌ {m}: no such file or directory")
    if output is not None and len(files) + len(missing) != 1:
        raise BibEditError("--output needs exactly one input file")

    for path in files:
        try:
            text = read_bib(path)
            result = format_bib(text, options)
        except (BibEditError, UnicodeDecodeError) as e:
            log(f"❌ {path}: {e} (skipped)")
            failed.append((str(path), str(e)))
            continue

        is_changed = result.text != text
        (changed if is_changed else unchanged).append(str(path))
        status = result.describe() if is_changed else f"already formatted ({result.entries} entries)"

        if check:
            log(f"{'✏️  would reformat' if is_changed else '✅'} {path}: {status}")
        elif output is not None:
            write_bib(output, result.text)
            log(f"✅ {path} → {output}: {status}")
        elif in_place:
            if is_changed:
                write_bib(path, result.text)
            log(f"✅ {path}: {status}")
        else:
            diff_path = get_output_dir(path, log_dir) / f"{path.name}.format.diff"
            if is_changed:
                diff_path.write_text(unified_diff(text, result.text, path), encoding="utf-8")
                log(f"✏️  {path}: {status}. Diff: {diff_path}")
            else:
                diff_path.unlink(missing_ok=True)
                log(f"✅ {path}: {status}")

    log(SEPARATOR_THIN * SEPARATOR_WIDTH)
    verb = "would change" if check or not (in_place or output is not None) else "changed"
    log(f"{len(files)} file(s): {len(changed)} {verb}, {len(unchanged)} already formatted, "
        f"{len(failed)} failed.")
    if changed and not (check or in_place or output is not None):
        log("🧪 Dry run. To write the changes, run with --in-place or --output <file.bib>")
    return {"changed": changed, "unchanged": unchanged, "failed": failed}


def _indent(value: str) -> str:
    if value.lower() in ("tab", "\\t", "\t"):
        return "\t"
    if value.isdigit():
        return " " * int(value)
    raise argparse.ArgumentTypeError("use a number of spaces or 'tab'")


def _non_negative(value: str) -> int:
    if not value.isdigit():
        raise argparse.ArgumentTypeError("expected a non-negative integer")
    return int(value)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Reformat .bib files consistently (aligned fields, braced values, "
        "month macros). Dry run by default."
    )
    parser.add_argument("paths", nargs="+", metavar="PATH", help=".bib files or directories (searched recursively)")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--in-place", action="store_true", help="Write the formatted text back to each file.")
    mode.add_argument("-o", "--output", default="", help="Write the formatted file here (single input file only).")
    mode.add_argument("--check", action="store_true", help="Write nothing; exit 1 if any file would change.")
    parser.add_argument("--sort-fields", action="store_true", help="Reorder fields using --field-order.")
    parser.add_argument(
        "--field-order",
        default=",".join(FIELD_ORDER),
        help="Comma-separated field order for --sort-fields; other fields follow in "
        "source order (default: the order used by 'bibcc add').",
    )
    parser.add_argument("--sort-entries", action="store_true", help="Sort entries by citation key (case-insensitive).")
    parser.add_argument("--keep-quotes", action="store_true", help='Keep "..." values and bare numbers as they are.')
    parser.add_argument("--keep-months", action="store_true", help="Do not turn month values into macros (jun).")
    parser.add_argument("--keep-pages", action="store_true", help="Do not turn page ranges like 12-15 into 12--15.")
    parser.add_argument("--no-align", action="store_true", help="Write 'name = value' without aligning '='.")
    parser.add_argument(
        "--indent", type=_indent, default="2", help="Field indent: number of spaces or 'tab' (default: 2)."
    )
    parser.add_argument(
        "--blank-lines", type=_non_negative, default=1, help="Blank lines between entries (default: 1)."
    )
    parser.add_argument("--trailing-comma", action="store_true", help="Put a comma after the last field.")
    parser.add_argument("--drop-empty", action="store_true", help="Remove fields with empty values ({} or \"\").")
    parser.add_argument(
        "--log-dir",
        default="",
        help="Directory for diffs and logs. Default: .bibcc/ next to each input file.",
    )
    return parser


def run(args: argparse.Namespace) -> None:
    files, missing = collect_bib_files(args.paths)
    if args.output and (len(args.paths) != 1 or len(files) != 1 or missing or Path(args.paths[0]).is_dir()):
        build_parser().error("--output needs exactly one input .bib file")
    options = FormatOptions(
        sort_fields=args.sort_fields,
        field_order=tuple(f.strip().lower() for f in args.field_order.split(",") if f.strip()),
        sort_entries=args.sort_entries,
        braces=not args.keep_quotes,
        months=not args.keep_months,
        pages=not args.keep_pages,
        align=not args.no_align,
        indent=args.indent,
        blank_lines=args.blank_lines,
        trailing_comma=args.trailing_comma,
        drop_empty=args.drop_empty,
    )
    log_dir = Path(args.log_dir) if args.log_dir else None
    first = Path(args.paths[0])
    logger_dir = log_dir
    if logger_dir is None and first.is_dir():
        logger_dir = first.resolve() / OUTPUT_DIR_NAME / "logs"

    with Logger("formatter", input_file=first, log_dir=logger_dir, enabled=not args.check) as logger:
        summary = format_paths(
            args.paths,
            options,
            in_place=args.in_place,
            output=args.output or None,
            check=args.check,
            log_dir=log_dir,
            log=logger.log,
        )
    if summary["failed"] or (args.check and summary["changed"]):
        sys.exit(1)


if __name__ == "__main__":
    run(build_parser().parse_args())
