from pathlib import Path

from bibcc.utils.composer import compose_bibliographies
from bibcc.utils.librarian import match_title_to_bib, parse_bib_entries, parse_library

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
    assert match_title_to_bib("a quoted title with subtitle", entries) == "Quoted_2023"


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
