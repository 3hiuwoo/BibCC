"""
BibCC configuration: settings files in two scopes, like the venue library.

The user config (``$BIBCC_CONFIG``, else ``~/.config/bibcc/config.yaml``)
holds settings for every project, and a project config (``.bibcc.yaml``,
committed with the bibliography) holds the settings of one project.  A
command reads both: where both set a key, the project's value wins, and a
command-line option wins over both.  Each command reads its own section;
``format`` reads ``format:``.  Shared configs to start from live in
``examples/config/`` of the BibCC repository.

Usage:
    from bibcc.config import load_config

    config = load_config(start="bib/refs.bib")   # user, then project
    config.section("format")                     # merged, validated values
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

import yaml

from bibcc.venues import PROJECT_SCOPE, USER_SCOPE

CONFIG_ENV_VAR = "BIBCC_CONFIG"
PROJECT_CONFIG_NAME = ".bibcc.yaml"
USER_CONFIG_DISPLAY = "~/.config/bibcc/config.yaml"
FILE_SCOPE = "file"  # a config named with --config FILE
SCOPES = (USER_SCOPE, PROJECT_SCOPE)

FORMAT_SECTION = "format"
# In a field order, the place of every field that the order doesn't list.
OTHER_FIELDS = "*"

HEADER = """\
# BibCC configuration. Each command reads its own section (format: for
# 'bibcc format'). A project's .bibcc.yaml wins over the user config, and
# command-line options win over both. For the keys, see 'bibcc config -h'.
#
# 'bibcc config import' rewrites this file; comments other than this header
# are not preserved.
"""


class ConfigError(ValueError):
    """A config file that can't be read or has an invalid value."""


class ConfigNotFound(LookupError):
    """The project scope has no config file, and the caller didn't ask to create one."""


# ------------------------------------------------------------------ files


def user_config_path() -> Path:
    """``$BIBCC_CONFIG`` if set, else ``$XDG_CONFIG_HOME/bibcc/config.yaml`` (``~/.config`` by default)."""
    env = os.environ.get(CONFIG_ENV_VAR)
    if env:
        return Path(env).expanduser()
    config_home = os.environ.get("XDG_CONFIG_HOME") or "~/.config"
    return Path(config_home).expanduser() / "bibcc" / "config.yaml"


def find_project_config(start: Optional[str | Path] = None) -> Optional[Path]:
    """The nearest ``.bibcc.yaml`` in *start* (a file or folder; default: cwd) or its parents."""
    here = Path(start or Path.cwd()).expanduser().resolve()
    if not here.is_dir():
        here = here.parent
    for folder in (here, *here.parents):
        candidate = folder / PROJECT_CONFIG_NAME
        if candidate.is_file():
            return candidate
    return None


def config_path(scope: str = USER_SCOPE, start: Optional[str | Path] = None, create: bool = False) -> Path:
    """The config file that *scope* writes to.

    For the project scope, the nearest ``.bibcc.yaml`` above *start*.
    Without one, :class:`ConfigNotFound` is raised, unless *create*: then
    it is ``.bibcc.yaml`` in the current directory.
    """
    if scope == USER_SCOPE:
        return user_config_path()
    if scope != PROJECT_SCOPE:
        raise ValueError(f"unknown config scope {scope!r} (use one of {', '.join(SCOPES)})")
    found = find_project_config(start)
    if found is not None:
        return found
    if not create:
        where = Path(start or Path.cwd()).expanduser().resolve()
        raise ConfigNotFound(
            f"no {PROJECT_CONFIG_NAME} in {where} or its parent directories; create one in your "
            "project root with: bibcc config init --scope project"
        )
    return Path.cwd() / PROJECT_CONFIG_NAME


def parse_yaml(text: str, where: str) -> Dict[str, Any]:
    """The top-level mapping of a config file's text (``{}`` for an empty file)."""
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as e:
        raise ConfigError(f"{where}: not valid YAML ({e})") from e
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ConfigError(f"{where}: expected a mapping of sections (such as format:)")
    for name, section in data.items():
        if section is not None and not isinstance(section, dict):
            raise ConfigError(f"{where}: section '{name}' must be a mapping of keys")
    return {str(name): dict(section or {}) for name, section in data.items()}


def dump_yaml(data: Mapping[str, Any]) -> str:
    """The text of a config file holding *data*, with the header."""
    body = yaml.safe_dump(dict(data), sort_keys=False, allow_unicode=True, default_flow_style=None, width=100)
    return HEADER + "\n" + (body if data else "")


# ------------------------------------------------------- format settings


@dataclass(frozen=True)
class Setting:
    """One key of a section: its default and how to read its YAML value."""

    default: Any
    help: str
    parse: Callable[[Any, str], Any]


