"""Persistent runtime configuration shared by bridge-managed services."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any, Mapping


CONFIG_KEYS = (
    "DOTTY_PI_MODEL",
    "DOTTY_PI_SIMPLE_REASONING",
    "DOTTY_PI_SIMPLE_REASONING_EFFORT",
    "VOICE_THINKER_MODEL",
    "DOTTY_PI_THINK_REASONING_EFFORT",
    "XIAOZHI_PUBLIC_WS_BASE_URL",
    "XIAOZHI_PUBLIC_OTA_BASE_URL",
    "IDLE_PHOTOGRAPHER_ENABLED",
)

DEFAULT_PATH = Path("/var/lib/dotty-bridge/state/runtime-config.json")


def config_path() -> Path:
    return Path(os.environ.get("DOTTY_RUNTIME_CONFIG_FILE", str(DEFAULT_PATH)))


def read_overrides(path: Path | None = None) -> dict[str, str]:
    target = path or config_path()
    try:
        raw = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(raw, dict):
        return {}
    return {
        key: value
        for key, value in raw.items()
        if key in CONFIG_KEYS and isinstance(value, str)
    }


def effective_config(
    defaults: Mapping[str, str], path: Path | None = None,
) -> dict[str, str]:
    values = {key: str(defaults.get(key, "")) for key in CONFIG_KEYS}
    values.update(read_overrides(path))
    return values


def write_overrides(values: Mapping[str, Any], path: Path | None = None) -> None:
    target = path or config_path()
    payload = {
        key: str(values[key])
        for key in CONFIG_KEYS
        if key in values
    }
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{target.name}.", suffix=".tmp", dir=target.parent,
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, target)
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise
