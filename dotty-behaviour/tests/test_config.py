"""Configuration defaults and environment override behaviour."""

from __future__ import annotations

import os
import json
from pathlib import Path
import subprocess
import sys


def _read_vlm_models(*, env: dict[str, str] | None = None) -> tuple[str, str]:
    process_env = os.environ.copy()
    process_env.pop("VISION_MODEL", None)
    process_env.pop("VLM_MODEL", None)
    if env:
        process_env.update(env)

    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import config; print(config.VISION_MODEL); print(config.VLM_MODEL)",
        ],
        cwd=Path(__file__).resolve().parents[1],
        env=process_env,
        check=True,
        capture_output=True,
        text=True,
    )
    vision_model, vlm_model = result.stdout.splitlines()
    return vision_model, vlm_model


def test_vision_defaults_to_live_low_latency_multimodal_model() -> None:
    assert _read_vlm_models() == (
        "google/gemini-3.1-flash-lite",
        "google/gemini-3.1-flash-lite",
    )


def test_idle_photographer_runtime_override_is_live(tmp_path: Path) -> None:
    runtime = tmp_path / "runtime-config.json"
    runtime.write_text(
        json.dumps({"IDLE_PHOTOGRAPHER_ENABLED": "false"}),
        encoding="utf-8",
    )
    process_env = os.environ.copy()
    process_env.update({
        "DOTTY_RUNTIME_CONFIG_FILE": str(runtime),
        "IDLE_PHOTOGRAPHER_ENABLED": "true",
    })
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import config; print(config.idle_photographer_enabled())",
        ],
        cwd=Path(__file__).resolve().parents[1],
        env=process_env,
        check=True,
        capture_output=True,
        text=True,
    )
    assert result.stdout.strip() == "False"
