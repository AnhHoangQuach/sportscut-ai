"""Which model provider `codex exec` uses, and the key it needs.

Codex can talk to a custom provider instead of the ChatGPT login, e.g. the open-source codex-lb
proxy (`model_provider = "codex-lb"` in ~/.codex/config.toml, `env_key = "CODEX_LB_API_KEY"`).
Codex then reads that key from its environment and stops with
"Missing environment variable: `CODEX_LB_API_KEY`" when it is not there. The office reads the same
config to pass that variable through, to load it from `.agent-office/.env`, and to tell the user
exactly what is missing (an environment problem, not quota and not a broken CLI).
"""
from __future__ import annotations

import os
import re
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

# The codex error when the provider's env_key is unset (codex-rs EnvVarError).
_MISSING_ENV = re.compile(r"Missing environment variable:?\s*`?([A-Za-z_][A-Za-z0-9_]*)`?")
_ENV_LINE = re.compile(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*?)\s*$")


@dataclass
class ProviderInfo:
    name: str = "openai"   # built-in ChatGPT login unless config.toml says otherwise
    env_key: str = ""      # environment variable that holds the provider's API key ("" = none)
    base_url: str = ""
    config_path: str = ""
    error: str = ""        # config.toml exists but could not be read


def codex_home(env: Mapping[str, str] | None = None) -> Path:
    env = os.environ if env is None else env
    return Path(env.get("CODEX_HOME") or Path.home() / ".codex").expanduser()


def provider_info(env: Mapping[str, str] | None = None) -> ProviderInfo:
    path = codex_home(env) / "config.toml"
    if not path.is_file():
        return ProviderInfo()
    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as e:
        return ProviderInfo(config_path=str(path), error=str(e))
    name = str(raw.get("model_provider") or "openai")
    profile = (raw.get("profiles") or {}).get(str(raw.get("profile") or "")) or {}
    if isinstance(profile, dict) and profile.get("model_provider"):
        name = str(profile["model_provider"])  # `profile = "x"` + [profiles.x] model_provider wins
    prov = (raw.get("model_providers") or {}).get(name) or {}
    if not isinstance(prov, dict):
        prov = {}
    return ProviderInfo(name=name, env_key=str(prov.get("env_key") or ""),
                        base_url=str(prov.get("base_url") or ""), config_path=str(path))


def read_env_file(path: Path | str | None) -> dict[str, str]:
    """KEY=value lines (optional `export`, quotes, # comments). A missing file is empty."""
    if not path:
        return {}
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError:
        return {}
    out: dict[str, str] = {}
    for line in text.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        m = _ENV_LINE.match(line)
        if not m:
            continue
        value = m.group(2)
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
            value = value[1:-1]
        out[m.group(1)] = value
    return out


def missing_env_var(output: str) -> str:
    """The variable codex says is missing, or ""."""
    m = _MISSING_ENV.search(output or "")
    return m.group(1) if m else ""
