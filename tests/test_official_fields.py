from pathlib import Path

import bibtexparser
import pytest

from bibcc import official, sources
from bibcc.checkers.official_fields import check_official_fields
from bibcc.cli import main
from bibcc.venues import VenueLibrary
from test_add import XPLORE_EXPORT, FakeWeb, _fixture

ICML = "Proceedings of the 41st International Conference on Machine Learning"
CVPR = "2025 IEEE/CVF Conference on Computer Vision and Pattern Recognition (CVPR)"
CVPR_TITLE = "A Unified, Resilient, and Explainable Adversarial Patch Detector"

REFS = f"""\
@inproceedings{{A_Doe_ICML2024,
  title = {{Alpha Learning}},
  author = {{Doe, Jane and Mi{{\\l}}o{{\\'s}}, Piotr}},
  booktitle = {{{ICML}}},
  year = {{2024}},
  pages = {{1--10}},
  keywords = {{kept on purpose}},
  citation = {{4}}
}}

@inproceedings{{B_Li_ICML2024,
  title = {{Beta Learning}},
  author = {{Li, Wei}},
  booktitle = {{{ICML}}},
  year = {{2024}},
  doi = {{10.5555/beta}},
  volume = {{235}},
  note = {{oral}}
}}

@inproceedings{{C_Wu_ICML2024,
  title = {{Gamma Learning}},
  author = {{Wu, Lan}},
  booktitle = {{{ICML}}},
  year = {{2024}}
}}

@inproceedings{{D_Ng_ICML2024,
  title = {{Delta Learning}},
  author = {{Ng, Tom}},
  booktitle = {{{ICML}}},
  year = {{2024}}
}}

@misc{{E_Ho_arXiv2024,
  title = {{Epsilon Learning}},
  author = {{Ho, Ann}},
  year = {{2024}},
  eprint = {{2401.00001}},
  archiveprefix = {{arXiv}}
}}
"""

EXPORTS = f"""\
% source: https://proceedings.mlr.press/v235/doe24a.html
@InProceedings{{pmlr-v235-doe24a,
  title = {{Alpha Learning*}},
  author = {{Doe, Jane and Mi\\l o\\'{{s}}, Piotr}},
  booktitle = {{{ICML}}},
  year = {{2024}},
  pages = {{1--11}},
  volume = {{235}},
  publisher = {{PMLR}},
  abstract = {{We learn alpha.}}
}}

@InProceedings{{pmlr-v235-li24b,
  title = {{Beta Learning}},
  author = {{Li, Wei}},
  booktitle = {{{ICML}}},
  year = {{2024}},
  volume = {{235}},
  publisher = {{PMLR}},
  doi = {{10.5555/BETA}},
  abstract = {{We learn beta.}}
}}

@InProceedings{{C_Wu_ICML2024,
  title = {{Another Paper Entirely}},
  author = {{Wu, Lan}},
  booktitle = {{{ICML}}},
  year = {{2024}}
}}
"""

LIBRARY = f"""\
proceedings:
- name: {ICML}
  year: '2024'
  fields: {{venue: 'Vienna, Austria'}}
"""


@pytest.fixture
def web(monkeypatch):
    fake = FakeWeb({})
    monkeypatch.setattr(sources, "fetch_url", fake)
    official.clear_cache()
    yield fake
    official.clear_cache()


def _write(tmp_path: Path) -> Path:
    bib = tmp_path / "refs.bib"
    bib.write_text(REFS, encoding="utf-8")
    exports = tmp_path / "exports"
    exports.mkdir()
    (exports / "icml.bib").write_text(EXPORTS, encoding="utf-8")
    return bib


def _entries(text: str):
    parser = bibtexparser.bparser.BibTexParser(common_strings=True)
    return {e["ID"]: e for e in bibtexparser.loads(text, parser=parser).entries}


