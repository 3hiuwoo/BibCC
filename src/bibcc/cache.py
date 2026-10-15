"""
Disk cache for the official BibTeX that BibCC downloads.

``add``, ``upgrade``, and ``check official`` download a paper's official
BibTeX export; a later run on the same paper reads it from here instead of
the network.  Only a paper's own export is kept (never a listing page, an
error, or a bot-protection page), and an item older than
:data:`MAX_AGE_DAYS` is downloaded again.

The cache lives in ``$BIBCC_CACHE`` if set, else
``$XDG_CACHE_HOME/bibcc`` (``~/.cache/bibcc``).  ``BIBCC_CACHE=off``
turns it off; :func:`refresh` makes the rest of a run download everything
again (``bibcc check official --refresh``) and update the cache.

Usage:
    from bibcc import cache

    text = cache.get(url)
    if text is None:
        ...
        cache.put(url, text)
"""

from __future__ import annotations

import hashlib
import os
import time
from pathlib import Path
from typing import Optional

CACHE_ENV_VAR = "BIBCC_CACHE"
CACHE_DISPLAY = "~/.cache/bibcc"
OFF = "off"
MAX_AGE_DAYS = 30

_refresh = False


def cache_dir() -> Optional[Path]:
    """The cache directory, or None when ``BIBCC_CACHE=off``."""
    env = os.environ.get(CACHE_ENV_VAR)
    if env is not None and env.strip().lower() in (OFF, "0", "no", "false", ""):
        return None
    if env:
        return Path(env).expanduser()
    base = os.environ.get("XDG_CACHE_HOME") or "~/.cache"
    return Path(base).expanduser() / "bibcc"


def refresh(on: bool = True) -> None:
    """Ignore what the cache holds for the rest of the run (new downloads still update it)."""
    global _refresh
    _refresh = on


def _path(key: str) -> Optional[Path]:
    folder = cache_dir()
    if folder is None:
        return None
    return folder / "official" / (hashlib.sha256(key.encode("utf-8")).hexdigest()[:40] + ".txt")


def get(key: str) -> Optional[str]:
    """The text kept for *key* (a URL, or a name such as ``xplore-document:DOI``), or None."""
    path = _path(key)
    if _refresh or path is None or not path.is_file():
        return None
    if time.time() - path.stat().st_mtime > MAX_AGE_DAYS * 86400:
        return None
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return None


def put(key: str, text: str) -> None:
    """Keep *text* for *key*; a cache that can't be written is skipped silently."""
    path = _path(key)
    if path is None:
        return
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    except OSError:
        pass
