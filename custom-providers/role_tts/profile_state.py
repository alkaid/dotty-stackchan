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
        voices_state = _read_json(voices_path)
        voices = voices_state["voices"]
        if not isinstance(voices, list):
            return default
    except (OSError, ValueError, KeyError, TypeError):
        return default

    voice_id = "default"
    try:
        roles_state = _read_json(roles_path)
        active_id = roles_state["active_role_id"]
        role = next(role for role in roles_state["roles"] if role["id"] == active_id)
        voice_id = role.get("voice_id") or "default"
    except (OSError, ValueError, KeyError, TypeError, StopIteration):
        pass

    for candidate_id in dict.fromkeys((voice_id, "default")):
        for voice in voices:
            if isinstance(voice, dict) and voice.get("id") == candidate_id:
                return voice
    return default