def test_check_official_fields_with_local_exports(tmp_path: Path, web):
    bib = _write(tmp_path)
    original = bib.read_text()
    logs = []
    result = check_official_fields(
        str(bib), VenueLibrary.loads(LIBRARY), local=[tmp_path / "exports"], offline=True, log=logs.append,
    )

    assert web.calls == []
    assert bib.read_text() == original
    assert result.checked == 2 and result.skipped == 1 and result.unmatched == 1
    assert [r[:5] for r in result.fields] == [
        ("A_Doe_ICML2024", "abstract", "upstream_only", "", "We learn alpha."),
        ("A_Doe_ICML2024", "keywords", "local_only", "kept on purpose", ""),
        ("A_Doe_ICML2024", "pages", "differs", "1--10", "1--11"),
        ("A_Doe_ICML2024", "publisher", "upstream_only", "", "PMLR"),
        ("A_Doe_ICML2024", "volume", "upstream_only", "", "235"),
        ("B_Li_ICML2024", "abstract", "upstream_only", "", "We learn beta."),
        ("B_Li_ICML2024", "note", "local_only", "oral", ""),
        ("B_Li_ICML2024", "publisher", "upstream_only", "", "PMLR"),
    ]
    # Neither the `\l o` spelling nor the trailing `*` of the title counts.
    assert result.fields[0][5] == "local file icml.bib https://proceedings.mlr.press/v235/doe24a.html"
    assert result.strict_findings == 6
    # The citation key matched, but the title says it's another paper.
    assert result.unchecked == [
        ("C_Wu_ICML2024", "mismatch", "the official BibTeX is 'Another Paper Entirely'", "", "check"),
    ]

    venues = {(r[2], r[3]): r for r in result.venues}
    assert venues[("publisher", "entries_lack")] == (ICML, "2024", "publisher", "entries_lack", "2", "2",
                                                     "A_Doe_ICML2024, B_Li_ICML2024")
    assert venues[("volume", "entries_lack")][4:] == ("2", "1", "A_Doe_ICML2024")
    assert venues[("abstract", "entries_lack")][4:] == ("2", "2", "A_Doe_ICML2024, B_Li_ICML2024")
    assert venues[("publisher", "library_lacks")] == (ICML, "2024", "publisher", "library_lacks", "2", "",
                                                      "official 'PMLR'")
    assert "pages" not in {name for name, _ in venues}  # the entries disagree; nothing for the library
    log = "\n".join(logs)
    assert f"{ICML} (2024): 'abstract' is in the official BibTeX of 2 checked entries; 2 lack it" in log
    assert f"{ICML} (2024): the venue library lacks 'publisher', official 'PMLR'" in log


@pytest.mark.parametrize("publisher, expected", [
    ("PMLR", None),
    ("Other Press", ("library_differs", "library 'Other Press', official 'PMLR' (from family "
                     "Proceedings of the International Conference on Machine Learning)")),
])
def test_check_official_compares_the_family_fields(tmp_path: Path, web, publisher, expected):
    bib = _write(tmp_path)
    library = VenueLibrary.loads(LIBRARY + f"""\
families:
- name: Proceedings of the International Conference on Machine Learning
  acronym: ICML
  fields: {{publisher: '{publisher}'}}
""")
    result = check_official_fields(
        str(bib), library, local=[tmp_path / "exports"], offline=True, log=lambda _: None,
    )
    rows = [(r[3], r[6]) for r in result.venues if r[2] == "publisher" and r[3].startswith("library_")]
    assert rows == ([expected] if expected else [])


def test_check_official_apply_adds_named_fields_only(tmp_path: Path, web):
    bib = _write(tmp_path)
    result = check_official_fields(
        str(bib), VenueLibrary.loads(LIBRARY), local=[tmp_path / "exports"], offline=True,
        apply=["all"], log=lambda _: None,
    )
    entries = _entries(bib.read_text())
    assert result.applied == 5
    assert entries["A_Doe_ICML2024"]["volume"] == "235"
    assert entries["A_Doe_ICML2024"]["pages"] == "1--10"  # differences are reported, not replaced
    assert entries["A_Doe_ICML2024"]["abstract"] == "We learn alpha."
    assert entries["B_Li_ICML2024"]["abstract"] == "We learn beta."
    assert [r[:3] for r in result.fields] == [
        ("A_Doe_ICML2024", "keywords", "local_only"), ("A_Doe_ICML2024", "pages", "differs"),
        ("B_Li_ICML2024", "note", "local_only"),
    ]


def test_check_official_apply_named_field(tmp_path: Path, web):
    bib = _write(tmp_path)
    result = check_official_fields(
        str(bib), VenueLibrary.loads(LIBRARY), local=[tmp_path / "exports"], offline=True,
        apply=["abstract"], log=lambda _: None,
    )
    entries = _entries(bib.read_text())
    assert result.applied == 2
    assert entries["A_Doe_ICML2024"]["abstract"] == "We learn alpha."
    assert "volume" not in entries["A_Doe_ICML2024"]


