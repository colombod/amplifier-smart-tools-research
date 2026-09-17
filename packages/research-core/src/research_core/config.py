"""Settings, and where each one came from.

Four tiers, most explicit first: an explicit argument, the config file, an
environment variable, the built-in default.

The config file sits ABOVE the environment. A deployment that wrote a config file
is entitled to have it honoured; an environment variable can arrive by accident
from a parent process. An explicit argument still beats both, because it is the
only tier someone typed on purpose for this invocation.

Resolution returns which tier won, not merely a value. Four places a value can
come from and no way to ask which one answered would be a debugging liability
rather than a feature.

TOML has no null. The specification-shaped trichotomy of absent / explicitly-null
/ wrong-type therefore collapses to two cases here: a key absent falls through to
the next tier, and a key present with the wrong type is fatal. Saying "no opinion"
is spelled by omitting the key, and that is stated in the documentation rather
than left for someone to discover.
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from research_core.errors import ConfigInvalidError

#: Where the config file lives, and the variable that moves it. The path is
#: itself an environment setting because a deployment or a test must be able to
#: pin a config without touching the user's own.
CONFIG_PATH_ENV_VAR = "RESEARCH_CONFIG"
DEFAULT_CONFIG_PATH = "~/.config/amplifier-research/config.toml"

SOURCE_ARGUMENT = "argument"
SOURCE_CONFIG_FILE = "config-file"
SOURCE_ENVIRONMENT = "environment"
SOURCE_DEFAULT = "default"

#: Most explicit first. Published so a caller can report it without hard-coding it.
RESOLUTION_ORDER = (
    SOURCE_ARGUMENT,
    SOURCE_CONFIG_FILE,
    SOURCE_ENVIRONMENT,
    SOURCE_DEFAULT,
)


@dataclass(frozen=True)
class Setting:
    """One configurable setting: its name, type, default and environment variable."""

    name: str
    type: type
    default: Any
    env_var: str
    description: str
    choices: tuple[str, ...] | None = None


def _default_runs_dir() -> str:
    state = os.environ.get("XDG_STATE_HOME") or "~/.local/state"
    return str(Path(state).expanduser() / "amplifier-research" / "runs")


def _default_engine_home() -> str:
    """Whatever the embedded engine would have used anyway.

    Imported lazily, and from the engine module, so the default cannot drift
    from what the engine actually does -- the same mistake in two files is the
    one this project has already made four times. The lazy import is the usual
    rule: nothing here may pull the agent engine in at module level.
    """
    from research_core.engine import default_engine_home

    return str(default_engine_home())


#: Every setting a caller may set. Shared by both tools: a deployment configures
#: the pair once, and nothing here is per-tool.
SETTINGS: tuple[Setting, ...] = (
    Setting(
        "runs_dir",
        str,
        None,  # computed at resolution time so XDG_STATE_HOME is read live
        "RESEARCH_RUNS_DIR",
        "Where runs are written. Point several callers at one directory and "
        "evidence accumulates; nothing reaps it.",
    ),
    Setting(
        "engine_home",
        str,
        None,  # computed at resolution time from what the engine itself defaults to
        "RESEARCH_ENGINE_HOME",
        "Where the embedded engine keeps its cache, module clones and per-turn "
        "working directories. Everything this tool writes outside the runs "
        "directory goes here, so a host that confines writes has exactly two "
        "paths to point somewhere it allows. Hundreds of megabytes, and worth "
        "keeping between runs.",
    ),
    Setting(
        "backend",
        str,
        "perplexity",
        "RESEARCH_BACKEND",
        "Which backend acquires evidence.",
    ),
    Setting(
        "depth",
        str,
        "medium",
        "RESEARCH_DEPTH",
        "How hard a run works before it reports.",
        choices=("low", "medium", "high"),
    ),
    Setting(
        "provider",
        str,
        None,
        "RESEARCH_PROVIDER",
        "Which model provider backs the reasoning stages. Unset means the first "
        "provider that resolves.",
    ),
    Setting(
        "model",
        str,
        None,
        "RESEARCH_MODEL",
        "Which model to use. Unset means the provider's own default.",
    ),
    Setting(
        "host_config",
        str,
        None,
        "RESEARCH_HOST_CONFIG",
        "Opt in to reading a HOST application's configuration for a model "
        "credential. Unset means never -- a smart tool is consumable from any "
        "host, and one that silently reads a particular host's private config "
        "file has quietly become that host's tool. Accepts 'amplifier' or a "
        "path. Only the model provider can be satisfied this way.",
    ),
    Setting(
        "max_read_lines",
        int,
        5000,
        "RESEARCH_MAX_READ_LINES",
        "The ceiling on a single bounded read. A request above it is refused "
        "rather than silently capped.",
    ),
    Setting(
        "max_attempts",
        int,
        3,
        "RESEARCH_MAX_ATTEMPTS",
        "How many times a stage may be repaired before the run fails carrying every attempt.",
    ),
    Setting(
        "timeout_ms",
        int,
        600_000,
        "RESEARCH_TIMEOUT_MS",
        "Wall-clock budget for one model-backed run. Exceeding it fails rather "
        "than returning a partial answer.",
    ),
)

_BY_NAME = {s.name: s for s in SETTINGS}


@dataclass(frozen=True)
class Resolved:
    """A setting's value and the tier that supplied it."""

    name: str
    value: Any
    source: str
    detail: str

    def to_dict(self) -> dict[str, Any]:
        return {"value": self.value, "source": self.source, "detail": self.detail}