def _bool(value: Any, where: str) -> bool:
    if isinstance(value, bool):
        return value
    raise ConfigError(f"{where} must be true or false, not {value!r}")


def _count(value: Any, where: str) -> int:
    if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
        return value
    raise ConfigError(f"{where} must be a non-negative integer, not {value!r}")


def parse_indent(value: Any, where: str = "indent") -> int | str:
    """A number of spaces, or ``"tab"``."""
    if isinstance(value, str) and value.strip().lower() in ("tab", "\\t", "\t"):
        return "tab"
    if isinstance(value, str) and value.strip().isdigit():
        return int(value)
    if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
        return value
    raise ConfigError(f"{where} must be a number of spaces or 'tab', not {value!r}")


def _names(value: Any, where: str) -> List[str]:
    if isinstance(value, str):
        value = [part for part in value.split(",")]
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise ConfigError(f"{where} must be a list of field names")
    return [v.strip().lower() for v in value if v.strip()]


def parse_field_order(value: Any, where: str = "field_order") -> Tuple[str, ...]:
    """A field order as one tuple, with :data:`OTHER_FIELDS` marking where unlisted fields go.

    The YAML value is a mapping ``{first: [...], last: [...]}`` (unlisted
    fields go between the two lists), or a list, in which ``"*"`` marks
    that place (default: the end).  The command line gives the list form,
    comma-separated.
    """
    if isinstance(value, dict):
        unknown = sorted(set(value) - {"first", "last"})
        if unknown:
            raise ConfigError(f"{where} takes the keys first and last, not {', '.join(unknown)}")
        first = _names(value.get("first") or [], f"{where}.first")
        last = _names(value.get("last") or [], f"{where}.last")
        if OTHER_FIELDS in first + last:
            raise ConfigError(f"{where}: '{OTHER_FIELDS}' belongs only in the list form; "
                              "with first and last, the other fields go between the two")
        order = [*first, OTHER_FIELDS, *last]
    else:
        order = _names(value, where)
    if order.count(OTHER_FIELDS) > 1:
        raise ConfigError(f"{where} lists '{OTHER_FIELDS}' more than once")
    seen = set()
    for name in order:
        if name in seen:
            raise ConfigError(f"{where} lists the field '{name}' more than once")
        seen.add(name)
    if OTHER_FIELDS in order and order[-1] == OTHER_FIELDS:
        order.pop()
    return tuple(order)


def field_order_warnings(order: Sequence[str], where: str) -> List[str]:
    """A warning for each name of *order* that isn't a known BibTeX field (likely a typo)."""
    # Imported here so that bibcc.helptext can import this module without a cycle.
    from bibcc.checkers.field_issues import KNOWN_FIELDS, suggest_field

    warnings = []
    for name in order:
        if name == OTHER_FIELDS or name in KNOWN_FIELDS:
            continue
        guess = suggest_field(name)
        hint = f"; did you mean '{guess}'?" if guess else ""
        warnings.append(f"{where} lists '{name}', which isn't a known field{hint}")
    return warnings


def field_order_yaml(order: Sequence[str]) -> Any:
    """The YAML form of a parsed field order: ``{first, last}`` around the other fields."""
    order = list(order)
    if OTHER_FIELDS not in order:
        return {"first": order, "last": []}
    i = order.index(OTHER_FIELDS)
    return {"first": order[:i], "last": order[i + 1 :]}


FORMAT_SETTINGS: Dict[str, Setting] = {
    "sort_fields": Setting(False, "Reorder fields using field_order.", _bool),
    "field_order": Setting(
        None,
        "The order for sort_fields: first (fields at the top), then every unlisted field in "
        "source order, then last (fields at the bottom). Default: the order that add uses.",
        parse_field_order,
    ),
    "sort_entries": Setting(False, "Sort entries by citation key.", _bool),
    "keep_quotes": Setting(False, 'Keep "..." values and bare numbers.', _bool),
    "keep_outer_braces": Setting(False, "Keep values wrapped in extra braces ({{...}}).", _bool),
    "keep_months": Setting(False, "Don't turn months into macros (jun).", _bool),
    "keep_pages": Setting(False, "Don't turn page ranges into -- ranges.", _bool),
    "align": Setting(True, "Align '=' to the longest field name.", _bool),
    "indent": Setting(2, "Field indent: a number of spaces, or tab.", parse_indent),
    "blank_lines": Setting(1, "Blank lines between entries.", _count),
    "trailing_comma": Setting(False, "Put a comma after the last field.", _bool),
    "drop_empty": Setting(False, 'Remove fields with empty values ({} or "").', _bool),
}

# The settings of each section that this release reads.
SECTIONS: Dict[str, Dict[str, Setting]] = {FORMAT_SECTION: FORMAT_SETTINGS}


