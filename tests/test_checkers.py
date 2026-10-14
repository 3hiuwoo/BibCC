from pathlib import Path

import pytest

from bibcc.checkers.citation_keys import check_citation_keys
from bibcc.checkers.missing_fields import check_missing_fields
from bibcc.checkers.template_fields import check_template_fields
from bibcc.titlecases import suggest_title_case

VENUES = """\
journals:
- name: Journal Complete
  fields:
    publisher: P
    issn: 1234-5678
- name: Journal Without ISSN
  fields:
    publisher: P
proceedings:
- name: European Conference on Computer Vision (ECCV)
  year: '2024'
  fields:
    venue: Milan, Italy
    publisher: Springer
    month: September
- name: Some Workshop
  year: '2023'
  fields:
    publisher: P
"""


def test_template_fields_reports_and_counts_override_fields(tmp_path: Path):
    path = tmp_path / "venues.yaml"
    path.write_text(VENUES, encoding="utf-8")
    logs = []

    check_template_fields(path, ["publisher", "issn"], ["venue", "publisher", "month"], log=logs.append)
    text = "\n".join(logs)

    assert "Journal Without ISSN" in text and "Journal Complete" not in text
    assert "1/2 journals have missing fields" in text
    assert "2/2 proceedings have missing fields" in text
    summary = text.split("Summary by field")[1]
    proceedings = summary.split("Proceedings:")[1]
    assert "issn: 1 missing" in summary
    assert "venue: 1 missing" in proceedings
    assert "month: 1 missing" in proceedings
    assert "series: 1 missing" in proceedings


def test_template_fields_cross_edition_consistency(tmp_path: Path):
    path = tmp_path / "venues.yaml"
    path.write_text(
        """\
proceedings:
- name: 2023 Conference on Examples (CE)
  year: '2023'
  fields:
    venue: Milan, Italy
    publisher: Springer
    month: June
    issn: 1234-5678
- name: 2024 Conference on Examples (CE)
  year: '2024'
  fields:
    venue: Paris, France
    publisher: Springer
    month: June
    issn: 1234-5678
- name: 2025 Conference on Examples (CE)
  year: '2025'
  fields:
    venue: Nice, France
    publisher: Springer
    month: June
""",
        encoding="utf-8",
    )
    logs = []

    check_template_fields(path, [], [], log=logs.append)
    text = "\n".join(logs)

    section = text.split("Cross-edition consistency")[1]
    assert "'issn' missing in 2025" in section
    assert "2023, 2024 have '1234-5678'" in section
    # venue differs per edition and month is everywhere: neither is reported.
    assert "'venue'" not in section
    assert "'month'" not in section


def test_template_fields_cross_edition_nothing_to_report(tmp_path: Path):
    path = tmp_path / "venues.yaml"
    path.write_text(
        """\
proceedings:
- name: 2024 Conference on Examples (CE)
  year: '2024'
  fields:
    publisher: Springer
- name: 2025 Conference on Examples (CE)
  year: '2025'
  fields:
    publisher: Springer
""",
        encoding="utf-8",
    )
    logs = []

    check_template_fields(path, [], [], log=logs.append)

    assert "Editions of the same venue define the same fields." in "\n".join(logs)


def test_missing_fields_filters_types_and_blank_values(tmp_path: Path):
    bib = tmp_path / "refs.bib"
    bib.write_text(
        """\
@inproceedings{HasMonth, title={A}, year={2024}, month=jun}
@inproceedings{BlankMonth, title={B}, year={2024}, month={ }}
@article{NoMonth, title={C}, year={2023}}
@misc{IgnoredType, title={D}}
""",
        encoding="utf-8",
    )
    logs = []

    rows = check_missing_fields(str(bib), ["month", " "], ["inproceedings", "article"], log=logs.append)

    assert rows == [
        ("BlankMonth", "inproceedings", "2024", ["month"]),
        ("NoMonth", "article", "2023", ["month"]),
    ]
    assert "month: 2" in logs[-1]


def test_missing_fields_skips_when_no_fields(tmp_path: Path):
    logs = []
    assert check_missing_fields(str(tmp_path / "absent.bib"), [""], ["article"], log=logs.append) == []
    assert "skipping" in logs[0]


