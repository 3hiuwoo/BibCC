import shutil
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def sample_bib(tmp_path: Path) -> Path:
    """A writable copy of the sample bibliography in an isolated directory."""
    dst = tmp_path / "sample.bib"
    shutil.copy(FIXTURES / "sample.bib", dst)
    return dst
