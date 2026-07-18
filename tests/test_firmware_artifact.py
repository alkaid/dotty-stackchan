from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).parents[1]
SCRIPT = ROOT / "scripts" / "verify_firmware_artifact.py"
SPEC = importlib.util.spec_from_file_location("verify_firmware_artifact", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
verify_firmware_artifact = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(verify_firmware_artifact)


DOTTY_OTA_URL = "http://ota.example.test:8003/xiaozhi/ota/"


def _artifact(tmp_path: Path, *, version: str, contents: bytes) -> tuple[Path, Path]:
    binary = tmp_path / "stack-chan.bin"
    binary.write_bytes(contents)
    description = tmp_path / "project_description.json"
    description.write_text(json.dumps({"project_version": version}), encoding="utf-8")
    return binary, description


def test_accepts_matching_dotty_ota_url_and_version(tmp_path: Path) -> None:
    binary, description = _artifact(
        tmp_path,
        version="1.4.5",
        contents=b"app\x001.4.5\x00" + DOTTY_OTA_URL.encode() + b"\x00",
    )

    version = verify_firmware_artifact.verify_artifact(
        binary, description, DOTTY_OTA_URL
    )

    assert version == "1.4.5"


def test_rejects_upstream_ota_url(tmp_path: Path) -> None:
    upstream = verify_firmware_artifact.UPSTREAM_OTA_URL
    binary, description = _artifact(
        tmp_path,
        version="1.4.5",
        contents=b"app\x001.4.5\x00" + upstream.encode() + b"\x00",
    )

    with pytest.raises(ValueError, match="upstream OTA service"):
        verify_firmware_artifact.verify_artifact(binary, description, upstream)


def test_rejects_binary_without_expected_ota_url(tmp_path: Path) -> None:
    binary, description = _artifact(
        tmp_path,
        version="1.4.5",
        contents=b"app\x001.4.5\x00https://wrong.example/xiaozhi/ota/\x00",
    )

    with pytest.raises(ValueError, match="does not contain expected OTA URL"):
        verify_firmware_artifact.verify_artifact(
            binary, description, DOTTY_OTA_URL
        )


def test_makefile_forwards_ota_url_and_reconfigures_before_build() -> None:
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")

    assert '-e XIAOZHI_PUBLIC_OTA_BASE_URL="$$ota_base_url"' in makefile
    assert "idf.py reconfigure && idf.py build" in makefile
    assert "scripts/verify_firmware_artifact.py" in makefile
