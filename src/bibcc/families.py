"""
Provider table: where the official BibTeX of each conference family lives.

The table ships with BibCC as data (``bibcc/data/families.yaml``) and holds
no venue fields, so it isn't a venue library.  Each row names a family by
its acronym and says which provider publishes its BibTeX (IEEE Xplore,
Springer, PMLR, a NeurIPS-style proceedings site, the ACL Anthology, IJCAI,
or OpenReview), which interim source it uses before the proceedings are out
(CVF Open Access or OpenReview), and so on.  The table also maps DOI
prefixes to providers and lists the publishers that block downloads.

A ``families`` record of a venue library (see :mod:`bibcc.venues`) with an
acronym overrides the keys it sets, and one with a new acronym adds a
family, so a new PMLR conference needs no code change::

    families:
      - name: Conference on Parsimony and Learning
        acronym: CPAL
        provider: pmlr

Usage:
    from bibcc.families import registry

    reg = registry(library)
    spec = reg.get(reg.acronym_of("Proceedings of the 41st International Conference on Machine Learning"))
    spec.provider  # "pmlr"
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache
from importlib import resources
from typing import Dict, List, Optional

import yaml

from bibcc.venues import Family, VenueLibrary, family_from_dict

XPLORE = "xplore"
SPRINGER = "springer"
PROCEEDINGS_SITE = "proceedings"
PMLR = "pmlr"
ACL = "acl"
IJCAI = "ijcai"
OPENREVIEW = "openreview"
BLOCKED = "blocked"
PROVIDERS = (XPLORE, SPRINGER, PROCEEDINGS_SITE, PMLR, ACL, IJCAI, OPENREVIEW, BLOCKED)

_WORKSHOP = re.compile(r"\bworkshops?\b", re.IGNORECASE)


@dataclass
class Spec:
    """The provider facts of one family (the routing keys of a :class:`bibcc.venues.Family`)."""

    acronym: str
    acronym_aliases: List[str] = field(default_factory=list)
    pattern: str = ""
    workshop_of: str = ""
    provider: str = ""
    site: str = ""
    interim: str = ""
    interim_since: str = ""
    blocked_by: str = ""
    manual_url: str = ""

    def interim_is_official(self, year: str) -> bool:
        """Whether the interim source is the official one in *year* (ICLR on OpenReview before 2024)."""
        since = self.interim_since
        return bool(since.isdigit() and year.isdigit() and int(year) < int(since))

    def update(self, family: Family) -> None:
        for key, value in family.routing.items():
            if key == "acronym_aliases":
                self.acronym_aliases = list(dict.fromkeys([*self.acronym_aliases, *value]))
            else:
                setattr(self, key, str(value))


@dataclass
class Registry:
    """The provider table, with the overrides of a venue library applied."""

    specs: Dict[str, Spec] = field(default_factory=dict)  # casefolded acronym -> spec
    doi_prefixes: Dict[str, str] = field(default_factory=dict)
    blocked_prefixes: Dict[str, str] = field(default_factory=dict)

    def get(self, acronym: str) -> Optional[Spec]:
        return self.specs.get(self._lookup.get((acronym or "").casefold(), ""))

    @property
    def _lookup(self) -> Dict[str, str]:
        names: Dict[str, str] = {}
        for key, spec in self.specs.items():
            names[key] = key
            for alias in spec.acronym_aliases:
                names.setdefault(alias.casefold(), key)
        return names

    def canonical(self, abbrev: str) -> str:
        """*abbrev* spelled as the table spells it (``nips`` -> ``NeurIPS``); unknown ones unchanged."""
        spec = self.get(abbrev)
        return spec.acronym if spec is not None else abbrev

    def search_prefix(self, provider: str) -> str:
        """The DOI prefix that a CrossRef title search uses for *provider*."""
        return next((p for p, name in self.doi_prefixes.items() if name == provider), "")

    def acronym_of(self, venue_name: str, library: Optional[VenueLibrary] = None) -> str:
        """The family acronym of a booktitle or journal name, or ``""``.

        In order: the acronym of the venue library family whose name or
        alias it shares; a table ``pattern``; the abbreviation that
        :func:`bibcc.checkers.citation_keys.abbreviate_venue` finds, as the
        table spells it; with the word "workshop", the table's workshop
        family of that abbreviation.
        """
        # Imported here: bibcc.checkers imports bibcc.official, which imports this module.
        from bibcc.checkers.citation_keys import abbreviate_venue

        text = " ".join((venue_name or "").replace("{", "").replace("}", "").split())
        if not text:
            return ""
        if library is not None and library.families:
            from bibcc.venues import family_match_keys

            keys = family_match_keys(text)
            for family in library.families:
                if family.acronym and keys & family.keys():
                    return self.canonical(family.acronym)
        for spec in self.specs.values():
            if spec.pattern and re.search(spec.pattern, text, re.IGNORECASE):
                return spec.acronym
        abbrev = self.canonical(abbreviate_venue(text))
        if _WORKSHOP.search(text):
            workshop = next((s for s in self.specs.values() if s.workshop_of.casefold() == abbrev.casefold()), None)
            if workshop is not None:
                return workshop.acronym
        return abbrev

    def interim_is_official(self, venue_name: str, year: str, library: Optional[VenueLibrary] = None) -> bool:
        spec = self.get(self.acronym_of(venue_name, library))
        return spec is not None and spec.interim_is_official(year)


def _load_table() -> Dict:
    text = resources.files("bibcc").joinpath("data/families.yaml").read_text(encoding="utf-8")
    return yaml.safe_load(text) or {}


@lru_cache(maxsize=1)
def _builtin() -> Registry:
    data = _load_table()
    reg = Registry(
        doi_prefixes={str(k): str(v) for k, v in (data.get("doi_prefixes") or {}).items()},
        blocked_prefixes={str(k): str(v) for k, v in (data.get("blocked_doi_prefixes") or {}).items()},
    )
    for i, raw in enumerate(data.get("families") or []):
        family = family_from_dict(raw, f"bibcc/data/families.yaml: families[{i}]")
        spec = Spec(family.acronym)
        spec.update(family)
        reg.specs[family.acronym.casefold()] = spec
    return reg


def builtin_families() -> List[Spec]:
    """The rows of the built-in table, in table order."""
    return list(_builtin().specs.values())


def registry(library: Optional[VenueLibrary] = None) -> Registry:
    """The built-in table, with the routing keys of *library*'s family records applied."""
    base = _builtin()
    families = [f for f in (library.families if library is not None else []) if f.acronym and f.routing]
    if not families:
        return base
    reg = Registry(
        specs={k: Spec(**vars(v)) for k, v in base.specs.items()},
        doi_prefixes=dict(base.doi_prefixes),
        blocked_prefixes=dict(base.blocked_prefixes),
    )
    for family in families:
        key = reg._lookup.get(family.acronym.casefold(), family.acronym.casefold())
        spec = reg.specs.setdefault(key, Spec(family.acronym))
        spec.update(family)
    return reg


def acronym_of(venue_name: str, library: Optional[VenueLibrary] = None) -> str:
    """Shortcut for ``registry(library).acronym_of(venue_name, library)``."""
    return registry(library).acronym_of(venue_name, library)
