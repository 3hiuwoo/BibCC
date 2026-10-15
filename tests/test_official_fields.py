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