@dataclass(frozen=True)
class Settings:
    """Every setting, resolved, with provenance and with what was ignored."""

    resolved: dict[str, Resolved]
    config_path: Path
    config_path_exists: bool
    ignored: tuple[str, ...] = ()

    def __getitem__(self, name: str) -> Any:
        return self.resolved[name].value

    def source_of(self, name: str) -> str:
        return self.resolved[name].source

    def to_dict(self) -> dict[str, Any]:
        return {
            "settings": {n: r.to_dict() for n, r in self.resolved.items()},
            "config_path": str(self.config_path),
            "config_path_exists": self.config_path_exists,
            "ignored": list(self.ignored),
        }


def config_path() -> Path:
    """Where the config file is expected, honouring the override variable."""
    return Path(os.environ.get(CONFIG_PATH_ENV_VAR, DEFAULT_CONFIG_PATH)).expanduser()


def _read_config_file(path: Path) -> dict[str, Any]:
    """Read the config file. Present-but-broken is fatal, never a fall-through."""
    if not path.exists():
        return {}
    try:
        with path.open("rb") as handle:
            raw = tomllib.load(handle)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise ConfigInvalidError(
            f"The config file at {path} could not be read: {exc}",
            "Fix the file, or move it aside. A caller with a config file present "
            "is entitled to have it honoured or to be told plainly that it is "
            "broken, never to be silently handed a default.",
        ) from exc

    unknown = sorted(set(raw) - set(_BY_NAME))
    if unknown:
        raise ConfigInvalidError(
            f"The config file at {path} sets settings that do not exist: {', '.join(unknown)}.",
            "A setting nobody reads is a setting whose author believes something "
            f"untrue. Known settings: {', '.join(sorted(_BY_NAME))}.",
        )
    return raw


def _coerce(setting: Setting, value: Any, where: str) -> Any:
    """Validate a value's type and membership. Wrong is fatal, never ignored."""
    if setting.type is int:
        # bool is an int in Python, and "true" is not a line count.
        if isinstance(value, bool) or not isinstance(value, int):
            raise ConfigInvalidError(
                f"{setting.name} in {where} must be an integer, got "
                f"{type(value).__name__} ({value!r}).",
                f"Set {setting.name} to a whole number.",
            )
    elif not isinstance(value, str):
        raise ConfigInvalidError(
            f"{setting.name} in {where} must be a string, got {type(value).__name__} ({value!r}).",
            f"Set {setting.name} to a string.",
        )

    if setting.choices and value not in setting.choices:
        raise ConfigInvalidError(
            f"{setting.name} in {where} must be one of "
            f"{', '.join(setting.choices)}, got {value!r}.",
            f"Choose one of: {', '.join(setting.choices)}.",
        )
    return value


