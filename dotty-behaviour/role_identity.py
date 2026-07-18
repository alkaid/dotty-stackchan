"""Resolve the active Bridge Role name for autonomous mode prompts."""

from __future__ import annotations

import json
import os
from pathlib import Path


DEFAULT_ROLES_PATH = Path("/var/lib/dotty-bridge/state/roles.json")


def configured_robot_name() -> str:
    name = os.environ.get("ROBOT_NAME", "Dotty").strip()
    if not name or len(name) > 80 or any(ord(char) < 32 for char in name):
        return "Dotty"
    return name


def active_role_name(path: str | Path | None = None) -> str:
    configured_name = configured_robot_name()
    target = Path(path) if path is not None else Path(
        os.environ.get("DOTTY_ROLES_FILE", str(DEFAULT_ROLES_PATH))
    )
    try:
        state = json.loads(target.read_text(encoding="utf-8"))
        role = next(
            item for item in state["roles"]
            if item["id"] == state["active_role_id"]
        )
        name = str(role.get("name") or "").strip()
        if role.get("id") == "default" and name.casefold() == "dotty":
            return configured_name
        if name and len(name) <= 80 and not any(ord(char) < 32 for char in name):
            return name
    except (OSError, json.JSONDecodeError, KeyError, TypeError, StopIteration):
        pass
    return configured_name


def wake_phrase(path: str | Path | None = None) -> str:
    return f"hi, {active_role_name(path)}"