def test_check_official_downloads_and_skips_interim(tmp_path: Path, web):
    import json

    items = {"message": {"items": [json.loads(_fixture("crossref_cvpr2025.json"))["message"]]}}
    web.routes.update({
        "query.bibliographic": (json.dumps(items), None),
        XPLORE_EXPORT + "11095062": (_fixture("xplore_11095062.json"), None),
    })
    bib = tmp_path / "refs.bib"
    bib.write_text(
        f"@inproceedings{{Unified_Kumar_CVPR2025,\n  title = {{{CVPR_TITLE}}},\n"
        f"  author = {{Kumar, Vishesh and Agarwal, Akshay}},\n  booktitle = {{{CVPR}}},\n"
        "  year = {2025},\n  pages = {30387--30397}\n}\n\n"
        "@inproceedings{Cvf_Wu_CVPR2025,\n  title = {T},\n"
        "  booktitle = {Proceedings of the Computer Vision and Pattern Recognition Conference (CVPR)},\n"
        "  year = {2025}\n}\n",
        encoding="utf-8",
    )
    library = VenueLibrary.loads(f"proceedings:\n- name: '{CVPR}'\n  year: '2025'\n"
                                 "  interim:\n    cvf: Proceedings of the Computer Vision and Pattern Recognition "
                                 "Conference (CVPR)\n  fields: {venue: 'Nashville, TN, USA'}\n")

    result = check_official_fields(str(bib), library, delay=0, log=lambda _: None)

    assert result.checked == 1 and result.skipped == 1
    assert [r[:4] for r in result.fields] == [
        ("Unified_Kumar_CVPR2025", "doi", "upstream_only", ""),
        ("Unified_Kumar_CVPR2025", "keywords", "upstream_only", ""),
    ]
    assert result.fields[0][4] == "10.1109/CVPR52734.2025.02829"
    assert result.fields[0][5].startswith("IEEE Xplore ")
    assert ("keywords", "entries_lack") in {(r[2], r[3]) for r in result.venues}


def test_check_official_reports_and_strict(tmp_path: Path, web, capsys):
    bib = _write(tmp_path)
    venues = tmp_path / "venues.yaml"
    venues.write_text(LIBRARY, encoding="utf-8")
    args = ["check", "official", str(bib), "--local", str(tmp_path / "exports"), "--offline",
            "--venues", str(venues)]

    with pytest.raises(SystemExit) as exc:
        main(args + ["--strict"])
    assert exc.value.code == 1
    reports = tmp_path / ".bibcc" / "refs.bib"
    fields = (reports / "official_fields.txt").read_text()
    assert fields.startswith("official fields: entry_id\tfield\tissue_type\tbib\tofficial\tsource\n")
    assert "A_Doe_ICML2024\tvolume\tupstream_only\t\t235\tlocal file icml.bib" in fields
    assert "C_Wu_ICML2024\tmismatch\t" in (reports / "official_unchecked.txt").read_text()
    assert f"{ICML}\t2024\tabstract\tentries_lack\t2\t2\tA_Doe_ICML2024, B_Li_ICML2024" in \
        (reports / "official_venues.txt").read_text()
    assert "1 entries match no --local entry" in capsys.readouterr().out

    # With only local_only findings left, --strict passes.
    main(args + ["--apply", "all,pages", "--ids", "B_Li_ICML2024"])
    main(args + ["--strict", "--ids", "B_Li_ICML2024"])
    assert "B_Li_ICML2024\tnote\tlocal_only\toral" in (reports / "official_fields.txt").read_text()


def test_check_official_learns_venue_schemas(tmp_path: Path, web):
    bib = _write(tmp_path)
    venues = tmp_path / "venues.yaml"
    venues.write_text(LIBRARY, encoding="utf-8")
    args = ["check", "official", str(bib), "--local", str(tmp_path / "exports"), "--offline",
            "--venues", str(venues)]

    result = check_official_fields(
        str(bib), VenueLibrary.loads(LIBRARY), local=[tmp_path / "exports"], offline=True, log=lambda _: None,
    )
    (proposal,) = result.proposals
    assert (proposal.level, proposal.fields) == ("family", ["abstract", "volume"])
    family = "Proceedings of the International Conference on Machine Learning"
    assert (family, "", "entry_fields", "schema_lacks", "2", "",
            "no family record yet; official BibTeX (2024): abstract, volume") in result.venues

    main(args + ["--learn"])
    library = VenueLibrary.load(venues)
    (learned,) = library.families
    assert (learned.name, learned.acronym, learned.entry_fields) == (family, "ICML", ["abstract", "volume"])
    assert learned.learned_from.startswith("official BibTeX of 2 entries (2024), ")

    result = check_official_fields(str(bib), library, local=[tmp_path / "exports"], offline=True,
                                   log=lambda _: None)
    assert result.proposals == []
    assert not [r for r in result.venues if r[2] == "entry_fields"]


