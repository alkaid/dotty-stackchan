#!/usr/bin/env python3
"""Summarise privacy-safe DOTTY_LATENCY events from Docker Compose logs."""

from __future__ import annotations

import argparse
import math
import re
import subprocess
from collections import defaultdict


_EVENT_RE = re.compile(r"DOTTY_LATENCY\s+(?P<fields>.+)$")
_FIELD_RE = re.compile(r"([A-Za-z0-9_]+)=([^\s]+)")


def parse_event(line: str) -> dict[str, str] | None:
    match = _EVENT_RE.search(line)
    if match is None:
        return None
    fields = dict(_FIELD_RE.findall(match.group("fields")))
    if "turn" not in fields or "phase" not in fields:
        return None
    return fields


def percentile(values: list[int], quantile: float) -> int:
    ordered = sorted(values)
    if not ordered:
        raise ValueError("percentile requires at least one value")
    index = max(0, math.ceil(len(ordered) * quantile) - 1)
    return ordered[index]


def summarise(lines: list[str]) -> tuple[dict[str, list[int]], dict[str, set[str]]]:
    phases: dict[str, list[int]] = defaultdict(list)
    turn_flags: dict[str, set[str]] = defaultdict(set)
    for line in lines:
        event = parse_event(line)
        if event is None:
            continue
        try:
            elapsed_ms = int(event["elapsed_ms"])
        except (KeyError, ValueError):
            continue
        phase = event["phase"]
        turn_id = event["turn"]
        phases[phase].append(elapsed_ms)
        if phase == "pi_tool_end":
            turn_flags[turn_id].add(f"tool:{event.get('tool', 'unknown')}")
        if phase == "filler_start":
            turn_flags[turn_id].add("filler")
    return dict(phases), dict(turn_flags)


def _docker_logs(since: str) -> list[str]:
    command = [
        "docker",
        "compose",
        "logs",
        "--since",
        since,
        "--no-color",
        "xiaozhi-esp32-server",
        "dotty-pi",
    ]
    result = subprocess.run(command, check=True, capture_output=True, text=True)
    return result.stdout.splitlines()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--since", default="24h", help="Docker --since value")
    args = parser.parse_args()

    phases, turn_flags = summarise(_docker_logs(args.since))
    if not phases:
        print(f"No DOTTY_LATENCY events found since {args.since}.")
        return 0

    print(f"Dotty latency report since {args.since}")
    print(f"{'phase':24} {'count':>5} {'p50':>8} {'p95':>8} {'max':>8}")
    for phase in sorted(phases):
        values = phases[phase]
        print(
            f"{phase:24} {len(values):5d} "
            f"{percentile(values, 0.50):7d}ms "
            f"{percentile(values, 0.95):7d}ms {max(values):7d}ms"
        )

    think_turns = sum("tool:think_hard" in flags for flags in turn_flags.values())
    filler_turns = sum("filler" in flags for flags in turn_flags.values())
    print(f"think_hard turns: {think_turns}")
    print(f"filler turns:     {filler_turns}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