@pytest.mark.parametrize(
    "title, expected",
    [
        # Text glued to a braced group continues that word.
        ("Continual {G}aussian Mixture Modeling with Priors", "Continual {G}aussian Mixture Modeling With Priors"),
        ("{BECAME}: {B}ayesian Continual Learning", "{BECAME}: {B}ayesian Continual Learning"),
        ("Layer-Wise {LoRA}s Guided by a Tree", "Layer-Wise {LoRA}s Guided by a Tree"),
        ("{G}aussian-augmented prototypical network", "{G}aussian-Augmented Prototypical Network"),
        # Capitals after the first letter are deliberate.
        ("PODNet: pooled outputs distillation", "PODNet: Pooled Outputs Distillation"),
        ("{CODA-Prompt}: COntinual decomposed prompting", "{CODA-Prompt}: COntinual Decomposed Prompting"),
        # Minor words joining a compound stay lowercase, except as its last part.
        ("learning with out-of-distribution detection", "Learning With Out-of-Distribution Detection"),
        ("mixture-of-experts adapters for plug-and-play use", "Mixture-of-Experts Adapters for Plug-and-Play Use"),
        ("a plug-in module and a follow-up", "A Plug-In Module and a Follow-Up"),
        ("self-report and class-incremental learning", "Self-Report and Class-Incremental Learning"),
    ],
)
def test_suggest_title_case(title, expected):
    assert suggest_title_case(title) == expected


def test_citation_key_year_allows_event_year(tmp_path: Path):
    bib = tmp_path / "refs.bib"
    bib.write_text(
        """\
@inproceedings{A_X_ECCV2024, year={2025}, booktitle={Computer Vision -- {ECCV} 2024}}
@inproceedings{B_X_CoLLAs2024, year={2025}, booktitle={Proceedings of The 3rd Conference on Lifelong Learning Agents}}
@misc{C_X_AAAI2026, year={2025}, eprint={2511.09791}, archiveprefix={arXiv}}
@inproceedings{D_X_ECCV2022, year={2025}, booktitle={Computer Vision -- {ECCV} 2024}}
@inproceedings{E_X_CVPR2023, year={2025}, booktitle={CVPR}}
@article{F_X_TPAMI2021, year={2022}, journal={{IEEE} Transactions on Pattern Analysis and Machine Intelligence}}
@misc{G_X_arXiv2026, year={2027}, eprint={2601.00001}}
""",
        encoding="utf-8",
    )
    rows = check_citation_keys(str(bib), log=lambda _: None)
    assert sorted(eid for eid, kind, _ in rows if kind == "year_mismatch") == [
        "D_X_ECCV2022", "E_X_CVPR2023", "F_X_TPAMI2021", "G_X_arXiv2026",
    ]


def test_citation_key_author_must_be_first_surname(tmp_path: Path):
    bib = tmp_path / "refs.bib"
    bib.write_text(
        """\
@article{A_Zhou_TPAMI2024, author={Zhou, Da-Wei and Wang, Qi}, year={2024}}
@article{B_Wang_TPAMI2024, author={Zhou, Da-Wei and Wang, Qi}, year={2024}}
@article{C_Zajac_TPAMI2024, author={Zaj\\k{a}c, Marcin}, year={2024}}
@article{D_Ven_TPAMI2024, author={Gido M. van de Ven}, year={2024}}
@article{E_Li_TPAMI2024, author={Lin, Tsung-Yi}, year={2024}}
@article{F_Anon_TPAMI2024, year={2024}}
""",
        encoding="utf-8",
    )
    rows = check_citation_keys(str(bib), log=lambda _: None)
    assert [(eid, kind) for eid, kind, _ in rows] == [
        ("B_Wang_TPAMI2024", "author_mismatch"), ("E_Li_TPAMI2024", "author_mismatch"),
    ]


def _check(args, capsys):
    from bibcc.cli import main

    try:
        main(["check", *args])
    except SystemExit as e:
        return e.code, capsys.readouterr().out
    return 0, capsys.readouterr().out


