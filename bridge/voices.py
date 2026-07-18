"""Persistent named TTS voice profiles."""

from __future__ import annotations

import json
import os
import re
import tempfile
import threading
import uuid
from pathlib import Path
from typing import Any, Callable


DEFAULT_PATH = Path("/var/lib/dotty-bridge/state/voices.json")
DEFAULT_EDGE_VOICE = "zh-CN-XiaoxiaoNeural"
MAX_VOICES = 32
MAX_NAME_CHARS = 80
_LOCK = threading.Lock()
_PERCENT_RE = re.compile(r"^[+-](?:\d|[1-9]\d|100)%$")
_PITCH_RE = re.compile(r"^[+-](?:\d{1,3}|1000)Hz$")
_EDGE_VOICE_RE = re.compile(r"^[A-Za-z0-9-]{4,80}Neural$")


class VoiceError(ValueError):
    pass


def voices_path() -> Path:
    return Path(os.environ.get("DOTTY_VOICES_FILE", str(DEFAULT_PATH)))


def default_voice() -> dict[str, Any]:
    return {
        "id": "default",
        "name": "Default EdgeTTS - Xiaoxiao",
        "provider": "edge",
        "config": {
            "voice": DEFAULT_EDGE_VOICE,
            "rate": "+0%",
            "volume": "+0%",
            "pitch": "+0Hz",
        },
    }


def _initial_state() -> dict[str, Any]:
    return {"version": 1, "voices": [default_voice()]}


def _number(
    raw: Any, label: str, minimum: float, maximum: float, *, integer: bool = False,
) -> int | float:
    try:
        value = int(raw) if integer else float(raw)
    except (TypeError, ValueError) as exc:
        raise VoiceError(f"{label} must be a number") from exc
    if value < minimum or value > maximum:
        raise VoiceError(f"{label} must be between {minimum:g} and {maximum:g}")
    return value


def _short_text(raw: Any, label: str, max_chars: int = 300) -> str:
    value = str(raw or "").strip()
    if not value or len(value) > max_chars or any(ord(char) < 32 for char in value):
        raise VoiceError(f"{label} must be 1-{max_chars} printable characters")
    return value


def _clean_config(provider: str, raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise VoiceError("Voice config must be an object")
    if provider == "chattts":
        return {
            "seed": _number(raw.get("seed", 42), "Seed", 0, 2_147_483_647, integer=True),
            "temperature": _number(raw.get("temperature", 0.3), "Temperature", 0.01, 2),
            "top_p": _number(raw.get("top_p", 0.7), "Top P", 0.01, 1),
            "top_k": _number(raw.get("top_k", 20), "Top K", 1, 100, integer=True),
            "gain_db": _number(raw.get("gain_db", 3.0), "Output gain", -12, 12),
            "refine_prompt": _short_text(
                raw.get("refine_prompt", "[oral_2][laugh_0][break_4]"),
                "Refine prompt",
            ),
            "code_prompt": _short_text(
                raw.get("code_prompt", "[speed_5]"), "Code prompt",
            ),
        }
    if provider == "edge":
        voice = _short_text(raw.get("voice", DEFAULT_EDGE_VOICE), "Edge voice", 100)
        rate = _short_text(raw.get("rate", "+0%"), "Rate", 8)
        volume = _short_text(raw.get("volume", "+0%"), "Volume", 8)
        pitch = _short_text(raw.get("pitch", "+0Hz"), "Pitch", 10)
        if not _EDGE_VOICE_RE.fullmatch(voice):
            raise VoiceError("Edge voice must look like en-AU-WilliamNeural")
        if not _PERCENT_RE.fullmatch(rate):
            raise VoiceError("Rate must be between -100% and +100%")
        if not _PERCENT_RE.fullmatch(volume):
            raise VoiceError("Volume must be between -100% and +100%")
        if not _PITCH_RE.fullmatch(pitch):
            raise VoiceError("Pitch must be between -1000Hz and +1000Hz")
        return {"voice": voice, "rate": rate, "volume": volume, "pitch": pitch}
    raise VoiceError("Voice provider must be ChatTTS or EdgeTTS")


def clean_voice(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise VoiceError("Voice entry must be an object")
    voice_id = str(raw.get("id", "")).strip()
    name = _short_text(raw.get("name"), "Voice name", MAX_NAME_CHARS)
    provider = str(raw.get("provider", "")).strip().lower()
    if not voice_id or len(voice_id) > 80:
        raise VoiceError("Voice ID is invalid")
    return {
        "id": voice_id,
        "name": name,
        "provider": provider,
        "config": _clean_config(provider, raw.get("config")),
    }


def _validate_state(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise VoiceError("Voice store must be an object")
    raw_voices = raw.get("voices")
    if not isinstance(raw_voices, list) or not raw_voices:
        raise VoiceError("Voice store must contain at least one voice")
    if len(raw_voices) > MAX_VOICES:
        raise VoiceError(f"Voice store supports at most {MAX_VOICES} voices")
    voices = [clean_voice(voice) for voice in raw_voices]
    ids = [voice["id"] for voice in voices]
    if len(set(ids)) != len(ids):
        raise VoiceError("Voice IDs must be unique")
    return {"version": 1, "voices": voices}


def read_voices(path: Path | None = None) -> dict[str, Any]:
    target = path or voices_path()
    try:
        raw = json.loads(target.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return _initial_state()
    except (OSError, json.JSONDecodeError) as exc:
        raise VoiceError(f"Unable to read voice store: {target}") from exc
    return _validate_state(raw)


def _write_voices(state: dict[str, Any], target: Path) -> None:
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
    target = path or voices_path()
    with _LOCK:
        state = read_voices(target)
        change(state)
        _write_voices(state, target)
        return state


def create_voice(
    name: str, provider: str, config: dict[str, Any], path: Path | None = None,
) -> dict[str, Any]:
    voice = clean_voice({
        "id": uuid.uuid4().hex,
        "name": name,
        "provider": provider,
        "config": config,
    })

    def change(state: dict[str, Any]) -> None:
        if len(state["voices"]) >= MAX_VOICES:
            raise VoiceError(f"Voice store supports at most {MAX_VOICES} voices")
        state["voices"].append(voice)

    return _mutate(change, path)


def update_voice(
    voice_id: str,
    name: str,
    provider: str,
    config: dict[str, Any],
    path: Path | None = None,
) -> dict[str, Any]:
    updated = clean_voice({
        "id": voice_id,
        "name": name,
        "provider": provider,
        "config": config,
    })

    def change(state: dict[str, Any]) -> None:
        for index, voice in enumerate(state["voices"]):
            if voice["id"] == voice_id:
                state["voices"][index] = updated
                return
        raise VoiceError("Voice not found")

    return _mutate(change, path)


def delete_voice(voice_id: str, path: Path | None = None) -> dict[str, Any]:
    def change(state: dict[str, Any]) -> None:
        remaining = [voice for voice in state["voices"] if voice["id"] != voice_id]
        if len(remaining) == len(state["voices"]):
            raise VoiceError("Voice not found")
        if not remaining:
            raise VoiceError("At least one voice is required")
        state["voices"] = remaining

    return _mutate(change, path)
