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
