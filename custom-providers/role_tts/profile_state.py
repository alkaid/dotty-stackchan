"""Read the active role's voice profile from shared JSON state."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


DEFAULT_PROFILE: dict[str, Any] = {
    "id": "default",
    "name": "Default EdgeTTS - Xiaoxiao",
    "provider": "edge",
    "config": {
        "voice": "zh-CN-XiaoxiaoNeural",
        "rate": "+0%",
        "volume": "+0%",
        "pitch": "+0Hz",
    },
}


def _read_json(path: str) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def load_active_voice(
    roles_path: str,
    voices_path: str,
    fallback: dict[str, Any] | None = None,
) -> dict[str, Any]:
    default = fallback or DEFAULT_PROFILE
    try:
        roles_state = _read_json(roles_path)
        voices_state = _read_json(voices_path)
        active_id = roles_state["active_role_id"]
        role = next(role for role in roles_state["roles"] if role["id"] == active_id)
        voice_id = role.get("voice_id", "default")
        return next(
            voice for voice in voices_state["voices"] if voice["id"] == voice_id
        )
    except (OSError, ValueError, KeyError, TypeError, StopIteration):
        return default
