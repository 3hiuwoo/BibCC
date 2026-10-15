"""The provider table, family records of the venue library, schemas, and the download cache."""

import os
import time
from pathlib import Path

from bibcc import cache, official, sources
from bibcc.families import PMLR, builtin_families, registry
from bibcc.schemas import OFFICIAL, apply_proposals, observe, propose
from bibcc.venues import PROCEEDINGS, Family, Venue, VenueLibrary, previous_edition

ICML_2024 = "Proceedings of the 41st International Conference on Machine Learning"
ICML_2025 = "Proceedings of the 42nd International Conference on Machine Learning"


# ---------------------------------------------------------- provider table


def test_builtin_table_names_providers_and_holds_no_venue_fields():
    reg = registry()
    assert reg.get("ICML").provider == PMLR
    assert reg.get("nips").acronym == "NeurIPS"
    assert reg.canonical("NIPS") == "NeurIPS"
    assert reg.acronym_of(ICML_2024) == "ICML"
    assert reg.acronym_of("Conference on Lifelong Learning Agents") == "CoLLAs"
    assert reg.acronym_of("2024 IEEE/CVF Conference on Computer Vision and Pattern Recognition Workshops (CVPRW)") \
        == "CVPRW"
    assert reg.interim_is_official("International Conference on Learning Representations", "2023")
    assert not reg.interim_is_official("International Conference on Learning Representations", "2024")
    assert reg.search_prefix("xplore") == "10.1109"
    assert all(not hasattr(spec, "fields") for spec in builtin_families())


def test_library_family_records_override_and_add_providers():
    library = VenueLibrary.loads("""\
families:
- name: Conference on Parsimony and Learning
  acronym: CPAL
  provider: pmlr
- acronym: NeurIPS
  interim: ""
  manual_url: https://example.org/neurips
""")
    reg = registry(library)
    assert reg.get("CPAL").provider == PMLR
    assert reg.acronym_of("Conference on Parsimony and Learning", library) == "CPAL"
    assert reg.get("NeurIPS").manual_url == "https://example.org/neurips"
    assert reg.get("NeurIPS").site == "https://proceedings.neurips.cc"  # keys it doesn't set stay
    assert registry().get("CPAL") is None  # the built-in table is unchanged


# --------------------------------------------------------- family records


FAMILY_LIBRARY = f"""\
families:
- name: International Conference on Machine Learning
  acronym: ICML
  fields: {{publisher: PMLR, series: Proceedings of Machine Learning Research}}
  entry_fields: [pages, pdf, url]
  learned_from: official BibTeX of 3 entries (2024)
proceedings:
- name: {ICML_2024}
  year: '2024'
  fields: {{venue: 'Vienna, Austria', publisher: PMLR Press}}
- name: {ICML_2025}
  year: '2025'
  fields: {{venue: 'Vancouver, Canada'}}
  entry_fields: [pages, url]
"""


def test_family_record_supplies_fields_and_schema_to_its_editions(tmp_path: Path):
    library = VenueLibrary.loads(FAMILY_LIBRARY)
    icml24 = library.find_exact(PROCEEDINGS, ICML_2024, "2024")
    icml25 = library.find_exact(PROCEEDINGS, ICML_2025, "2025")

    assert library.family_of(ICML_2024).acronym == "ICML"
    assert library.family_of("ICML 2026").acronym == "ICML"  # by acronym
    assert library.fields_of(icml24) == {
        "publisher": "PMLR Press", "series": "Proceedings of Machine Learning Research", "venue": "Vienna, Austria",
    }
    assert library.schema_of(icml24) == (
        ["pages", "pdf", "url"],
        "family International Conference on Machine Learning (ICML), learned from official BibTeX of 3 entries (2024)",
    )
    assert library.schema_of(icml25)[0] == ["pages", "url"]  # the edition's own schema wins
    assert previous_edition(library, ICML_2025, "2025") is icml24

    path = tmp_path / "venues.yaml"
    library.save(path)
    again = VenueLibrary.load(path)
    assert [f.to_dict() for f in again.families] == [f.to_dict() for f in library.families]
    assert again.find_exact(PROCEEDINGS, ICML_2025, "2025").entry_fields == ["pages", "url"]
    text = path.read_text()
    assert text.index("\nfamilies:\n") < text.index("\nproceedings:\n")


