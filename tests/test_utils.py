from pathlib import Path
from types import SimpleNamespace

from bibcc.utils.composer import compose_bibliographies
from bibcc.utils.librarian import cmd_rename, match_title_to_bib, parse_bib_entries, parse_library

BIB = """\
@inproceedings{Braced_2024,
  title = {A {Braced} Title},
  year = 2024,
}

@article{Quoted_2023,
  title = "A Quoted {Title}: With Subtitle",
  journal = {J},
}

@misc{NoTitle_2022,
  note = {x}
}
"""


def test_librarian_reads_braced_and_quoted_titles(tmp_path: Path):
    bib = tmp_path / "refs.bib"
    bib.write_text(BIB, encoding="utf-8")

    entries = parse_bib_entries(bib)

    assert list(entries) == ["Braced_2024", "Quoted_2023", "NoTitle_2022"]
    assert entries["Braced_2024"]["title_norm"] == "a braced title"
    assert entries["Quoted_2023"]["title_raw"] == "A Quoted {Title}: With Subtitle"
    assert entries["NoTitle_2022"]["title_raw"] == ""
    assert entries["Quoted_2023"]["raw"].startswith("@article{Quoted_2023,")
    assert entries["Quoted_2023"]["raw"].endswith("}")
    assert match_title_to_bib("a quoted title with subtitle", entries) == ["Quoted_2023"]


def test_librarian_rename_skips_titles_shared_by_several_entries(tmp_path: Path):
    bib = tmp_path / "refs.bib"
    bib.write_text(
        "@inproceedings{LwF_Li_ECCV2016, title = {Learning without Forgetting}}\n"
        "@article{LwF_Li_TPAMI2018, title = {Learning without Forgetting}}\n"
        "@article{Other_A_PR2024, title = {Another Title}}\n",
        encoding="utf-8",
    )
    pdfs = tmp_path / "pdfs"
    pdfs.mkdir()
    (pdfs / "Li - 2016 - Learning without Forgetting.pdf").write_bytes(b"")
    (pdfs / "A - 2024 - Another Title.pdf").write_bytes(b"")

    logs = []
    cmd_rename(bib, pdfs, dry_run=False, logger=SimpleNamespace(log=logs.append))

    assert sorted(p.name for p in pdfs.iterdir()) == [
        "Li - 2016 - Learning without Forgetting.pdf",
        "Other_A_PR2024.pdf",
    ]
    assert any("LwF_Li_ECCV2016, LwF_Li_TPAMI2018" in line for line in logs)
    report = (tmp_path / ".bibcc" / "refs.bib" / "rename_report.txt").read_text(encoding="utf-8")
    assert "1 ambiguous" in report


def test_librarian_library_listing_encodings(tmp_path: Path):
    listing = "Key_A_2024.pdf\r\nKey_B_2023.PDF\r\nnotes.txt\r\n"
    expected = {"Key_A_2024", "Key_B_2023"}
    for name, data in {
        "utf8.txt": listing.encode("utf-8"),
        "utf8bom.txt": listing.encode("utf-8-sig"),
        "utf16.txt": listing.encode("utf-16"),
        "utf16le.txt": listing.encode("utf-16-le"),
        "utf16be.txt": listing.encode("utf-16-be"),
    }.items():
        path = tmp_path / name
        path.write_bytes(data)
        assert parse_library(path) == expected, name


def test_composer_skips_its_output_and_bibcc_folders(tmp_path: Path):
    root = tmp_path / "bibs"
    (root / "sub").mkdir(parents=True)
    (root / ".bibcc").mkdir()
    (root / "a.bib").write_text("@misc{A, title={A}}\n", encoding="utf-8")
    (root / "sub" / "b.bib").write_text("@misc{B, title={B}}\n@misc{A, title={A2}}\n", encoding="utf-8")
    (root / ".bibcc" / "report.bib").write_text("@misc{R, title={R}}\n", encoding="utf-8")
    output = root / "all.bib"
    output.write_text("@misc{Stale, title={old output}}\n", encoding="utf-8")

    logs = []
    stats = compose_bibliographies(root, output, log=logs.append)

    assert (stats.file_count, stats.entry_count, stats.duplicate_count) == (2, 3, 1)
    text = output.read_text(encoding="utf-8")
    assert "% === source: a.bib ===" in text
    assert "% === source: sub/b.bib ===" in text
    assert "Stale" not in text and "@misc{R," not in text

    # Running again must not pick up the composed file itself.
    again = compose_bibliographies(root, output, log=logs.append)
    assert again.file_count == 2