def test_check_official_never_proposes_a_journal_month(tmp_path: Path, web):
    bib = tmp_path / "refs.bib"
    bib.write_text("@article{J_Doe_IJCV2026,\n  title = {Journal Paper},\n  author = {Doe, Jane},\n"
                   "  journal = {International Journal of Computer Vision},\n  year = {2026}\n}\n")
    exports = tmp_path / "exports"
    exports.mkdir()
    (exports / "J_Doe_IJCV2026.bib").write_text(
        "@article{x,\n  title = {Journal Paper},\n  author = {Doe, Jane},\n"
        "  journal = {International Journal of Computer Vision},\n  year = {2026},\n  month = sep,\n"
        "  publisher = {Springer}\n}\n")
    library = VenueLibrary.loads("journals:\n- name: International Journal of Computer Vision\n  fields: {}\n")
    result = check_official_fields(str(bib), library, local=[exports], offline=True, log=lambda _: None)
    lacks = {r[2] for r in result.venues if r[3] == "library_lacks"}
    assert lacks == {"publisher"}


JOURNAL_EXPORT = """\
@article{x,
  title = {Journal Paper},
  author = {Doe, Jane},
  journal = {Journal of Tests},
  year = {2025},
  volume = {3},
  pages = {1--9},
  doi = {10.1016/j.test.2025.1},
  publisher = {Elsevier},
  issn = {1234-5678}
}
"""


def test_check_official_learn_hands_a_missing_journal_record_to_missing_venues(tmp_path: Path, web):
    bib = tmp_path / "refs.bib"
    bib.write_text("@article{J_Doe_JT2025,\n  title = {Journal Paper},\n  author = {Doe, Jane},\n"
                   "  journal = {Journal of Tests},\n  year = {2025},\n  volume = {3}\n}\n")
    exports = tmp_path / "exports"
    exports.mkdir()
    (exports / "J_Doe_JT2025.bib").write_text(JOURNAL_EXPORT)
    venues = tmp_path / "venues.yaml"
    venues.write_text("journals: []\n", encoding="utf-8")

    main(["check", "official", str(bib), "--local", str(exports), "--offline", "--venues", str(venues), "--learn"])
    assert VenueLibrary.load(venues).journals == []
    text = (tmp_path / ".bibcc" / "refs.bib" / "missing_venues.yaml").read_text()
    assert '  - name: "Journal of Tests"' in text
    assert 'publisher: "Elsevier"  # from official BibTeX (J_Doe_JT2025)' in text
    assert 'issn: "1234-5678"  # from official BibTeX' in text
    assert "    entry_fields: [doi, pages, volume]" in text
    assert "learned_from: \"official BibTeX of 1 entry (2025)" in text

    main(["complete", str(bib), "--update-venues-only", "--venues", str(venues)])
    (journal,) = VenueLibrary.load(venues).journals
    assert journal.fields == {"publisher": "Elsevier", "issn": "1234-5678"}
    assert journal.entry_fields == ["doi", "pages", "volume"]
    assert journal.learned_from.startswith("official BibTeX of 1 entry (2025), ")


def test_a_later_run_adds_the_schema_to_a_record_already_in_missing_venues(tmp_path: Path, web):
    bib = tmp_path / "refs.bib"
    bib.write_text("@article{J_Doe_JT2025,\n  title = {Journal Paper},\n  author = {Doe, Jane},\n"
                   "  journal = {Journal of Tests},\n  year = {2025},\n  volume = {3}\n}\n")
    venues = tmp_path / "venues.yaml"
    venues.write_text("journals: []\n", encoding="utf-8")
    main(["complete", str(bib), "--venues", str(venues)])
    yaml_path = tmp_path / ".bibcc" / "refs.bib" / "missing_venues.yaml"
    assert "    entry_fields:" not in yaml_path.read_text()

    exports = tmp_path / "exports"
    exports.mkdir()
    (exports / "J_Doe_JT2025.bib").write_text(JOURNAL_EXPORT)
    main(["check", "official", str(bib), "--local", str(exports), "--offline", "--venues", str(venues), "--learn"])
    text = yaml_path.read_text()
    assert text.count("- name:") == 1
    assert "    entry_fields: [doi, pages, volume]" in text