def test_upsert_family_merges_names_fields_and_schema():
    library = VenueLibrary.loads(FAMILY_LIBRARY)
    status = library.upsert_family(Family(name="ICML", acronym="ICML", fields={"address": "Online"},
                                          entry_fields=["pages"]), overwrite=False)
    assert status == "updated"
    (family,) = library.families
    assert family.fields["address"] == "Online"
    assert family.entry_fields == ["pages", "pdf", "url"]  # kept without overwrite
    assert "ICML" in family.aliases


# ----------------------------------------------------------------- schemas


def _entry(key: str, name: str, year: str) -> dict:
    return {"ID": key, "ENTRYTYPE": "inproceedings", "booktitle": name, "year": year}


def test_propose_gives_a_differing_year_its_own_schema():
    library = VenueLibrary.loads(f"""\
proceedings:
- name: {ICML_2024}
  year: '2024'
  fields: {{venue: 'Vienna, Austria'}}
""")
    seen = [
        observe(_entry("A", ICML_2025, "2025"), library, ["pages", "url", "pdf", "publisher", "title"]),
        observe(_entry("B", ICML_2025, "2025"), library, ["pages", "url", "pdf"]),
        observe(_entry("C", ICML_2024, "2024"), library, ["pages", "url", "venue"]),
    ]
    proposals = propose(seen, library, OFFICIAL)

    assert [(p.level, p.year, p.fields) for p in proposals] == [
        ("family", "", ["pages", "pdf", "url"]),
        ("edition", "2024", ["pages", "url"]),
    ]
    assert proposals[0].new_family_name == "Proceedings of the International Conference on Machine Learning"

    target = VenueLibrary.loads(f"""\
proceedings:
- name: {ICML_2024}
  year: '2024'
  fields: {{venue: 'Vienna, Austria'}}
""")
    logs = []
    assert apply_proposals(target, proposals, logs.append) == 2
    assert target.families[0].acronym == "ICML"
    assert target.proceedings[0].entry_fields == ["pages", "url"]
    assert target.proceedings[0].learned_from.startswith("official BibTeX of 1 entry (2024), ")


def test_apply_proposals_skips_records_of_another_library():
    merged = VenueLibrary(journals=[Venue("journal", "Pattern Recognition", {"publisher": "Elsevier"},
                                          origin="project")])
    seen = [observe({"ID": "A", "ENTRYTYPE": "article", "journal": "Pattern Recognition", "year": "2025"},
                    merged, ["volume", "pages", "doi"])]
    proposals = propose(seen, merged, OFFICIAL)
    logs = []
    assert apply_proposals(VenueLibrary(), proposals, logs.append) == 0
    assert "pass --scope project" in logs[0]


def test_articles_not_in_an_issue_dont_count_toward_a_schema():
    library = VenueLibrary()
    article = {"ID": "A", "ENTRYTYPE": "article", "journal": "Pattern Recognition", "year": "2025"}
    assert observe(article, library, ["doi"]) is None
    assert observe(article, library, ["doi", "volume"]).fields == {"doi", "volume"}


# ------------------------------------------------------------------- cache


def test_cache_keeps_downloads_until_they_age_or_a_refresh(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("BIBCC_CACHE", str(tmp_path / "cache"))
    assert cache.get("https://example.org/a.bib") is None
    cache.put("https://example.org/a.bib", "@inproceedings{a}")
    assert cache.get("https://example.org/a.bib") == "@inproceedings{a}"

    cache.refresh()
    assert cache.get("https://example.org/a.bib") is None
    cache.refresh(False)

    (path,) = (tmp_path / "cache" / "official").iterdir()
    old = time.time() - (cache.MAX_AGE_DAYS + 1) * 86400
    os.utime(path, (old, old))
    assert cache.get("https://example.org/a.bib") is None

    monkeypatch.setenv("BIBCC_CACHE", "off")
    cache.put("https://example.org/b.bib", "x")
    assert cache.cache_dir() is None and cache.get("https://example.org/b.bib") is None


def test_official_downloads_read_the_disk_cache(monkeypatch):
    calls = []

    def fetch(url, **_):
        calls.append(url)
        return "@inproceedings{pmlr-v235-a24a, title = {A}}", None

    monkeypatch.setattr(sources, "fetch_url", fetch)
    official.clear_cache()
    url = "https://proceedings.mlr.press/v235/a24a/a24a.bib"
    first = official._get(url, keep=official._is_bibtex)
    official.clear_cache()  # a new run: only the disk cache remembers
    assert official._get(url, keep=official._is_bibtex) == first
    assert calls == [url]
