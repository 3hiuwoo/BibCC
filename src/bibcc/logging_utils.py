"""
Unified logging utilities for BibCC tools.

This module provides a consistent logging strategy across all tools:
- Automatic log file generation (no manual --output needed)
- Simultaneous stdout and file output
- Consistent log file naming convention
- Reports and logs stored in ``.bibcc/<input name>/`` next to the input file

Usage:
    from bibcc.logging_utils import Logger

    # Create logger that auto-generates log file from input file
    logger = Logger("checker", input_file="refs/my.bib")
    # -> Creates: refs/.bibcc/my.bib/logs/checker.log

    # Log messages (goes to both stdout and file)
    logger.log("Processing...")
    logger.log("Found 10 entries", prefix="✅")

    # At the end, finalize the log
    logger.close()
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import IO, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Format constants — shared across all BibCC tools
# ---------------------------------------------------------------------------

SEPARATOR_WIDTH: int = 70
"""Standard width for separator lines in logs and reports."""

SEPARATOR_HEAVY: str = "="
"""Character for heavy separators (headers, section boundaries)."""

SEPARATOR_LIGHT: str = "-"
"""Character for light separators (subsection breaks)."""

SEPARATOR_THIN: str = "─"
"""Character for thin separators (summary lines)."""


OUTPUT_DIR_NAME: str = ".bibcc"
"""Name of the per-directory folder holding reports and logs."""

NESTED_REPORTS_DIR: str = "reports"
"""For an input already inside a ``.bibcc/`` tree: the sibling folder for its reports."""

REPORT_KINDS: Tuple[str, ...] = (
    "add.txt", "citation_keys.txt", "complete.diff", "conflicts.txt", "extra_pdfs.txt",
    "field_issues.txt", "format.diff", "incomplete_entries.txt", "missing_fields.txt",
    "missing_pdfs.txt", "missing_venues.txt", "missing_venues.yaml", "published.txt",
    "rename_report.txt", "scholar_urls.txt", "smart_protection.txt", "title_case.txt",
    "title_report.txt", "upgrade.diff", "upgrade.txt", "venue_check.txt",
)
"""Every report file name; the flat ``.bibcc/NAME.KIND`` files of 0.3 are moved by these."""

TOOL_NAMES: Tuple[str, ...] = (
    "adder", "checker", "completer", "composer", "formatter", "librarian",
    "scholar.cite", "scholar.titles", "upgrader",
)


def report_dir(
    path: Optional[str | Path] = None,
    override: Optional[str | Path] = None,
    create: bool = True,
) -> Path:
    """Return (and create) the directory for the reports about *path*.

    *path* is a ``.bib`` file or a directory; its reports go to
    ``.bibcc/NAME/`` next to it.  *override* (``--log-dir``) takes the place
    of that ``.bibcc/``.  A *path* that is already inside a ``.bibcc/`` tree
    gets ``reports/NAME/`` next to it, so ``.bibcc`` folders never nest.
    Without *path*: ``./.bibcc/`` (or *override*).  With *create* false, the
    directory is only named, not made.
    """
    if path is None:
        out = Path(override) if override else Path.cwd() / OUTPUT_DIR_NAME
    else:
        p = Path(path).resolve()
        if override:
            out = Path(override) / p.name
        elif OUTPUT_DIR_NAME in p.parent.parts:
            out = p.parent / NESTED_REPORTS_DIR / p.name
        else:
            out = p.parent / OUTPUT_DIR_NAME / p.name
    if create:
        out.mkdir(parents=True, exist_ok=True)
    return out


def report_path(path: Optional[str | Path], kind: str, override: Optional[str | Path] = None) -> Path:
    """``report_dir(path, override) / kind``, for one of :data:`REPORT_KINDS`."""
    return report_dir(path, override) / kind


def remove_report(path: Path) -> None:
    """Delete a report that this run has nothing for, so no stale findings stay behind."""
    try:
        path.unlink()
    except FileNotFoundError:
        pass


def migrate_legacy_reports(path: Optional[str | Path]) -> List[Tuple[Path, Path]]:
    """Move 0.3's flat reports and logs about *path* into its report directory.

    ``.bibcc/NAME.KIND`` becomes ``.bibcc/NAME/KIND`` and
    ``.bibcc/logs/NAME.TOOL.log`` becomes ``.bibcc/NAME/logs/TOOL.log``.
    Files are moved, never deleted (a filled-in missing-venues YAML is user
    work), and a file whose new name is taken stays where it is.  Returns
    the ``(old, new)`` pairs that were moved.
    """
    if path is None:
        return []
    p = Path(path).resolve()
    legacy = p.parent / OUTPUT_DIR_NAME
    if OUTPUT_DIR_NAME in p.parent.parts or not legacy.is_dir():
        return []
    pairs = [(legacy / f"{p.name}.{kind}", Path(kind)) for kind in REPORT_KINDS]
    pairs += [(legacy / "logs" / f"{p.name}.{tool}.log", Path("logs") / f"{tool}.log") for tool in TOOL_NAMES]
    moved: List[Tuple[Path, Path]] = []
    for old, rel in pairs:
        if not old.is_file():
            continue
        new = legacy / p.name / rel
        if new.exists():
            continue
        new.parent.mkdir(parents=True, exist_ok=True)
        old.rename(new)
        moved.append((old, new))
    logs = legacy / "logs"
    if moved and logs.is_dir() and not any(logs.iterdir()):
        logs.rmdir()
    return moved


# ---------------------------------------------------------------------------
# Report-file writer — shared across tools
# ---------------------------------------------------------------------------


def write_report(path: Path, header: str, rows: List[str]) -> None:
    """Write a simple report file with *header* followed by *rows*.

    This is the canonical way to persist checker / completer output so that
    every report file in the repository follows the same lightweight format::

        <header line>
        <row 1>
        <row 2>
        ...

    If *rows* is empty the file will contain ``(none)`` as a placeholder.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    content = [header]
    content.extend(rows if rows else ["(none)"])
    path.write_text("\n".join(content) + "\n", encoding="utf-8")


