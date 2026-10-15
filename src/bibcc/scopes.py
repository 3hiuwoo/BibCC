"""
Scopes: where BibCC's user files live, and the shared examples to start them from.

BibCC keeps three kinds of user files, each in two scopes:

=========  ===================================  =====================
Kind       User scope                           Project scope
=========  ===================================  =====================
config     ``$BIBCC_CONFIG`` or ``config.yaml``  ``.bibcc.yaml``
venues     ``$BIBCC_VENUES`` or ``venues.yaml``  ``.bibcc-venues.yaml``
terms      ``$BIBCC_TERMS`` or ``terms.txt``     ``.bibcc-terms.txt``
=========  ===================================  =====================

The user files live in ``$XDG_CONFIG_HOME/bibcc/`` (``~/.config/bibcc/``)
unless their environment variable names another path.  A project file is
the nearest one in the directory of the ``.bib`` file or a parent directory.
A new project file goes next to the project's other BibCC files (its root),
or into the current directory when there are none.

Shared files to start from live in ``examples/KIND/`` of the BibCC
repository; :func:`read_source` and :func:`example_names` read them from the
checkout BibCC runs from, or else from GitHub.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple

USER_SCOPE = "user"
PROJECT_SCOPE = "project"
FILE_SCOPE = "file"  # a file named on the command line (--venues FILE, --config FILE)
SCOPES = (USER_SCOPE, PROJECT_SCOPE)

REPO = "3hiuwoo/BibCC"
EXAMPLES_BRANCH = "main"
EXAMPLE_RAW_URL = f"https://raw.githubusercontent.com/{REPO}/{EXAMPLES_BRANCH}/examples/{{kind}}/{{name}}{{suffix}}"
EXAMPLES_API_URL = f"https://api.github.com/repos/{REPO}/contents/examples/{{kind}}?ref={EXAMPLES_BRANCH}"
EXAMPLES_PAGE_URL = f"https://github.com/{REPO}/tree/{EXAMPLES_BRANCH}/examples/{{kind}}"

_EXAMPLE_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*")


def config_home() -> Path:
    """``$XDG_CONFIG_HOME/bibcc`` (``~/.config/bibcc`` by default)."""
    return Path(os.environ.get("XDG_CONFIG_HOME") or "~/.config").expanduser() / "bibcc"


@dataclass(frozen=True)
class FileKind:
    """One kind of user file: where its user and project files live, and its shared examples."""

    name: str  # the command that manages it, and its examples/ directory
    label: str  # "config", "venue library", "terms file"
    env_var: str
    user_name: str
    project_name: str
    suffix: str
    example_label: str  # "example config", ...
    examples_label: str  # "example configs", ...

    @property
    def user_display(self) -> str:
        return f"~/.config/bibcc/{self.user_name}"

    def user_path(self) -> Path:
        """``$ENV_VAR`` if set, else ``$XDG_CONFIG_HOME/bibcc/USER_NAME``."""
        env = os.environ.get(self.env_var)
        return Path(env).expanduser() if env else config_home() / self.user_name

    def find_project(self, start: Optional[str | Path] = None) -> Optional[Path]:
        """The nearest project file in *start* (a file or directory; default: cwd) or its parents."""
        for folder in _folders(start):
            candidate = folder / self.project_name
            if candidate.is_file():
                return candidate
        return None

    def new_project_path(self, start: Optional[str | Path] = None) -> Path:
        """Where a new project file goes: next to the nearest other project file above *start*, or the cwd."""
        for folder in _folders(start):
            if any((folder / kind.project_name).is_file() for kind in KINDS if kind is not self):
                return folder / self.project_name
        return Path.cwd() / self.project_name


def _folders(start: Optional[str | Path]) -> List[Path]:
    here = Path(start or Path.cwd()).expanduser().resolve()
    if not here.is_dir():
        here = here.parent
    return [here, *here.parents]


CONFIG = FileKind("config", "config", "BIBCC_CONFIG", "config.yaml", ".bibcc.yaml", ".yaml",
                  "example config", "example configs")
VENUES = FileKind("venues", "venue library", "BIBCC_VENUES", "venues.yaml", ".bibcc-venues.yaml", ".yaml",
                  "example library", "examples")
TERMS = FileKind("terms", "terms file", "BIBCC_TERMS", "terms.txt", ".bibcc-terms.txt", ".txt",
                 "example terms file", "example terms files")
KINDS = (CONFIG, VENUES, TERMS)


# --------------------------------------------------------------- examples


def local_examples_dir(kind: FileKind) -> Optional[Path]:
    """``examples/KIND/`` of the checkout BibCC runs from, if it runs from one (editable install)."""
    import bibcc

    folder = Path(bibcc.__file__).resolve().parents[2] / "examples" / kind.name
    return folder if folder.is_dir() else None


def example_name(kind: FileKind, source: str) -> str:
    """*source* without the file suffix (``.yml`` too, for YAML kinds)."""
    if kind.suffix == ".yaml":
        return re.sub(r"\.ya?ml$", "", source)
    return source[: -len(kind.suffix)] if source.endswith(kind.suffix) else source


def read_source(source: str, kind: FileKind) -> Tuple[str, str]:
    """``(text, where it came from)`` for a file, an http(s) URL, or the name of a file in ``examples/KIND/``.

    Raises :class:`ValueError` when *source* is none of them or can't be read.
    """
    from bibcc import sources

    path = Path(source).expanduser()
    if path.is_file():
        return path.read_text(encoding="utf-8"), str(path)
    if re.match(r"https?://", source):
        content, error = sources.fetch_url(source)
        if error:
            raise ValueError(f"could not download {source}: {error}")
        return content or "", source
    name = example_name(kind, source)
    if not _EXAMPLE_NAME.fullmatch(name):
        raise ValueError(f"{source}: no such file, URL, or {kind.example_label} name")
    local = local_examples_dir(kind)
    if local is not None and (local / f"{name}{kind.suffix}").is_file():
        example = local / f"{name}{kind.suffix}"
        return example.read_text(encoding="utf-8"), str(example)
    url = EXAMPLE_RAW_URL.format(kind=kind.name, name=name, suffix=kind.suffix)
    content, error = sources.fetch_url(url)
    if error:
        raise ValueError(
            f"{source}: no such file, and no {kind.example_label} of that name ({url}: {error}). "
            f"List them with: bibcc {kind.name} examples"
        )
    return content or "", url


def example_names(kind: FileKind) -> Tuple[List[Path], List[str], str]:
    """``(local files, remote names, where)`` of the files in ``examples/KIND/``, local checkout first.

    Raises :class:`ValueError` when the list can't be downloaded.
    """
    from bibcc import sources

    local = local_examples_dir(kind)
    if local is not None:
        return sorted(local.glob(f"*{kind.suffix}")), [], str(local)
    page = EXAMPLES_PAGE_URL.format(kind=kind.name)
    data, error = sources.fetch_json(EXAMPLES_API_URL.format(kind=kind.name))
    if error or not isinstance(data, list):
        raise ValueError(f"could not list the {kind.examples_label} ({error or 'unexpected answer'}); see {page}")
    names = [item["name"][: -len(kind.suffix)] for item in data
             if isinstance(item, dict) and str(item.get("name", "")).endswith(kind.suffix)]
    return [], sorted(names), page