ECCV = "Computer Vision -- ECCV 2024"


def _eccv_entry(key: str, chapter: str, volume: str, part: str) -> str:
    return (f"@inproceedings{{{key},\n  title = {{Paper {key}}},\n  author = {{Doe, Jane}},\n"
            f"  booktitle = {{{ECCV}}},\n  year = {{2025}},\n  pages = {{1--17}},\n"
            f"  doi = {{10.1007/{chapter}}},\n  volume = {{{volume}}},\n  part = {{{part}}}\n}}\n\n")


def _eccv_export(key: str) -> str:
    return (f"@InProceedings{{{key},\n  title = {{Paper {key}}},\n  author = {{Doe, Jane}},\n"
            f"  booktitle = {{{ECCV}}},\n  year = {{2025}},\n  pages = {{1--17}}\n}}\n")


def test_check_official_learns_the_volume_and_part_of_each_book(tmp_path: Path, web):
    from bibcc.completer import complete_entry

    bib = tmp_path / "refs.bib"
    bib.write_text(_eccv_entry("A_Doe_ECCV2024", "978-3-031-72649-1_1", "15059", "XXVI")
                   + _eccv_entry("B_Doe_ECCV2024", "978-3-031-72649-1_7", "15059", "XXVI")
                   + _eccv_entry("C_Doe_ECCV2024", "978-3-031-73000-0_2", "15060", "XXVII"))
    exports = tmp_path / "exports"
    exports.mkdir()
    for key in ("A_Doe_ECCV2024", "B_Doe_ECCV2024", "C_Doe_ECCV2024"):
        (exports / f"{key}.bib").write_text(_eccv_export(key))
    venues = tmp_path / "venues.yaml"
    venues.write_text(f"proceedings:\n- name: {ECCV}\n  year: '2025'\n  fields: {{venue: 'Milan, Italy'}}\n")

    result = check_official_fields(str(bib), VenueLibrary.load(venues), local=[exports], offline=True,
                                   log=lambda _: None)
    rows = {(r[2], r[3]): r for r in result.venues}
    assert rows[("volume", "books_lack")] == (
        ECCV, "2025", "volume", "books_lack", "3", "2",
        "978-3-031-72649-1: 15059 (A_Doe_ECCV2024, B_Doe_ECCV2024); 978-3-031-73000-0: 15060 (C_Doe_ECCV2024)")
    assert rows[("part", "export_lacks")][4:6] == ("3", "3")
    assert ("doi", "export_lacks") not in rows  # like bibcc add, the check keeps the entry's DOI

    main(["check", "official", str(bib), "--local", str(exports), "--offline", "--venues", str(venues), "--learn"])
    (record,) = VenueLibrary.load(venues).proceedings
    assert record.books == {"978-3-031-72649-1": {"volume": "15059", "part": "XXVI"},
                            "978-3-031-73000-0": {"volume": "15060", "part": "XXVII"}}
    assert "books:" in venues.read_text()

    library = VenueLibrary.load(venues)
    result = check_official_fields(str(bib), library, local=[exports], offline=True, log=lambda _: None)
    assert not [r for r in result.fields if r[1] in ("volume", "part")]
    assert not [r for r in result.venues if r[3] == "books_lack" or r[2] in ("volume", "part")]

    new = {"ID": "N", "ENTRYTYPE": "inproceedings", "booktitle": ECCV, "year": "2025",
           "doi": "https://doi.org/10.1007/978-3-031-73000-0_9"}
    assert complete_entry(new, library).patch == {"venue": "Milan, Italy", "volume": "15060", "part": "XXVII"}
    other = dict(new, doi="10.1007/978-3-031-99999-9_1")
    assert complete_entry(other, library).patch == {"venue": "Milan, Italy"}


def test_check_official_learn_counts_schemas_and_book_fields_apart(tmp_path: Path, web, capsys):
    bib = tmp_path / "refs.bib"
    bib.write_text(_eccv_entry("A_Doe_ECCV2024", "978-3-031-72649-1_1", "15059", "XXVI"))
    exports = tmp_path / "exports"
    exports.mkdir()
    (exports / "A_Doe_ECCV2024.bib").write_text(_eccv_export("A_Doe_ECCV2024"))
    venues = tmp_path / "venues.yaml"
    venues.write_text(f"proceedings:\n- name: {ECCV}\n  year: '2025'\n  fields: {{venue: 'Milan, Italy'}}\n")
    main(["check", "official", str(bib), "--local", str(exports), "--offline", "--venues", str(venues), "--learn"])
    out = capsys.readouterr().out
    # One family schema (doi, pages) and the book's volume and part, not "3 venue schemas".
    assert "Wrote 1 venue schemas and 2 book fields into" in out