class Logger:
    """
    Unified logger that writes to both stdout and a log file.

    The log file is automatically named based on the input file and tool name:
        <input dir>/.bibcc/<input_file>/logs/<tool_name>.log

    If no input file is provided, uses:
        ./.bibcc/logs/<tool_name>.log

    The first run on an input moves its 0.3-style flat reports into the new
    layout and logs what it moved.
    """

    def __init__(
        self,
        tool_name: str,
        input_file: Optional[str | Path] = None,
        log_dir: Optional[str | Path] = None,
        log_suffix: str = ".log",
        enabled: bool = True,
    ):
        """
        Initialize the logger.

        Args:
            tool_name: Name of the tool (e.g., "checker", "completer")
            input_file: Path to the input file being processed
            log_dir: The ``--log-dir`` override, which takes the place of
                ``.bibcc/`` (default: ``.bibcc/`` next to the input)
            log_suffix: Suffix for log file (default: ".log")
            enabled: Whether file logging is enabled (default: True)
        """
        self.tool_name = tool_name
        self.enabled = enabled
        self._file: Optional[IO[str]] = None
        self._log_path: Optional[Path] = None
        self._buffer: list[str] = []

        if not enabled:
            return

        moved = [] if log_dir else migrate_legacy_reports(input_file)
        log_dir_path = report_dir(input_file or None, log_dir) / "logs"
        log_dir_path.mkdir(parents=True, exist_ok=True)
        self._log_path = log_dir_path / f"{tool_name}{log_suffix}"

        # Open log file
        try:
            self._file = open(self._log_path, "w", encoding="utf-8")
            # Write header
            self._file.write(f"{SEPARATOR_HEAVY * SEPARATOR_WIDTH}\n")
            self._file.write(f"{tool_name.upper()} LOG\n")
            self._file.write(
                f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
            )
            if input_file:
                self._file.write(f"Input: {input_file}\n")
            self._file.write(f"{SEPARATOR_HEAVY * SEPARATOR_WIDTH}\n\n")
        except IOError as e:
            print(f"⚠️  Could not create log file {self._log_path}: {e}")
            self._file = None
        if moved:
            target = log_dir_path.parent
            self.log(f"📦 Moved {len(moved)} reports and logs from the old .bibcc/ layout to {target}:")
            for old, new in moved:
                self.log(f"   {old.relative_to(target.parent)} → {new.relative_to(target.parent)}")

    @property
    def log_path(self) -> Optional[Path]:
        """Return the path to the log file."""
        return self._log_path

    def log(
        self,
        message: str = "",
        prefix: str = "",
        to_stdout: bool = True,
        to_file: bool = True,
    ) -> None:
        """
        Log a message to stdout and/or file.

        Args:
            message: The message to log
            prefix: Optional prefix (emoji or label)
            to_stdout: Whether to print to stdout (default: True)
            to_file: Whether to write to log file (default: True)
        """
        full_message = f"{prefix} {message}".strip() if prefix else message

        if to_stdout:
            print(full_message)

        if to_file and self._file and self.enabled:
            # Strip ANSI codes and some emojis for cleaner log files
            clean_message = full_message
            self._file.write(clean_message + "\n")
            self._file.flush()

    def log_separator(
        self, char: str = SEPARATOR_LIGHT, length: int = SEPARATOR_WIDTH
    ) -> None:
        """Log a separator line."""
        self.log(char * length)

    def log_header(
        self, title: str, char: str = SEPARATOR_HEAVY, length: int = SEPARATOR_WIDTH
    ) -> None:
        """Log a header with title."""
        self.log(char * length)
        self.log(title)
        self.log(char * length)

    def log_section(self, title: str) -> None:
        """Log a section header."""
        self.log("")
        self.log(f"--- {title} ---")

    def close(self) -> None:
        """Close the log file and print summary."""
        if self._file:
            self._file.write(f"\n{SEPARATOR_HEAVY * SEPARATOR_WIDTH}\n")
            self._file.write(
                f"Log completed: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
            )
            self._file.close()
            self._file = None

        if self._log_path and self.enabled:
            print(f"\n📝 Log saved to: {self._log_path}")

    def __enter__(self) -> "Logger":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()