def parse_section(name: str, raw: Mapping[str, Any], where: str) -> Tuple[Dict[str, Any], List[str]]:
    """``(values, warnings)`` of one section; :class:`ConfigError` for an invalid value."""
    settings = SECTIONS.get(name, {})
    values: Dict[str, Any] = {}
    warnings: List[str] = []
    for key, value in raw.items():
        key = str(key)
        setting = settings.get(key)
        if setting is None:
            known = ", ".join(settings)
            warnings.append(f"{where}: {name}.{key} isn't a setting (ignored); the {name} settings are {known}")
            continue
        values[key] = setting.parse(value, f"{where}: {name}.{key}")
        if key == "field_order":
            warnings += field_order_warnings(values[key], f"{where}: {name}.{key}")
    return values, warnings


# ------------------------------------------------------------- loading


@dataclass
class ConfigFile:
    """One config file that a command reads."""

    scope: str
    path: Path
    data: Dict[str, Dict[str, Any]] = field(default_factory=dict)  # the YAML, as written

    @property
    def exists(self) -> bool:
        return self.path.is_file()

    @classmethod
    def load(cls, path: Path, scope: str) -> "ConfigFile":
        if not path.is_file():
            return cls(scope, path)
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as e:
            raise ConfigError(f"{path}: {e}") from e
        return cls(scope, path, parse_yaml(text, str(path)))

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(dump_yaml(self.data), encoding="utf-8")


@dataclass
class Config:
    """The merged view of the config files that apply to one input."""

    files: List[ConfigFile] = field(default_factory=list)  # read order: user, then project
    values: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    origins: Dict[str, Dict[str, str]] = field(default_factory=dict)  # section -> key -> scope
    warnings: List[str] = field(default_factory=list)

    def section(self, name: str) -> Dict[str, Any]:
        return dict(self.values.get(name, {}))

    def origin(self, name: str, key: str) -> str:
        return self.origins.get(name, {}).get(key, "default")

    @property
    def present(self) -> List[ConfigFile]:
        """The files that exist, in read order."""
        return [f for f in self.files if f.exists]

    def describe(self) -> str:
        """``user FILE + project FILE``, or ``built-in defaults``."""
        return " + ".join(f"{f.scope} {f.path}" for f in self.present) or "built-in defaults"

    def key(self) -> Tuple[str, ...]:
        """Identifies the files, so that inputs sharing them share one Config."""
        return tuple(str(f.path) for f in self.present)


def merge(files: Sequence[ConfigFile]) -> Config:
    """Validate and merge *files*; a later file wins where both set a key."""
    config = Config(files=list(files))
    for f in files:
        for name, raw in f.data.items():
            if name not in SECTIONS:
                config.warnings.append(
                    f"{f.path}: this release of BibCC doesn't read a {name}: section (ignored)")
                continue
            values, warnings = parse_section(name, raw, str(f.path))
            config.warnings += warnings
            config.values.setdefault(name, {}).update(values)
            config.origins.setdefault(name, {}).update({k: f.scope for k in values})
    return config


def load_config(
    config: Optional[str | Path] = None,
    start: Optional[str | Path] = None,
    use_files: bool = True,
) -> Config:
    """The config a command reads for an input at *start* (a ``.bib`` file or folder; default: cwd).

    With *config*, that file alone.  Without *use_files*, none (built-in
    defaults).  Otherwise the user config, then the nearest project config
    above *start*, merged.
    """
    if not use_files:
        return Config()
    if config:
        path = Path(config).expanduser()
        if not path.is_file():
            raise ConfigError(f"{path}: no such config file")
        return merge([ConfigFile.load(path, FILE_SCOPE)])
    files = [ConfigFile.load(user_config_path(), USER_SCOPE)]
    project = find_project_config(start)
    if project is not None:
        files.append(ConfigFile.load(project, PROJECT_SCOPE))
    return merge(files)


def merge_into(
    target: ConfigFile, incoming: Mapping[str, Mapping[str, Any]], overwrite: bool
) -> Tuple[Dict[str, int], List[Tuple[str, Any, Any]]]:
    """Merge the keys of *incoming* into *target*'s data.

    Returns ``({added, updated, unchanged}, [(section.key, kept, other)])``:
    a key that *target* sets to another value is kept unless *overwrite*.
    """
    counts = {"added": 0, "updated": 0, "unchanged": 0}
    differ: List[Tuple[str, Any, Any]] = []
    for name, section in incoming.items():
        mine = target.data.setdefault(name, {})
        for key, value in section.items():
            if key not in mine:
                mine[key] = value
                counts["added"] += 1
            elif mine[key] == value:
                counts["unchanged"] += 1
            elif overwrite:
                differ.append((f"{name}.{key}", value, mine[key]))
                mine[key] = value
                counts["updated"] += 1
            else:
                differ.append((f"{name}.{key}", mine[key], value))
                counts["unchanged"] += 1
    return counts, differ
