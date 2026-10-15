"""Protected terms: the user and project terms files, and the terms command."""

from pathlib import Path

import pytest

from bibcc import sources
from bibcc.cli import main
from bibcc.terms import (
    PROJECT_TERMS_NAME,
    TermsNotFound,
    add_terms,
    all_terms,
    find_project_terms,
    parse_terms,
    read_terms,
    terms_path,
    user_terms_path,
)

EXAMPLE_TERMS = Path(__file__).parent.parent / "examples" / "terms"


def _terms(*argv: str) -> int:
    with pytest.raises(SystemExit) as exc:
        main(["terms", *argv])
    return exc.value.code


@pytest.fixture
def project(tmp_path: Path) -> Path:
    folder = tmp_path / "paper"
    (folder / "bib").mkdir(parents=True)
    (folder / "bib" / "refs.bib").write_text("@article{k, title = {T}, year = {2024}}\n")
    return folder


def test_user_terms_default_to_xdg_config_and_env(isolated_user_library: Path, monkeypatch, tmp_path: Path):
    assert user_terms_path() == isolated_user_library.parent / "terms.txt"
    monkeypatch.setenv("BIBCC_TERMS", str(tmp_path / "mine.txt"))
    assert user_terms_path() == tmp_path / "mine.txt"


def test_parse_and_add_ignore_comments_blanks_and_case(tmp_path: Path):
    assert parse_terms("# c\nCLIP\n\n  LoRA \nclip\n") == ["CLIP", "LoRA"]
    path = tmp_path / "t.txt"
    assert add_terms(path, ["CLIP", "clip", "ViT"]) == ["CLIP", "ViT"]
    assert add_terms(path, ["vit", "SD-LoRA"]) == ["SD-LoRA"]
    assert read_terms(path) == ["CLIP", "ViT", "SD-LoRA"]
    assert path.read_text().startswith("# Protected terms")


def test_project_terms_are_found_upward_and_created_next_to_the_library(project: Path, monkeypatch):
    bib = project / "bib" / "refs.bib"
    with pytest.raises(TermsNotFound):
        terms_path("project", start=bib)
    monkeypatch.chdir(project / "bib")
    assert terms_path("project", start=bib, create=True) == project / "bib" / PROJECT_TERMS_NAME
    (project / ".bibcc-venues.yaml").write_text("journals: []\n")
    assert terms_path("project", start=bib, create=True) == project / PROJECT_TERMS_NAME
    add_terms(project / PROJECT_TERMS_NAME, ["CIP-Net"])
    assert find_project_terms(bib) == project / PROJECT_TERMS_NAME
    add_terms(user_terms_path(), ["cip-net", "LoRA"])
    assert all_terms(bib) == ["cip-net", "LoRA"]  # user first; duplicates dropped


def test_terms_add_where_and_list(project: Path, monkeypatch, capsys):
    monkeypatch.chdir(project)
    assert _terms("add", "CIP-Net", "Transformer-XL") == 0
    assert _terms("add", "SD-LoRA", "--scope", "project") == 0
    assert read_terms(user_terms_path()) == ["CIP-Net", "Transformer-XL"]
    assert read_terms(project / PROJECT_TERMS_NAME) == ["SD-LoRA"]
    capsys.readouterr()
    assert _terms("list") == 0
    assert capsys.readouterr().out.splitlines() == [
        "CIP-Net\tuser", "Transformer-XL\tuser", "SD-LoRA\tproject",
    ]
    assert _terms("where", str(project / "bib" / "refs.bib")) == 0
    out = capsys.readouterr().out
    assert "(2 terms)" in out and "(1 terms)" in out


def test_terms_import_example_by_name_and_dry_run(isolated_user_library: Path, tmp_path: Path, capsys):
    example = read_terms(EXAMPLE_TERMS / "miaa.txt")
    assert "CLIP" in example and "NeurIPS" in example
    assert _terms("import", "miaa", "--dry-run") == 0
    assert not user_terms_path().exists()
    assert _terms("import", "miaa") == 0
    assert read_terms(user_terms_path()) == example
    assert _terms("import", "miaa") == 0
    assert "Nothing new to import" in capsys.readouterr().out
    target = tmp_path / "other.txt"
    assert _terms("import", str(EXAMPLE_TERMS / "miaa.txt"), "--file", str(target)) == 0
    assert read_terms(target) == example


def test_terms_import_downloads_unknown_names(isolated_user_library: Path, monkeypatch):
    requested = []

    def fake_fetch(url, **_):
        requested.append(url)
        return ("RemoteNet\n", None) if url.endswith("/remote.txt") else (None, "HTTP 404: Not Found")

    monkeypatch.setattr(sources, "fetch_url", fake_fetch)
    assert _terms("import", "remote") == 0
    assert requested[-1].endswith("/examples/terms/remote.txt")
    assert read_terms(user_terms_path()) == ["RemoteNet"]
    assert _terms("import", "no-such-list") == 1


def test_terms_examples_lists_the_checkout(capsys):
    assert _terms("examples") == 0
    assert "miaa" in capsys.readouterr().out