def test_check_strict_exit_status_and_empty_entries(tmp_path: Path, capsys):
    bib = tmp_path / "refs.bib"
    bib.write_text(
        "@article{A_Zhou_TPAMI2024,\n  author = {Zhou, Da-Wei},\n  year = {2024},\n  month = jun,\n}\n",
        encoding="utf-8",
    )
    assert _check(["keys", str(bib), "--strict"], capsys)[0] == 0
    assert _check(["missing", str(bib), "--strict"], capsys)[0] == 0
    bib.write_text(bib.read_text() + "\n@article{B_Wang_TPAMI2024,\n  author = {Zhou, Da-Wei},\n  year = {2024},\n}\n")
    assert _check(["keys", str(bib)], capsys)[0] == 0
    code, out = _check(["keys", str(bib), "--strict"], capsys)
    assert code == 1 and "author_mismatch" in out
    assert (tmp_path / ".bibcc" / "refs.bib" / "citation_keys.txt").exists()
    assert not (tmp_path / ".bibcc" / "refs.bib" / "missing_fields.txt").exists()

    bib.write_text(
        "@article{A_Zhou_TPAMI2024,\n  author = {Zhou, Da-Wei},\n  year = {2024},\n}\n\n"
        "% BibCC: no official BibTeX could be downloaded\n@inproceedings{C_Li_AAAI2025,\n}\n"
    )
    code, out = _check(["keys", str(bib), "--strict"], capsys)
    assert code == 1
    assert "1 empty entries have no fields, so the check skips them: C_Li_AAAI2025" in out
    assert f"bibcc add --retry --output {bib}" in out
    assert _check(["keys", str(tmp_path / "missing.bib")], capsys)[0] == 2
    assert _check([str(bib)], capsys)[0] == 2  # a check name comes first
    assert _check(["missing", str(bib), "--fields", ""], capsys)[0] == 2


def test_check_quote_apply_braces_only_given_terms(tmp_path: Path, capsys):
    bib = tmp_path / "refs.bib"
    bib.write_text(
        "@article{A_Zhou_TPAMI2024,\n"
        "  title  = {LoRA Meets {CLIP}: Gaussian Adapters for lora Tuning},\n"
        "  author = {Zhou, Da-Wei},\n"
        "  year   = {2024},\n"
        "}\n",
        encoding="utf-8",
    )
    vocab = tmp_path / "terms.txt"
    vocab.write_text("Adapters\n")
    code, out = _check(["quote", str(bib), "--apply", "--terms", "LoRA,CLIP",
                        "--vocab-file", str(vocab)], capsys)
    assert code == 0
    text = bib.read_text()
    assert "title  = {{LoRA} Meets {CLIP}: Gaussian {Adapters} for lora Tuning}," in text
    assert "Gaussian" in out  # still reported by the check, but not applied
    assert "author = {Zhou, Da-Wei}," in text


def test_check_quote_reports_and_splits_overbraced_compounds(tmp_path: Path, capsys):
    bib = tmp_path / "refs.bib"
    bib.write_text(
        "@article{A_Zhou_TPAMI2024,\n"
        "  title  = {{CLIP-Based} {SD-LoRA} and {Transformer-XL} Tuning},\n"
        "  year   = {2024},\n"
        "}\n",
        encoding="utf-8",
    )
    code, out = _check(["quote", str(bib)], capsys)
    assert code == 0
    report = (tmp_path / ".bibcc" / "refs.bib" / "smart_protection.txt").read_text()
    assert "A_Zhou_TPAMI2024\t{CLIP-Based}\tOver-Braced: use {CLIP}-Based" in report
    assert "{SD-LoRA}" not in report
    assert "{CLIP-Based}" in bib.read_text()  # reporting never writes

    # --apply needs no terms to split; a compound listed in --terms stays whole.
    assert _check(["quote", str(bib), "--apply", "--terms", "Transformer-XL"], capsys)[0] == 0
    assert "title  = {{CLIP}-Based {SD-LoRA} and {Transformer-XL} Tuning}," in bib.read_text()
    assert not (tmp_path / ".bibcc" / "refs.bib" / "smart_protection.txt").exists()


