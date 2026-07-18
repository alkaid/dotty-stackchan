#!/usr/bin/env python3
"""Advance the firmware PROJECT_VER before a release build."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import re
import stat
import tempfile


PROJECT_VERSION_RE = re.compile(
    r'^(?P<prefix>\s*set\(PROJECT_VER\s+")'
    r'(?P<version>\d+\.\d+\.\d+)'
    r'(?P<suffix>"\)\s*)$',
    re.MULTILINE,
)


def _parse_version(value: str) -> tuple[int, int, int]:
    if not re.fullmatch(r"\d+\.\d+\.\d+", value):
        raise ValueError(f"firmware version must be MAJOR.MINOR.PATCH: {value!r}")
    return tuple(int(part) for part in value.split("."))  # type: ignore[return-value]


def bump_project_version(path: Path, requested: str | None = None) -> str:
    source = path.read_text(encoding="utf-8")
    matches = list(PROJECT_VERSION_RE.finditer(source))
    if len(matches) != 1:
        raise ValueError(
            f"expected one PROJECT_VER in {path}, found {len(matches)}"
        )

    match = matches[0]
    current = _parse_version(match.group("version"))
    if requested is None:
        target = (current[0], current[1], current[2] + 1)
    else:
        target = _parse_version(requested)
        if target <= current:
            raise ValueError(
                f"requested firmware version {requested} must exceed "
                f"{match.group('version')}"
            )
    version = ".".join(str(part) for part in target)
    updated = (
        source[: match.start("version")]
        + version
        + source[match.end("version") :]
    )

    mode = stat.S_IMODE(path.stat().st_mode)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(updated)
        os.chmod(temporary, mode)
        os.replace(temporary, path)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
    return version


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--path",
        type=Path,
        default=Path("firmware/firmware/CMakeLists.txt"),
    )
    parser.add_argument(
        "--version",
        help="Explicit next version; defaults to incrementing PATCH",
    )
    args = parser.parse_args()
    print(bump_project_version(args.path, args.version))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