def _librarian(argv, monkeypatch, tmp_path):
    from bibcc.cli import main

    monkeypatch.chdir(tmp_path)
    try:
        main(["librarian", *argv])
    except SystemExit as e:
        return e.code
    raise AssertionError("librarian did not exit")


def test_librarian_missing_reads_several_bibs_and_a_pdf_directory(tmp_path: Path, monkeypatch):
    bib = tmp_path / "bib"
    (bib / "sub").mkdir(parents=True)
    (bib / ".bibcc").mkdir()
    (bib / "a.bib").write_text("@misc{Has_A_2024, title={Has}}\n@misc{Lacks_A_2024, title={Lacks}}\n")
    (bib / "sub" / "b.bib").write_text("@misc{Has_A_2024, title={Has}}\n@misc{Empty_B_2025,\n}\n")
    (bib / ".bibcc" / "x.bib").write_text("@misc{Hidden_X_2020, title={Hidden}}\n")
    extra = tmp_path / "extra.bib"
    extra.write_text("@misc{Spaced_C_2023, title={Spaced}}\n")
    pdfs = tmp_path / "pdfs"
    (pdfs / "2024").mkdir(parents=True)
    (pdfs / "2024" / "Has_A_2024.pdf").write_bytes(b"")
    (pdfs / "Spaced_C_2023.PDF").write_bytes(b"")
    (pdfs / "Stray_D_2022.pdf").write_bytes(b"")

    assert _librarian(["missing", "bib", "extra.bib", "pdfs"], monkeypatch, tmp_path) == 1
    report = (tmp_path / ".bibcc" / "bib" / "missing_pdfs.txt").read_text()
    assert "% Missing PDFs: 2 / 4 entries" in report
    assert "Lacks_A_2024" in report and "Empty_B_2025" in report
    assert "Hidden_X_2020" not in report and "Has_A_2024" not in report
    assert f"% === source: {Path('bib') / 'sub' / 'b.bib'} ===" in report

    assert _librarian(["missing", "bib", "extra.bib", "pdfs", "--skip-empty"], monkeypatch, tmp_path) == 1
    report = (tmp_path / ".bibcc" / "bib" / "missing_pdfs.txt").read_text()
    assert "% Missing PDFs: 1 / 3 entries" in report and "Empty_B_2025" not in report

    (pdfs / "Lacks_A_2024.pdf").write_bytes(b"")
    assert _librarian(["missing", "bib", "extra.bib", "pdfs", "--skip-empty"], monkeypatch, tmp_path) == 0

    assert _librarian(["extra", "bib", "extra.bib", "pdfs"], monkeypatch, tmp_path) == 0
    assert (tmp_path / ".bibcc" / "bib" / "extra_pdfs.txt").read_text().splitlines()[-1] == "Stray_D_2022.pdf"


def test_librarian_missing_still_reads_a_listing(tmp_path: Path, monkeypatch):
    (tmp_path / "refs.bib").write_text(BIB)
    (tmp_path / "papers.txt").write_text("Braced_2024.pdf\nQuoted_2023.pdf\nNoTitle_2022.pdf\n")
    assert _librarian(["missing", "refs.bib", "papers.txt"], monkeypatch, tmp_path) == 0
    assert "% Missing PDFs: 0 / 3" in (tmp_path / ".bibcc" / "refs.bib" / "missing_pdfs.txt").read_text()


def test_librarian_missing_usage_errors(tmp_path: Path, monkeypatch):
    (tmp_path / "refs.bib").write_text(BIB)
    (tmp_path / "other.bib").write_text(BIB)
    assert _librarian(["missing", "refs.bib", "no-such-dir"], monkeypatch, tmp_path) == 2
    assert _librarian(["missing", "nope.bib", "refs.bib", "pdfs"], monkeypatch, tmp_path) == 2
    # Forgetting the library: the last .bib file is not taken as a listing.
    assert _librarian(["missing", "refs.bib", "other.bib"], monkeypatch, tmp_path) == 2