def test_check_quote_apply_and_interactive_are_exclusive(tmp_path: Path, capsys):
    bib = tmp_path / "refs.bib"
    bib.write_text("@article{k, title = {A Study}, year = {2024}}\n", encoding="utf-8")
    assert _check(["quote", str(bib), "--apply", "--interactive"], capsys)[0] == 2


def test_check_quote_interactive_accept_skip_remember(tmp_path: Path, capsys, monkeypatch):
    bib = tmp_path / "refs.bib"
    bib.write_text(
        "@article{A_Zhou_TPAMI2024,\n"
        "  title  = {{CIP-Net} and {CLIP-Based} for Tuning},\n"
        "  year   = {2024},\n"
        "}\n"
        "@inproceedings{B_Li_CVPR2024,\n"
        "  title  = {Revisiting {CIP-Net} Models},\n"
        "  year   = {2024},\n"
        "}\n",
        encoding="utf-8",
    )
    answers = iter(["r", "a"])  # remember {CIP-Net}, accept the {CLIP-Based} split
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(answers))
    code, out = _check(["quote", str(bib), "--interactive"], capsys)
    assert code == 0
    text = bib.read_text()
    assert "title  = {{CIP-Net} and {CLIP}-Based for Tuning}," in text
    # The remembered compound stays whole in the second entry without asking.
    assert "title  = {Revisiting {CIP-Net} Models}," in text
    assert "Interactive summary: 1 accepted, 0 edited, 0 skipped, 1 remembered" in out
    vocab = tmp_path / ".bibcc" / "refs.bib" / "vocab.txt"
    assert vocab.read_text(encoding="utf-8").strip() == "CIP-Net"

    # Later runs read the vocabulary file and leave the compound whole.
    code, out = _check(["quote", str(bib)], capsys)
    assert code == 0
    assert "Over-Braced" not in out
    assert "✅ No unprotected terms in 2 entries." in out

    # --apply keeps it whole too, and braces it where it appears unbraced.
    bib.write_text(
        bib.read_text()
        + "@article{C_Wang_AAAI2025,\n  title = {CIP-Net Revisited}, year = {2025},\n}\n"
    )
    assert _check(["quote", str(bib), "--apply"], capsys)[0] == 0
    assert "title = {{CIP-Net} Revisited}," in bib.read_text()


def test_check_quote_interactive_skip_and_quit(tmp_path: Path, capsys, monkeypatch):
    bib = tmp_path / "refs.bib"
    bib.write_text(
        "@article{A_Zhou_TPAMI2024,\n"
        "  title  = {{CLIP-Based} Prompting},\n"
        "  year   = {2024},\n"
        "}\n"
        "@inproceedings{B_Li_CVPR2024,\n"
        "  title  = {{ViT-based} Models},\n"
        "  year   = {2024},\n"
        "}\n",
        encoding="utf-8",
    )
    answers = iter(["s", "q"])  # skip the first, quit at the second
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(answers))
    code, out = _check(["quote", str(bib), "--interactive"], capsys)
    assert code == 0
    assert bib.read_text().count("{CLIP-Based}") == 1  # skipped: kept whole, not written
    assert "✅ No title changed." in out
    assert not (tmp_path / ".bibcc" / "refs.bib" / "vocab.txt").exists()
    # The compounds are still reported after the review.
    assert "Over-Braced" in out


def test_check_quote_reads_auto_vocab_file(tmp_path: Path, capsys):
    bib = tmp_path / "refs.bib"
    bib.write_text("@article{k, title = {{CIP-Net} Models}, year = {2024}}\n", encoding="utf-8")
    vocab = tmp_path / ".bibcc" / "refs.bib" / "vocab.txt"
    vocab.parent.mkdir(parents=True)
    vocab.write_text("CIP-Net\n", encoding="utf-8")
    code, out = _check(["quote", str(bib)], capsys)
    assert code == 0
    assert "Over-Braced" not in out
    assert not (tmp_path / ".bibcc" / "refs.bib" / "smart_protection.txt").exists()