def _from_environment(setting: Setting) -> Any | None:
    raw = os.environ.get(setting.env_var)
    if raw is None or raw.strip() == "":
        return None
    text = raw.strip()
    if setting.type is int:
        try:
            return _coerce(setting, int(text), f"${setting.env_var}")
        except ValueError as exc:
            raise ConfigInvalidError(
                f"${setting.env_var} must be an integer, got {text!r}.",
                f"Set {setting.env_var} to a whole number, or unset it.",
            ) from exc
    return _coerce(setting, text, f"${setting.env_var}")


def resolve_settings(**arguments: Any) -> Settings:
    """Resolve every setting, most explicit tier first, recording provenance.

    Keyword arguments are the explicit tier; a value of ``None`` means the caller
    did not supply one, which is how an unset CLI flag arrives.
    """
    unknown = sorted(set(arguments) - set(_BY_NAME))
    if unknown:
        raise ConfigInvalidError(
            f"No such setting: {', '.join(unknown)}.",
            f"Known settings: {', '.join(sorted(_BY_NAME))}.",
        )

    path = config_path()
    exists = path.exists()
    file_values = _read_config_file(path)

    resolved: dict[str, Resolved] = {}
    ignored: list[str] = []

    for setting in SETTINGS:
        argument = arguments.get(setting.name)
        in_file = setting.name in file_values
        in_env = _from_environment(setting) is not None

        if argument is not None:
            value = _coerce(setting, argument, "the command line")
            resolved[setting.name] = Resolved(
                setting.name, value, SOURCE_ARGUMENT, "passed on this invocation"
            )
            # Say what was seen and not honoured, rather than letting it vanish.
            if in_file:
                ignored.append(
                    f"{setting.name} is set in {path} but an explicit argument "
                    "was given on this invocation"
                )
            if in_env:
                ignored.append(
                    f"${setting.env_var} is set but an explicit argument was "
                    "given on this invocation"
                )
            continue

        if in_file:
            value = _coerce(setting, file_values[setting.name], str(path))
            resolved[setting.name] = Resolved(
                setting.name, value, SOURCE_CONFIG_FILE, f"{setting.name} in {path}"
            )
            if in_env:
                ignored.append(
                    f"${setting.env_var} is set but {path} sets {setting.name}, "
                    "and the config file is the more deliberate of the two"
                )
            continue

        from_env = _from_environment(setting)
        if from_env is not None:
            resolved[setting.name] = Resolved(
                setting.name, from_env, SOURCE_ENVIRONMENT, f"${setting.env_var}"
            )
            continue

        computed = {"runs_dir": _default_runs_dir, "engine_home": _default_engine_home}
        factory = computed.get(setting.name)
        default = factory() if factory else setting.default
        resolved[setting.name] = Resolved(setting.name, default, SOURCE_DEFAULT, "built-in default")

    return Settings(
        resolved=resolved,
        config_path=path,
        config_path_exists=exists,
        ignored=tuple(ignored),
    )


def effective_configuration(**arguments: Any) -> dict[str, Any]:
    """Everything the `config` verb reports: settings, provenance, credential tiers.

    Safe to print in full. Credential surfaces report the tier that satisfied
    them and nothing else.
    """
    from research_core import credentials as _credentials

    document = resolve_settings(**arguments).to_dict()
    document["credentials"] = {
        surface: status.to_dict() for surface, status in _credentials.all_status().items()
    }
    document["credentials_path"] = str(_credentials.credentials_path())
    document["resolution_order"] = list(RESOLUTION_ORDER)
    return document