def _isbn_entry(key: str, chapter: str) -> str:
    return (f"@inproceedings{{{key},\n  title = {{Paper {key}}},\n  author = {{Doe, Jane}},\n"
            f"  booktitle = {{{ECCV}}},\n  year = {{2025}},\n  doi = {{10.1007/{chapter}}}\n}}\n\n")


def _isbn_export(key: str, isbn: str) -> str:
    return (f"@InProceedings{{{key},\n  title = {{Paper {key}}},\n  author = {{Doe, Jane}},\n"
            f"  booktitle = {{{ECCV}}},\n  year = {{2025}},\n  isbn = {{{isbn}}}\n}}\n")


@pytest.mark.parametrize("books,expected", [
    # The record lists its books: the chapter's ISBN is one book's, not the edition's.
    ("  books:\n    978-3-031-72649-1: {volume: '15059'}\n", False),
    # A proceedings in one book (no books table): its ISBN is the edition's.
    ("", True),
])
def test_check_official_proposes_no_book_isbn_for_a_proceedings_in_several_books(tmp_path: Path, web, books,
                                                                                 expected):
    bib = tmp_path / "refs.bib"
    bib.write_text(_isbn_entry("A_Doe_ECCV2024", "978-3-031-72649-1_1"))
    exports = tmp_path / "exports"
    exports.mkdir()
    (exports / "A_Doe_ECCV2024.bib").write_text(_isbn_export("A_Doe_ECCV2024", "978-3-031-72649-1"))
    library = VenueLibrary.loads(f"proceedings:\n- name: {ECCV}\n  year: '2025'\n"
                                 f"  fields: {{venue: 'Milan, Italy'}}\n{books}")
    result = check_official_fields(str(bib), library, local=[exports], offline=True, log=lambda _: None)
    assert any(r[2] == "isbn" and r[3] == "library_lacks" for r in result.venues) is expected


def test_check_official_proposes_no_isbn_for_chapters_of_several_books(tmp_path: Path, web):
    bib = tmp_path / "refs.bib"
    bib.write_text(_isbn_entry("A_Doe_ECCV2024", "978-3-031-72649-1_1")
                   + _isbn_entry("B_Doe_ECCV2024", "978-3-031-73000-0_2"))
    exports = tmp_path / "exports"
    exports.mkdir()
    (exports / "A_Doe_ECCV2024.bib").write_text(_isbn_export("A_Doe_ECCV2024", "978-3-031-72649-1"))
    (exports / "B_Doe_ECCV2024.bib").write_text(_isbn_export("B_Doe_ECCV2024", "978-3-031-73000-0"))
    library = VenueLibrary.loads(f"proceedings:\n- name: {ECCV}\n  year: '2025'\n  fields: {{venue: 'Milan, Italy'}}\n")
    result = check_official_fields(str(bib), library, local=[exports], offline=True, log=lambda _: None)
    assert not [r for r in result.venues if r[2] == "isbn" and r[3] in ("library_lacks", "library_differs")]


@pytest.mark.parametrize("ours,theirs,same", [
    ("Huiping Zhuang and Yizhu Chen", "Zhuang, Huiping and Chen, Yizhu", True),
    ("Gido M. van de Ven", "van de Ven, Gido M.", True),
    ("Gido M. van de Ven", "Ven, Gido M. van de", False),
    ("Nor Ashidi Mat Isa", "Mat Isa, Nor Ashidi", False),  # a different last name
    ("Philip H.S. Torr", "Torr, Philip", False),
    ("Huiping Zhuang and Yizhu Chen", "Chen, Yizhu and Zhuang, Huiping", False),  # the order counts
])
def test_names_in_either_bibtex_form_agree(ours, theirs, same):
    from bibcc.checkers.official_fields import _same_value

    assert _same_value("author", ours, theirs) is same
    assert _same_value("editor", ours, theirs) is same


def test_book_of_reads_the_isbn_of_a_chapter_doi():
    from bibcc.venues import book_of

    assert book_of("10.1007/978-3-031-72649-1_13") == "978-3-031-72649-1"
    assert book_of("doi:10.1007/978-3-031-7264-X_2") == "978-3-031-7264-X"
    assert book_of("10.1007/s11263-024-02000-1") == ""
    assert book_of("") == ""
