"""
Shared pieces of the command-line help (``bibcc <command> -h``).

Every command builds its parser with :class:`HelpFormatter` and an epilog made
by :func:`epilog`, so all help pages share one layout: description, options,
then examples, output files, environment variables, and a pointer to the
README.

Usage:
    parser = argparse.ArgumentParser(
        description=DESCRIPTION,
        epilog=epilog(
            examples=[("Check for a missing month", "bibcc check refs.bib")],
            outputs=[(".bibcc/<input>.missing_fields.txt", "entries missing fields")],
            env=[ENV_VENUES],
        ),
        formatter_class=HelpFormatter,
    )
"""

from __future__ import annotations

import argparse
from typing import Optional, Sequence, Tuple

from bibcc.venues import DEFAULT_LIBRARY_PATH, LIBRARY_ENV_VAR

DOCS_URL = "https://github.com/3hiuwoo/BibCC#readme"

ENV_VENUES: Tuple[str, str] = (LIBRARY_ENV_VAR, "venue library to use when --venues is not given")
ENV_S2: Tuple[str, str] = ("S2_API_KEY", "Semantic Scholar API key (without one, requests are soon rate limited)")

VENUES_HELP = (
    f"Venue library YAML (default: ${LIBRARY_ENV_VAR}, else the bundled {DEFAULT_LIBRARY_PATH})."
)


class HelpFormatter(argparse.RawDescriptionHelpFormatter):
    """Keep the line breaks of descriptions and epilogs; wrap option help as usual."""


def _pairs(rows: Sequence[Tuple[str, str]]) -> str:
    width = max(len(name) for name, _ in rows)
    return "\n".join(f"  {name:<{width}}  {text}" for name, text in rows)


def epilog(
    examples: Sequence[Tuple[str, str]] = (),
    outputs: Sequence[Tuple[str, str]] = (),
    env: Sequence[Tuple[str, str]] = (),
    notes: Optional[str] = None,
    exit_status: Optional[str] = None,
) -> str:
    """Help text shown after the options.

    Args:
        examples: ``(what it does, command)`` pairs.
        outputs: ``(file, what it holds)`` pairs.
        env: ``(variable, meaning)`` pairs.
        notes: Free text, already wrapped.
        exit_status: Free text describing exit codes, already wrapped.
    """
    parts = []
    if examples:
        lines = []
        for what, command in examples:
            lines.append(f"  # {what}")
            lines.append(f"  {command}")
        parts.append("examples:\n" + "\n".join(lines))
    if outputs:
        parts.append("output files:\n" + _pairs(outputs))
    if notes:
        parts.append("notes:\n" + _indent(notes))
    if exit_status:
        parts.append("exit status:\n" + _indent(exit_status))
    if env:
        parts.append("environment:\n" + _pairs(env))
    parts.append(f"Full documentation: {DOCS_URL}")
    return "\n\n".join(parts)


def _indent(text: str) -> str:
    return "\n".join(f"  {line}" if line else "" for line in text.strip("\n").splitlines())
