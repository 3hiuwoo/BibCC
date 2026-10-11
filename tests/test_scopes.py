"""User and project venue libraries: where they are, how they merge, and which one is written."""

from pathlib import Path

import pytest
import yaml

from bibcc import sources
from bibcc.cli import main
from bibcc.venues import (
    JOURNAL,
    PROJECT_LIBRARY_NAME,
    LibraryNotFound,
    Venue,
    VenueLibrary,
    find_project_library,
    load_library,
    open_library,
    user_library_path,
)
from conftest import EXAMPLE_VENUES, MIAA_VENUES

BIB = """\
@article{X_Doe_JT2024,
  title = {A Title},
  author = {Doe, Jane},
  journal = {Journal of Tests},
  year = {2024},
}
"""


def _write_library(path: Path, **journals: dict) -> Path:
    lib = VenueLibrary(path=path)
    for name, fields in journals.items():
        lib.upsert(Venue(JOURNAL, name.replace("_", " "), dict(fields)))
    lib.save()
    return path


def _journal(path: Path, name: str = "Journal of Tests") -> dict:
    return VenueLibrary.load(path).find_exact(JOURNAL, name).fields


@pytest.fixture
def project(tmp_path: Path) -> Path:
    """A project folder with a .bib file two levels down."""
    bib = tmp_path / "paper" / "bib" / "refs.bib"
    bib.parent.mkdir(parents=True)
    bib.write_text(BIB)
    return tmp_path / "paper"


# ------------------------------------------------------------- locations


def test_user_library_defaults_to_xdg_config(isolated_user_library: Path):
    assert user_library_path() == isolated_user_library
    assert isolated_user_library.parts[-2:] == ("bibcc", "venues.yaml")


