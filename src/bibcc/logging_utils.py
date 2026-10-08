"""
Unified logging utilities for BibCC tools.

This module provides a consistent logging strategy across all tools:
- Automatic log file generation (no manual --output needed)
- Simultaneous stdout and file output
- Consistent log file naming convention
- All logs stored in logs/ subdirectory

Usage:
    from bibcc.logging_utils import Logger

    # Create logger that auto-generates log file from input file
    logger = Logger("checker", input_file="my.bib")
    # -> Creates: logs/my.bib.checker.log

    # Log messages (goes to both stdout and file)
    logger.log("Processing...")
    logger.log("Found 10 entries", prefix="✅")

    # At the end, finalize the log
    logger.close()
"""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path
from typing import IO, List, Optional, TextIO

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


def get_repo_dir() -> Path:
    """Get the repository directory (where this file is located)."""
    return Path(__file__).parent.resolve()


def get_logs_dir() -> Path:
    """Get the logs directory (repo_dir/logs/)."""
    logs_dir = get_repo_dir() / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    return logs_dir


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
        logs/<input_file>.<tool_name>.log

    If no input file is provided, uses:
        logs/<tool_name>_<timestamp>.log
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
            log_dir: Directory for log files (default: repo_dir/logs/)
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

        # Always use logs/ subdirectory (unless explicit log_dir)
        log_dir_path = Path(log_dir) if log_dir else get_logs_dir()
        log_dir_path.mkdir(parents=True, exist_ok=True)

        # Determine log file path
        if input_file:
            input_path = Path(input_file)
            base_name = input_path.name
            self._log_path = log_dir_path / f"{base_name}.{tool_name}{log_suffix}"
        else:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            self._log_path = log_dir_path / f"{tool_name}_{timestamp}{log_suffix}"

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


class TeeWriter:
    """
    A writer that duplicates output to multiple destinations.

    This can be used to redirect stdout to both console and file.
    """

    def __init__(self, *writers: TextIO):
        self.writers = writers

    def write(self, text: str) -> int:
        for writer in self.writers:
            writer.write(text)
            writer.flush()
        return len(text)

    def flush(self) -> None:
        for writer in self.writers:
            writer.flush()


def create_log_path(
    input_file: str | Path,
    tool_name: str,
    suffix: str = ".log",
    log_dir: Optional[str | Path] = None,
) -> Path:
    """
    Create a standardized log file path.

    Args:
        input_file: The input file being processed
        tool_name: Name of the tool
        suffix: Log file suffix (default: ".log")
        log_dir: Optional directory for log files

    Returns:
        Path to the log file
    """
    input_path = Path(input_file)
    base_name = input_path.name

    if log_dir:
        log_dir_path = Path(log_dir)
        log_dir_path.mkdir(parents=True, exist_ok=True)
        return log_dir_path / f"{base_name}.{tool_name}{suffix}"
    else:
        return input_path.parent / f"{base_name}.{tool_name}{suffix}"
