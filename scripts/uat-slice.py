#!/usr/bin/env python3
"""Slice UAT session recordings into per-check clips — companion to
docs/uat-runbook.md.

Reads the session results CSV (check_id, verdict, source, start, end, note;
times are wall-clock HH:MM:SS) and cuts each row's window out of the matching
source video. The wall-clock → video-time mapping comes from the on-camera
sync mark: for each video you pass the video timestamp at which the sync mark
happened and the wall-clock time Brett read aloud.

PASS clips land in <out>/shorts/, everything else in <out>/issues/, named
<date>-<check_id>-<verdict>-<source>.mp4.

Usage:
  python scripts/uat-slice.py uat-sessions/2026-07-12/results.csv \
      --video phone=uat-sessions/2026-07-12/video/IMG_1234.mp4 \
      --sync  phone=00:03:12@14:02:10 \
      --video screen=uat-sessions/2026-07-12/video/dashboard.mkv \
      --sync  screen=00:00:45@14:02:10 \
      --out   uat-sessions/2026-07-12/clips

Options:
  --pad N       seconds of pre/post-roll around each window (default 3)
  --reencode    frame-accurate cuts (slow); default is stream-copy (fast,
                cuts snap to keyframes — the default pad absorbs the slack)
  --dry-run     print the ffmpeg commands without running them
"""

from __future__ import annotations

import argparse
import csv
import subprocess
import sys
from datetime import date
from pathlib import Path

VERDICTS_TO_SHORTS = {"PASS"}
REQUIRED_COLUMNS = {"check_id", "verdict", "source", "start", "end"}


def hms_to_seconds(hms: str) -> float:
    """'HH:MM:SS' or 'MM:SS' → seconds."""
    parts = [float(p) for p in hms.strip().split(":")]
    if not 2 <= len(parts) <= 3:
        raise ValueError(f"bad time {hms!r} (want HH:MM:SS or MM:SS)")
    if len(parts) == 2:
        parts = [0.0, *parts]
    h, m, s = parts
    return h * 3600 + m * 60 + s


def seconds_to_hms(seconds: float) -> str:
    seconds = max(seconds, 0.0)
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{int(h):02d}:{int(m):02d}:{s:06.3f}"


def parse_kv(arg: str, flag: str) -> tuple[str, str]:
    if "=" not in arg:
        raise SystemExit(f"{flag} wants source=value, got {arg!r}")
    key, value = arg.split("=", 1)
    return key.strip(), value.strip()


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("results_csv", type=Path)
    ap.add_argument("--video", action="append", default=[], metavar="SOURCE=PATH",
                    help="source video, e.g. phone=IMG_1234.mp4 (repeatable)")
    ap.add_argument("--sync", action="append", default=[], metavar="SOURCE=VTIME@WALL",
                    help="sync mark: video time @ wall-clock, e.g. phone=00:03:12@14:02:10")
    ap.add_argument("--out", type=Path, default=Path("clips"))
    ap.add_argument("--pad", type=float, default=3.0)
    ap.add_argument("--reencode", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    videos = dict(parse_kv(v, "--video") for v in args.video)
    if not videos:
        ap.error("at least one --video source=path is required")

    # offset[source] = wall-clock seconds − video seconds, from the sync mark.
    offsets: dict[str, float] = {}
    for s in args.sync:
        source, mark = parse_kv(s, "--sync")
        if "@" not in mark:
            raise SystemExit(f"--sync wants VTIME@WALLCLOCK, got {mark!r}")
        vtime, wall = mark.split("@", 1)
        offsets[source] = hms_to_seconds(wall) - hms_to_seconds(vtime)
    missing_sync = set(videos) - set(offsets)
    if missing_sync:
        raise SystemExit(f"no --sync given for video source(s): {sorted(missing_sync)}")

    with args.results_csv.open(newline="") as fh:
        reader = csv.DictReader(fh)
        missing_cols = REQUIRED_COLUMNS - set(reader.fieldnames or [])
        if missing_cols:
            raise SystemExit(f"results CSV missing columns: {sorted(missing_cols)}")
        rows = [r for r in reader if r.get("check_id", "").strip()]
    if not rows:
        raise SystemExit("results CSV has no data rows")

    session_date = args.results_csv.parent.name or date.today().isoformat()
    failures = 0
    sliced = 0

    for row in rows:
        check_id = row["check_id"].strip()
        verdict = row["verdict"].strip().upper()
        source = row["source"].strip()
        if source not in videos:
            print(f"SKIP {check_id}: unknown source {source!r} (no --video for it)")
            continue
        try:
            start_wall = hms_to_seconds(row["start"])
            end_wall = hms_to_seconds(row["end"])
        except ValueError as exc:
            print(f"SKIP {check_id}: {exc}")
            failures += 1
            continue
        if end_wall <= start_wall:
            print(f"SKIP {check_id}: end {row['end']} not after start {row['start']}")
            failures += 1
            continue

        vstart = start_wall - offsets[source] - args.pad
        vend = end_wall - offsets[source] + args.pad
        if vend <= 0:
            print(f"SKIP {check_id}: window falls before the start of {source} video")
            failures += 1
            continue

        bucket = "shorts" if verdict in VERDICTS_TO_SHORTS else "issues"
        out_dir = args.out / bucket
        out_path = out_dir / f"{session_date}-{check_id}-{verdict}-{source}.mp4"

        codec = ["-c:v", "libx264", "-c:a", "aac"] if args.reencode else ["-c", "copy"]
        cmd = [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            "-ss", seconds_to_hms(vstart),
            "-to", seconds_to_hms(vend),
            "-i", str(videos[source]),
            *codec,
            str(out_path),
        ]

        if args.dry_run:
            print(" ".join(cmd))
            continue

        out_dir.mkdir(parents=True, exist_ok=True)
        result = subprocess.run(cmd)
        if result.returncode != 0:
            print(f"FAIL {check_id}: ffmpeg exited {result.returncode}")
            failures += 1
        else:
            print(f"{verdict:7s} {check_id} → {out_path}")
            sliced += 1

    if not args.dry_run:
        print(f"\n{sliced} clip(s) written to {args.out}/, {failures} problem(s).")
        print("Review every clip before upload — see docs/uat-social.md.")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