def test_user_library_env_var_wins(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("BIBCC_VENUES", str(tmp_path / "lab.yaml"))
    assert user_library_path() == tmp_path / "lab.yaml"


def test_project_library_is_found_from_the_bib_file_upward(project: Path):
    assert find_project_library(project / "bib" / "refs.bib") is None
    lib = _write_library(project / PROJECT_LIBRARY_NAME)
    assert find_project_library(project / "bib" / "refs.bib") == lib.resolve()
    assert find_project_library(project / "bib") == lib.resolve()
    assert find_project_library(project / "bib" / "not-yet.bib") == lib.resolve()


def test_no_library_is_shipped_with_the_package():
    package = Path(__import__("bibcc").__file__).parent
    assert not list(package.rglob("*.yaml"))


def test_example_libraries_load_and_are_in_canonical_form(tmp_path: Path):
    examples = sorted(EXAMPLE_VENUES.glob("*.yaml"))
    assert MIAA_VENUES in examples
    for path in examples:
        lib = VenueLibrary.load(path)
        assert len(lib), f"{path.name} has no records"
        # Saving rewrites in sorted, canonical form; examples are kept that way so diffs stay small.
        assert lib.save(tmp_path / path.name).read_text() == path.read_text(), f"{path.name} is not canonical"


# --------------------------------------------------------------- merging


def test_project_values_win_and_fields_of_both_are_kept(isolated_user_library: Path, project: Path):
    _write_library(isolated_user_library, Journal_of_Tests={"publisher": "User Pub", "issn": "1111-1111"},
                   Only_User={"publisher": "U"})
    _write_library(project / PROJECT_LIBRARY_NAME, Journal_of_Tests={"publisher": "Project Pub", "address": "Here"},
                   Only_Project={"publisher": "P"})
    lib = load_library(start=project / "bib" / "refs.bib")
    fields = lib.find_exact(JOURNAL, "Journal of Tests").fields
    assert fields == {"publisher": "Project Pub", "issn": "1111-1111", "address": "Here"}
    assert lib.find_exact(JOURNAL, "Only User") and lib.find_exact(JOURNAL, "Only Project")
    assert [(c.name, c.kept, c.other) for c in lib.overrides] == [("publisher", "Project Pub", "User Pub")]
    assert [s.scope for s in lib.sources] == ["user", "project"]
    assert "project overrides 1 user field" in lib.describe()


def test_merged_view_is_read_only(isolated_user_library: Path, project: Path):
    _write_library(isolated_user_library, Journal_of_Tests={"publisher": "U"})
    _write_library(project / PROJECT_LIBRARY_NAME, Journal_of_Tests={"publisher": "P"})
    lib = load_library(start=project)
    with pytest.raises(ValueError, match="read-only"):
        lib.save()
    assert _journal(isolated_user_library) == {"publisher": "U"}


def test_venues_file_replaces_both_scopes(isolated_user_library: Path, project: Path, tmp_path: Path):
    _write_library(isolated_user_library, Only_User={"publisher": "U"})
    _write_library(project / PROJECT_LIBRARY_NAME, Only_Project={"publisher": "P"})
    other = _write_library(tmp_path / "other.yaml", Only_Other={"publisher": "O"})
    lib = load_library(other, start=project)
    assert [v.name for v in lib.journals] == ["Only Other"]
    assert lib.path == other


def test_empty_library_explains_how_to_start(isolated_user_library: Path, project: Path):
    text = load_library(start=project).describe()
    assert "not created yet" in text and "bibcc venues examples" in text


def test_open_project_library_requires_one_unless_creating(project: Path, monkeypatch):
    with pytest.raises(LibraryNotFound, match="bibcc venues init --scope project"):
        open_library("project", start=project / "bib" / "refs.bib")
    monkeypatch.chdir(project)
    created = open_library("project", start=project / "bib", create=True)
    assert created.path == project / PROJECT_LIBRARY_NAME and not created.path.exists()


# ------------------------------------------------------- complete writes


def _missing_yaml(bib: Path, name: str = "New Journal") -> None:
    path = bib.parent / ".bibcc" / bib.name / "missing_venues.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"journals:\n  - name: {name}\n    fields:\n      publisher: Fresh\n")


def test_complete_uses_project_values(isolated_user_library: Path, project: Path, tmp_path: Path):
    _write_library(isolated_user_library, Journal_of_Tests={"publisher": "User Pub", "issn": "1111-1111"})
    _write_library(project / PROJECT_LIBRARY_NAME, Journal_of_Tests={"publisher": "Project Pub"})
    bib = project / "bib" / "refs.bib"
    out = tmp_path / "out.bib"
    main(["complete", str(bib), "--output", str(out)])
    text = out.read_text()
    assert "Project Pub" in text and "1111-1111" in text and "User Pub" not in text


def test_update_venues_writes_the_user_library_by_default(isolated_user_library: Path, project: Path, capsys):
    project_lib = _write_library(project / PROJECT_LIBRARY_NAME, Journal_of_Tests={"publisher": "P"})
    before = project_lib.read_text()
    bib = project / "bib" / "refs.bib"
    _missing_yaml(bib)
    main(["complete", str(bib), "--update-venues"])
    assert _journal(isolated_user_library, "New Journal") == {"publisher": "Fresh"}
    assert project_lib.read_text() == before
    assert f"into the user library {isolated_user_library}" in capsys.readouterr().out


def test_update_venues_scope_project_writes_only_the_project(isolated_user_library: Path, project: Path, capsys):
    project_lib = _write_library(project / PROJECT_LIBRARY_NAME, Journal_of_Tests={"publisher": "P"})
    bib = project / "bib" / "refs.bib"
    _missing_yaml(bib)
    main(["complete", str(bib), "--update-venues", "--scope", "project"])
    assert _journal(project_lib, "New Journal") == {"publisher": "Fresh"}
    assert not isolated_user_library.exists()
    assert "into the project library" in capsys.readouterr().out


def test_update_venues_scope_project_without_project_library_fails(project: Path, isolated_user_library: Path):
    bib = project / "bib" / "refs.bib"
    _missing_yaml(bib)
    with pytest.raises(SystemExit) as exc:
        main(["complete", str(bib), "--update-venues", "--scope", "project"])
    assert exc.value.code == 1
    assert not isolated_user_library.exists()


@pytest.mark.parametrize("extra", [["--scope", "user"], ["--update-venues", "--scope", "user", "--venues", "x.yaml"]])
def test_scope_usage_errors(project: Path, extra):
    with pytest.raises(SystemExit) as exc:
        main(["complete", str(project / "bib" / "refs.bib"), *extra])
    assert exc.value.code == 2


# ------------------------------------------------------- venues command


def _venues(*argv: str) -> int:
    with pytest.raises(SystemExit) as exc:
        main(["venues", *argv])
    return exc.value.code


def test_venues_init_user_and_project(isolated_user_library: Path, project: Path, monkeypatch, capsys):
    assert _venues("init") == 0
    assert isolated_user_library.exists() and not len(VenueLibrary.load(isolated_user_library))
    monkeypatch.chdir(project)
    assert _venues("init", "--scope", "project") == 0
    assert (project / PROJECT_LIBRARY_NAME).exists()
    _write_library(project / PROJECT_LIBRARY_NAME, Kept={"publisher": "K"})
    assert _venues("init", "--scope", "project") == 0
    assert "already exists" in capsys.readouterr().out
    assert _journal(project / PROJECT_LIBRARY_NAME, "Kept") == {"publisher": "K"}


def test_venues_import_example_by_name_into_user_library(isolated_user_library: Path):
    assert _venues("import", "miaa") == 0
    imported = VenueLibrary.load(isolated_user_library)
    example = VenueLibrary.load(MIAA_VENUES)
    assert (len(imported.journals), len(imported.proceedings)) == (len(example.journals), len(example.proceedings))


def test_venues_import_keeps_your_values_unless_overwrite(isolated_user_library: Path, tmp_path: Path, capsys):
    _write_library(isolated_user_library, Journal_of_Tests={"publisher": "Mine"})
    source = _write_library(tmp_path / "shared.yaml", Journal_of_Tests={"publisher": "Theirs", "issn": "2222-2222"})
    assert _venues("import", str(source)) == 0
    assert _journal(isolated_user_library) == {"publisher": "Mine", "issn": "2222-2222"}
    assert "kept 'Mine' (incoming 'Theirs')" in capsys.readouterr().out
    assert _venues("import", str(source), "--overwrite") == 0
    assert _journal(isolated_user_library) == {"publisher": "Theirs", "issn": "2222-2222"}


def test_venues_import_dry_run_and_explicit_file(isolated_user_library: Path, tmp_path: Path):
    source = _write_library(tmp_path / "shared.yaml", Journal_of_Tests={"publisher": "Theirs"})
    assert _venues("import", str(source), "--dry-run") == 0
    assert not isolated_user_library.exists()
    target = tmp_path / "target.yaml"
    assert _venues("import", str(source), "--venues", str(target)) == 0
    assert _journal(target) == {"publisher": "Theirs"} and not isolated_user_library.exists()


def test_venues_import_into_project_creates_it_in_cwd(isolated_user_library: Path, project: Path, monkeypatch,
                                                      tmp_path: Path):
    source = _write_library(tmp_path / "shared.yaml", Journal_of_Tests={"publisher": "Theirs"})
    monkeypatch.chdir(project)
    assert _venues("import", str(source), "--scope", "project") == 0
    assert _journal(project / PROJECT_LIBRARY_NAME) == {"publisher": "Theirs"}
    assert not isolated_user_library.exists()


def test_venues_import_downloads_unknown_names_and_urls(isolated_user_library: Path, monkeypatch):
    shared = "journals:\n  - name: Remote Journal\n    fields: {publisher: R}\n"
    requested = []

    def fake_fetch(url, **_):
        requested.append(url)
        return (shared, None) if url.endswith("/remote.yaml") else (None, "HTTP 404: Not Found")

    monkeypatch.setattr(sources, "fetch_url", fake_fetch)
    assert _venues("import", "remote") == 0
    assert requested[-1].endswith("/examples/venues/remote.yaml")
    assert _journal(isolated_user_library, "Remote Journal") == {"publisher": "R"}
    assert _venues("import", "https://example.org/remote.yaml", "--dry-run") == 0
    assert _venues("import", "no-such-library") == 1


def test_venues_where_names_every_scope(isolated_user_library: Path, project: Path, capsys):
    _write_library(isolated_user_library, Journal_of_Tests={"publisher": "U"})
    project_lib = _write_library(project / PROJECT_LIBRARY_NAME, Journal_of_Tests={"publisher": "P"})
    assert _venues("where", str(project / "bib" / "refs.bib")) == 0
    out = capsys.readouterr().out
    assert str(isolated_user_library) in out and str(project_lib.resolve()) in out
    assert "project 'P' (user 'U')" in out and "--scope project" in out


def test_venues_examples_lists_the_checkout(capsys):
    assert _venues("examples") == 0
    assert "miaa" in capsys.readouterr().out


def test_check_venues_checks_each_scope(isolated_user_library: Path, project: Path, monkeypatch, capsys):
    _write_library(isolated_user_library, Journal_of_Tests={"publisher": "U"})
    _write_library(project / PROJECT_LIBRARY_NAME, Other={"publisher": "P"})
    monkeypatch.chdir(project)
    main(["check", "--check-venues"])
    out = capsys.readouterr().out
    assert "User library" in out and "Project library" in out


def test_update_hint_names_scope_project_only_when_there_is_a_project_library(project: Path):
    from bibcc.missing_venues import update_command

    bib = project / "bib" / "refs.bib"
    assert update_command(bib) == f"bibcc complete {bib} --in-place --update-venues"
    (project / PROJECT_LIBRARY_NAME).write_text("journals: []\nproceedings: []\n")
    assert update_command(bib).endswith("--update-venues --scope project")


def test_complete_yaml_hint_names_scope_project(isolated_user_library: Path, project: Path):
    (project / PROJECT_LIBRARY_NAME).write_text("journals: []\nproceedings: []\n")
    bib = project / "bib" / "refs.bib"
    bib.write_text("@article{A,\n  title = {T},\n  journal = {Unknown Journal of Things},\n  year = {2024}\n}\n")
    main(["complete", str(bib)])
    header = (bib.parent / ".bibcc" / "refs.bib" / "missing_venues.yaml").read_text()
    assert "--update-venues --scope project" in header


def test_missing_venues_yaml_documents_the_library_schema():
    # The fill-in YAML uses the library schema; the example in the repo must stay loadable.
    data = yaml.safe_load((Path(__file__).parent.parent / "missing_venues.example.yaml").read_text())
    assert set(data) <= {"journals", "proceedings"}
