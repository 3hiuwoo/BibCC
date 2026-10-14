from pathlib import Path

from bibcc.cli import main
from bibcc.logging_utils import OUTPUT_DIR_NAME, migrate_legacy_reports, report_dir


def test_report_dir_is_per_input_next_to_it(tmp_path: Path):
    bib = tmp_path / "refs" / "a.bib"
    bib.parent.mkdir()
    bib.write_text("")
    assert report_dir(bib) == bib.parent.resolve() / OUTPUT_DIR_NAME / "a.bib"
    assert report_dir(bib).is_dir()


def test_report_dir_of_a_directory_sits_next_to_it(tmp_path: Path):
    (tmp_path / "bib").mkdir()
    assert report_dir(tmp_path / "bib") == tmp_path.resolve() / OUTPUT_DIR_NAME / "bib"


def test_report_dir_override_takes_the_place_of_bibcc(tmp_path: Path):
    override = tmp_path / "elsewhere"
    assert report_dir(tmp_path / "a.bib", override) == override / "a.bib"
    assert (override / "a.bib").is_dir()


def test_report_dir_never_nests_bibcc(tmp_path: Path):
    staged = tmp_path / OUTPUT_DIR_NAME / "work" / "batch" / "retried.bib"
    staged.parent.mkdir(parents=True)
    staged.write_text("")
    out = report_dir(staged)
    assert out == staged.parent.resolve() / "reports" / "retried.bib"
    assert out.parts.count(OUTPUT_DIR_NAME) == 1


def test_report_dir_without_input_is_cwd_bibcc(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert report_dir() == tmp_path / OUTPUT_DIR_NAME


def test_check_writes_reports_and_logs_next_to_input(sample_bib: Path):
    main(["check", "missing", str(sample_bib), "--fields", "month"])
    out = sample_bib.parent / OUTPUT_DIR_NAME / "sample.bib"
    assert (out / "missing_fields.txt").exists()
    assert (out / "logs" / "checker.log").exists()
    assert "ISPC_Wang_CVPR2024" in (out / "missing_fields.txt").read_text()


def test_check_removes_a_stale_report_when_it_finds_nothing(sample_bib: Path):
    out = sample_bib.parent / OUTPUT_DIR_NAME / "sample.bib"
    out.mkdir(parents=True)
    (out / "missing_fields.txt").write_text("old findings\n")
    main(["check", "missing", str(sample_bib), "--fields", "title"])
    assert not (out / "missing_fields.txt").exists()


def test_complete_dry_run_writes_reports_next_to_input(sample_bib: Path):
    before = sample_bib.read_bytes()
    main(["complete", str(sample_bib)])
    out = sample_bib.parent / OUTPUT_DIR_NAME / "sample.bib"
    assert (out / "incomplete_entries.txt").exists()
    assert sample_bib.read_bytes() == before


def test_legacy_flat_reports_are_moved_not_deleted(tmp_path: Path):
    bib = tmp_path / "refs.bib"
    bib.write_text("")
    legacy = tmp_path / OUTPUT_DIR_NAME
    (legacy / "logs").mkdir(parents=True)
    (legacy / "refs.bib.missing_venues.yaml").write_text("filled in by hand\n")
    (legacy / "refs.bib.add.txt").write_text("add: identifier\n")
    (legacy / "logs" / "refs.bib.adder.log").write_text("log\n")
    (legacy / "other.bib.add.txt").write_text("someone else's\n")
    (legacy / "refs.bib.notes.txt").write_text("not a BibCC report\n")

    moved = migrate_legacy_reports(bib)

    new = legacy / "refs.bib"
    assert len(moved) == 3
    assert (new / "missing_venues.yaml").read_text() == "filled in by hand\n"
    assert (new / "add.txt").exists()
    assert (new / "logs" / "adder.log").exists()
    assert not (legacy / "refs.bib.add.txt").exists()
    assert not (legacy / "logs").exists()
    assert (legacy / "other.bib.add.txt").exists()
    assert (legacy / "refs.bib.notes.txt").exists()


def test_migration_keeps_an_old_file_whose_new_name_is_taken(tmp_path: Path):
    bib = tmp_path / "refs.bib"
    bib.write_text("")
    legacy = tmp_path / OUTPUT_DIR_NAME
    (legacy / "refs.bib").mkdir(parents=True)
    (legacy / "refs.bib" / "add.txt").write_text("new\n")
    (legacy / "refs.bib.add.txt").write_text("old\n")
    assert migrate_legacy_reports(bib) == []
    assert (legacy / "refs.bib.add.txt").read_text() == "old\n"
    assert (legacy / "refs.bib" / "add.txt").read_text() == "new\n"


def test_commands_migrate_on_first_run(sample_bib: Path):
    legacy = sample_bib.parent / OUTPUT_DIR_NAME
    legacy.mkdir()
    (legacy / "sample.bib.missing_fields.txt").write_text("old\n")
    main(["check", "missing", str(sample_bib), "--fields", "title"])
    assert not (legacy / "sample.bib.missing_fields.txt").exists()
    log = (legacy / "sample.bib" / "logs" / "checker.log").read_text()
    assert "Moved 1 reports" in log
