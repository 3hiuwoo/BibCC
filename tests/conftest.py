import shutil
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"
EXAMPLE_VENUES = Path(__file__).parent.parent / "examples" / "venues"
MIAA_VENUES = EXAMPLE_VENUES / "miaa.yaml"


@pytest.fixture(autouse=True)
def isolated_user_library(tmp_path_factory, monkeypatch) -> Path:
    """Point the user venue library at an empty temporary folder, never the real one."""
    config = tmp_path_factory.mktemp("config")
    monkeypatch.delenv("BIBCC_VENUES", raising=False)
    monkeypatch.delenv("BIBCC_CONFIG", raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(config))
    # Each test gets its own download cache, so no test reads another's downloads.
    monkeypatch.setenv("BIBCC_CACHE", str(tmp_path_factory.mktemp("cache")))
    from bibcc import cache

    cache.refresh(False)
    return config / "bibcc" / "venues.yaml"


@pytest.fixture
def miaa_user_library(isolated_user_library: Path) -> Path:
    """The isolated user library, filled with a copy of the MIAA example library."""
    isolated_user_library.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(MIAA_VENUES, isolated_user_library)
    return isolated_user_library


@pytest.fixture
def sample_bib(tmp_path: Path) -> Path:
    """A writable copy of the sample bibliography in an isolated directory."""
    dst = tmp_path / "sample.bib"
    shutil.copy(FIXTURES / "sample.bib", dst)
    return dst
