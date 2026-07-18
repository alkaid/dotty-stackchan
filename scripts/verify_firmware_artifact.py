#!/usr/bin/env python3
"""Reject firmware artifacts built with stale version or OTA metadata."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


UPSTREAM_OTA_URL = "https://api.tenclass.net/xiaozhi/ota/"


def verify_artifact(
    binary_path: Path,
    project_description_path: Path,
    expected_ota_url: str,
) -> str:
    expected_ota_url = expected_ota_url.strip()
    if not expected_ota_url.endswith("/xiaozhi/ota/"):
        raise ValueError(
            "expected OTA URL must end with /xiaozhi/ota/: "
            f"{expected_ota_url!r}"
        )
    if expected_ota_url == UPSTREAM_OTA_URL:
        raise ValueError("refusing to publish firmware pointed at the upstream OTA service")

    metadata = json.loads(project_description_path.read_text(encoding="utf-8"))
    version = str(metadata.get("project_version") or "").strip()
    if not version:
        raise ValueError("project_description.json has no project_version")

    binary = binary_path.read_bytes()
    if expected_ota_url.encode() not in binary:
        raise ValueError(
            f"firmware does not contain expected OTA URL {expected_ota_url!r}"
        )
    if UPSTREAM_OTA_URL.encode() in binary:
        raise ValueError("firmware still contains the upstream OTA service URL")
    if version.encode() not in binary:
        raise ValueError(f"firmware does not contain project version {version!r}")

    return version


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--project-description", type=Path, required=True)
    parser.add_argument("--expected-ota-url", required=True)
    args = parser.parse_args()

    version = verify_artifact(
        args.binary,
        args.project_description,
        args.expected_ota_url,
    )
    print(
        f"Verified firmware {version}: "
        f"OTA endpoint {args.expected_ota_url.strip()}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
