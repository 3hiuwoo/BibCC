from pathlib import Path

from bibcc.cli import main
from bibcc.logging_utils import OUTPUT_DIR_NAME, get_output_dir


def test_output_dir_sits_next_to_input(tmp_path: Path):
    bib = tmp_path / "refs" / "a.bib"
    bib.parent.mkdir()
    bib.write_text("")
    assert get_output_dir(bib) == bib.parent.resolve() / OUTPUT_DIR_NAME
    assert (bib.parent / OUTPUT_DIR_NAME).is_dir()


def test_output_dir_override_wins(tmp_path: Path):
    override = tmp_path / "elsewhere"
    assert get_output_dir(tmp_path / "a.bib", override) == override
    assert override.is_dir()


def test_check_writes_reports_and_logs_next_to_input(sample_bib: Path):
    main(["check", str(sample_bib), "--fields", "month", "--check-keys"])
    out = sample_bib.parent / OUTPUT_DIR_NAME
    assert (out / "sample.bib.missing_fields.txt").exists()
    assert (out / "logs" / "sample.bib.checker.log").exists()
    assert "ISPC_Wang_CVPR2024" in (out / "sample.bib.missing_fields.txt").read_text()


def test_complete_dry_run_writes_reports_next_to_input(sample_bib: Path):
    before = sample_bib.read_bytes()
    main(["complete", str(sample_bib)])
    out = sample_bib.parent / OUTPUT_DIR_NAME
    assert (out / "sample.bib.incomplete_entries.txt").exists()
    assert sample_bib.read_bytes() == before
