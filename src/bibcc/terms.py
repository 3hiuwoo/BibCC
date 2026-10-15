"""
Protected terms: the words that ``check quote`` keeps in {braces}.

Like the venue library, terms live in two scopes.  The user terms file
(``$BIBCC_TERMS``, else ``~/.config/bibcc/terms.txt``) holds terms for every
project, and a project terms file (``.bibcc-terms.txt``, committed with the
bibliography) holds the terms of one project.  ``check quote`` reads both,
on top of its built-in vocabulary of names, and braces their terms with
``--apply``.  A file has one term per line; blank lines and ``#`` comments
are ignored.  Shared lists to start from live in ``examples/terms/`` of the
BibCC repository.

Usage:
    from bibcc.terms import add_terms, load_terms, terms_path

    sources = load_terms("bib/refs.bib")          # user, then project
    add_terms(terms_path("project", start="bib/"), ["CIP-Net"])
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, List, Optional

from bibcc.venues import PROJECT_SCOPE, USER_SCOPE, find_project_library

TERMS_ENV_VAR = "BIBCC_TERMS"
PROJECT_TERMS_NAME = ".bibcc-terms.txt"
USER_TERMS_DISPLAY = "~/.config/bibcc/terms.txt"

_HEADER = """\
# Protected terms for 'bibcc check quote': one term per line, with the case
# that titles use. Blank lines and lines that start with # are ignored.
# To add terms, run 'bibcc terms add TERM' or edit this file.
"""


class TermsNotFound(LookupError):
    """The project scope has no terms file, and the caller didn't ask to create one."""


def user_terms_path() -> Path:
    """``$BIBCC_TERMS`` if set, else ``$XDG_CONFIG_HOME/bibcc/terms.txt`` (``~/.config`` by default)."""
    env = os.environ.get(TERMS_ENV_VAR)
    if env:
        return Path(env).expanduser()
    config_home = os.environ.get("XDG_CONFIG_HOME") or "~/.config"
    return Path(config_home).expanduser() / "bibcc" / "terms.txt"


def find_project_terms(start: Optional[str | Path] = None) -> Optional[Path]:
    """The nearest ``.bibcc-terms.txt`` in *start* (a file or folder; default: cwd) or its parents."""
    here = Path(start or Path.cwd()).expanduser().resolve()
    if not here.is_dir():
        here = here.parent
    for folder in (here, *here.parents):
        candidate = folder / PROJECT_TERMS_NAME
        if candidate.is_file():
            return candidate
    return None


def terms_path(scope: str = USER_SCOPE, start: Optional[str | Path] = None, create: bool = False) -> Path:
    """The terms file that *scope* writes to.

    For the project scope, the nearest ``.bibcc-terms.txt`` above *start*.
    Without one, :class:`TermsNotFound` is raised, unless *create*: then
    the file goes next to the project venue library, or into the current
    directory when there's no project library either (written on the
    first :func:`add_terms`).
    """
    if scope == USER_SCOPE:
        return user_terms_path()
    if scope != PROJECT_SCOPE:
        raise ValueError(f"unknown terms scope {scope!r} (use user or project)")
    found = find_project_terms(start)
    if found is not None:
        return found
    if not create:
        where = Path(start or Path.cwd()).expanduser().resolve()
        raise TermsNotFound(
            f"no {PROJECT_TERMS_NAME} in {where} or its parent directories; create one with: "
            "bibcc terms add TERM --scope project"
        )
    library = find_project_library(start)
    folder = library.parent if library is not None else Path.cwd()
    return folder / PROJECT_TERMS_NAME


def parse_terms(text: str) -> List[str]:
    """The terms of a terms file's text, in file order, without duplicates (ignoring case)."""
    terms: List[str] = []
    seen: set[str] = set()
    for line in text.splitlines():
        term = line.strip()
        if term and not term.startswith("#") and term.casefold() not in seen:
            seen.add(term.casefold())
            terms.append(term)
    return terms


def read_terms(path: Path) -> List[str]:
    """The terms of *path*; ``[]`` when the file doesn't exist."""
    return parse_terms(path.read_text(encoding="utf-8")) if path.is_file() else []


def add_terms(path: Path, terms: Iterable[str]) -> List[str]:
    """Append the *terms* that *path* lacks (ignoring case); return the ones added."""
    have = {t.casefold() for t in read_terms(path)}
    new: List[str] = []
    for term in terms:
        term = " ".join(str(term).split())
        if term and not term.startswith("#") and term.casefold() not in have:
            have.add(term.casefold())
            new.append(term)
    if not new:
        return []
    path.parent.mkdir(parents=True, exist_ok=True)
    text = path.read_text(encoding="utf-8") if path.is_file() else _HEADER
    if text and not text.endswith("\n"):
        text += "\n"
    path.write_text(text + "".join(f"{t}\n" for t in new), encoding="utf-8")
    return new


@dataclass
class TermSource:
    """One terms file that a command reads."""

    scope: str
    path: Path
    terms: List[str] = field(default_factory=list)

    @property
    def exists(self) -> bool:
        return self.path.is_file()


def load_terms(start: Optional[str | Path] = None) -> List[TermSource]:
    """The user terms file, then the project terms file above *start* (when there is one)."""
    sources = [TermSource(USER_SCOPE, user_terms_path())]
    project = find_project_terms(start)
    if project is not None:
        sources.append(TermSource(PROJECT_SCOPE, project))
    for source in sources:
        source.terms = read_terms(source.path)
    return sources


def all_terms(start: Optional[str | Path] = None) -> List[str]:
    """Every term of the user and project terms files, without duplicates (ignoring case)."""
    return parse_terms("\n".join(t for source in load_terms(start) for t in source.terms))

