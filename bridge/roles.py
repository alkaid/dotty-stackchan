"""Persistent role library shared by Bridge and dotty-pi."""

from __future__ import annotations

import json
import os
import tempfile
import threading
import uuid
from pathlib import Path
from typing import Any, Callable


DEFAULT_PATH = Path("/var/lib/dotty-bridge/state/roles.json")
MAX_ROLES = 32
MAX_NAME_CHARS = 80
MAX_PROMPT_CHARS = 32_000
_LOCK = threading.Lock()


class RoleError(ValueError):
    pass


def roles_path() -> Path:
    return Path(os.environ.get("DOTTY_ROLES_FILE", str(DEFAULT_PATH)))


def default_prompt() -> str:
    fallback = Path(__file__).parent.parent / "personas" / "default.md"
    path = Path(os.environ.get("DOTTY_DEFAULT_ROLE_FILE", str(fallback)))
    try:
        prompt = path.read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise RoleError(f"Default role prompt is unavailable: {path}") from exc
    if not prompt:
        raise RoleError("Default role prompt is empty")
    return prompt


def _initial_state() -> dict[str, Any]:
    return {
        "version": 1,
        "active_role_id": "default",
        "roles": [{
            "id": "default",
            "name": "Dotty",
            "prompt": default_prompt(),
            "voice_id": "default",
        }],
    }


def _clean_role(raw: Any) -> dict[str, str]:
    if not isinstance(raw, dict):
        raise RoleError("Role entry must be an object")
    role_id = str(raw.get("id", "")).strip()
    name = str(raw.get("name", "")).strip()
    prompt = str(raw.get("prompt", "")).strip()
    voice_id = str(raw.get("voice_id", "default")).strip()
    if not role_id or len(role_id) > 80:
        raise RoleError("Role ID is invalid")
    if not name or len(name) > MAX_NAME_CHARS:
        raise RoleError(f"Role name must be 1-{MAX_NAME_CHARS} characters")
    if not prompt or len(prompt) > MAX_PROMPT_CHARS:
        raise RoleError(f"Role prompt must be 1-{MAX_PROMPT_CHARS:,} characters")
    if not voice_id or len(voice_id) > 80:
        raise RoleError("Role voice ID is invalid")
    return {
        "id": role_id,
        "name": name,
        "prompt": prompt,
        "voice_id": voice_id,
    }


def _validate_state(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise RoleError("Role store must be an object")
    raw_roles = raw.get("roles")
    if not isinstance(raw_roles, list) or not raw_roles:
        raise RoleError("Role store must contain at least one role")
    if len(raw_roles) > MAX_ROLES:
        raise RoleError(f"Role store supports at most {MAX_ROLES} roles")
    roles = [_clean_role(role) for role in raw_roles]
    ids = [role["id"] for role in roles]
    if len(set(ids)) != len(ids):
        raise RoleError("Role IDs must be unique")
    active = str(raw.get("active_role_id", "")).strip()
    if active not in ids:
        raise RoleError("Active role does not exist")
    return {"version": 1, "active_role_id": active, "roles": roles}


def read_roles(path: Path | None = None) -> dict[str, Any]:
    target = path or roles_path()
    try:
        raw = json.loads(target.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return _initial_state()
    except (OSError, json.JSONDecodeError) as exc:
        raise RoleError(f"Unable to read role store: {target}") from exc
    return _validate_state(raw)


def _write_roles(state: dict[str, Any], target: Path) -> None:
    payload = _validate_state(state)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{target.name}.", suffix=".tmp", dir=target.parent,
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
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


def _mutate(
    change: Callable[[dict[str, Any]], None], path: Path | None = None,
) -> dict[str, Any]:
    target = path or roles_path()
    with _LOCK:
        state = read_roles(target)
        change(state)
        _write_roles(state, target)
        return state


def create_role(
    name: str,
    prompt: str,
    voice_id: str = "default",
    path: Path | None = None,
) -> dict[str, Any]:
    role = _clean_role({
        "id": uuid.uuid4().hex,
        "name": name,
        "prompt": prompt,
        "voice_id": voice_id,
    })

    def change(state: dict[str, Any]) -> None:
        if len(state["roles"]) >= MAX_ROLES:
            raise RoleError(f"Role store supports at most {MAX_ROLES} roles")
        state["roles"].append(role)

    return _mutate(change, path)


def update_role(
    role_id: str,
    name: str,
    prompt: str,
    voice_id: str = "default",
    path: Path | None = None,
) -> dict[str, Any]:
    updated = _clean_role({
        "id": role_id,
        "name": name,
        "prompt": prompt,
        "voice_id": voice_id,
    })

    def change(state: dict[str, Any]) -> None:
        for index, role in enumerate(state["roles"]):
            if role["id"] == role_id:
                state["roles"][index] = updated
                return
        raise RoleError("Role not found")

    return _mutate(change, path)


def activate_role(role_id: str, path: Path | None = None) -> dict[str, Any]:
    def change(state: dict[str, Any]) -> None:
        if not any(role["id"] == role_id for role in state["roles"]):
            raise RoleError("Role not found")
        state["active_role_id"] = role_id

    return _mutate(change, path)


def delete_role(role_id: str, path: Path | None = None) -> dict[str, Any]:
    def change(state: dict[str, Any]) -> None:
        if state["active_role_id"] == role_id:
            raise RoleError("Activate another role before deleting this one")
        remaining = [role for role in state["roles"] if role["id"] != role_id]
        if len(remaining) == len(state["roles"]):
            raise RoleError("Role not found")
        if not remaining:
            raise RoleError("At least one role is required")
        state["roles"] = remaining

    return _mutate(change, path)
