"""Configuration defaults and environment override behaviour."""

from __future__ import annotations

import os
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
