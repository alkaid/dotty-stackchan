"""SecurityCycle — per-device timer + capture cycle + ring buffer."""

from __future__ import annotations

import asyncio
import json
import tempfile
import time
from pathlib import Path
from time import perf_counter
from zoneinfo import ZoneInfo

from consumers import SecurityCycle
from logs import NdjsonWriter
from perception import PerceptionEvent, PerceptionState

from ._fakes import FakeXiaozhi, let_consumer_settle


_UTC = ZoneInfo("UTC")


def _make(td: Path, state: PerceptionState, xiaozhi: FakeXiaozhi,
          *, interval=0.05, wait=0.5) -> SecurityCycle:
    return SecurityCycle(
        state,
        xiaozhi,
        NdjsonWriter(td, "security", _UTC),
        interval_sec=interval,
        audio_duration_ms=5000,
        vlm_prompt="describe",
        vlm_wait_sec=wait,
        ring_buffer_size=10,
    )


async def _drive(consumer: SecurityCycle, body):
    task = asyncio.create_task(consumer.run())
    try:
        await let_consumer_settle()
        await body()
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


def test_state_changed_to_security_starts_timer() -> None:
    async def go() -> None:
        with tempfile.TemporaryDirectory() as td:
            tdp = Path(td)
            state = PerceptionState()
            xiaozhi = FakeXiaozhi()
            consumer = _make(tdp, state, xiaozhi, interval=10.0, wait=0.05)

            async def body() -> None:
                state.broadcast(
                    PerceptionEvent(
                        device_id="dev-1",
                        name="state_changed",
                        data={"state": "security"},
                        ts=time.time(),
                    )
                )
                # Let the consumer dispatch its first cycle
                await asyncio.sleep(0.1)
                assert len(xiaozhi.take_photo_calls) >= 1
                assert xiaozhi.take_photo_calls[0]["device_id"] == "dev-1"
                assert xiaozhi.capture_audio_calls[0]["device_id"] == "dev-1"

            await _drive(consumer, body)

    asyncio.run(go())


def test_state_changed_away_from_security_stops_timer() -> None:
    async def go() -> None:
        with tempfile.TemporaryDirectory() as td:
            tdp = Path(td)
            state = PerceptionState()
            xiaozhi = FakeXiaozhi()
            # Short interval so multiple cycles would normally fire
            consumer = _make(tdp, state, xiaozhi, interval=0.05, wait=0.02)

            async def body() -> None:
                state.broadcast(
                    PerceptionEvent(
                        device_id="dev-1",
                        name="state_changed",
                        data={"state": "security"},
                        ts=time.time(),
                    )
                )
                await asyncio.sleep(0.1)
                state.broadcast(
                    PerceptionEvent(
                        device_id="dev-1",
                        name="state_changed",
                        data={"state": "idle"},
                        ts=time.time(),
                    )
                )
                # Allow the stop event to register
                await let_consumer_settle()
                count_after_stop = len(xiaozhi.take_photo_calls)
                # Wait beyond what would be the next interval
                await asyncio.sleep(0.2)
                assert len(xiaozhi.take_photo_calls) == count_after_stop

            await _drive(consumer, body)

    asyncio.run(go())


def test_cycle_writes_ndjson_record() -> None:
    async def go() -> None:
        with tempfile.TemporaryDirectory() as td:
            tdp = Path(td)
            state = PerceptionState()
            xiaozhi = FakeXiaozhi()
            consumer = _make(tdp, state, xiaozhi, interval=10.0, wait=0.05)

            async def body() -> None:
                state.broadcast(
                    PerceptionEvent(
                        device_id="dev-1",
                        name="state_changed",
                        data={"state": "security"},
                        ts=time.time(),
                    )
                )
                await asyncio.sleep(0.15)
                files = list(tdp.glob("security-*.ndjson"))
                assert len(files) == 1
                record = json.loads(
                    files[0].read_text(encoding="utf-8").splitlines()[0]
                )
                assert record["device"] == "dev-1"
                # Both polls miss (no cache fill) → errors recorded
                assert "photo_poll_miss" in record["errors"]
                assert "audio_poll_miss" in record["errors"]

            await _drive(consumer, body)

    asyncio.run(go())


def test_cycle_reads_vision_cache_when_fresh() -> None:
    async def go() -> None:
        with tempfile.TemporaryDirectory() as td:
            tdp = Path(td)
            state = PerceptionState()
            xiaozhi = FakeXiaozhi()
            consumer = _make(tdp, state, xiaozhi, interval=10.0, wait=0.2)

            async def _populate_vision() -> None:
                # Wait for the take_photo dispatch, then drop a fresh
                # cache entry just like /api/vision/explain would.
                for _ in range(50):
                    if xiaozhi.take_photo_calls:
                        break
                    await asyncio.sleep(0.005)
                state.vision_cache["dev-1"] = {
                    "description": "Door opens, someone enters.",
                    "wall_ts": time.time(),
                    "timestamp": perf_counter(),
                }

            async def body() -> None:
                state.broadcast(
                    PerceptionEvent(
                        device_id="dev-1",
                        name="state_changed",
                        data={"state": "security"},
                        ts=time.time(),
                    )
                )
                populator = asyncio.create_task(_populate_vision())
                await asyncio.sleep(0.6)
                await populator
                files = list(tdp.glob("security-*.ndjson"))
                assert len(files) == 1
                record = json.loads(
                    files[0].read_text(encoding="utf-8").splitlines()[0]
                )
                assert record["photo_desc"] == "Door opens, someone enters."
                assert "photo_poll_miss" not in record["errors"]
                # Cache entry should be tagged
                assert (
                    state.vision_cache["dev-1"]["source"]
                    == "security_capture"
                )

            await _drive(consumer, body)

    asyncio.run(go())


def test_audio_capture_pending_when_dispatch_returns_false() -> None:
    """If capture_audio returns False (relay 404 / firmware not ready),
    the cycle still completes with `audio_capture_pending` in errors."""
    async def go() -> None:
        with tempfile.TemporaryDirectory() as td:
            tdp = Path(td)
            state = PerceptionState()
            xiaozhi = FakeXiaozhi()
            # Patch capture_audio to return False
            async def _no_audio(device_id: str, duration_ms: int = 4000) -> bool:
                xiaozhi.capture_audio_calls.append(
                    {"device_id": device_id, "duration_ms": duration_ms}
                )
                return False
            xiaozhi.capture_audio = _no_audio  # type: ignore[assignment]

            consumer = _make(tdp, state, xiaozhi, interval=10.0, wait=0.05)

            async def body() -> None:
                state.broadcast(
                    PerceptionEvent(
                        device_id="dev-1",
                        name="state_changed",
                        data={"state": "security"},
                        ts=time.time(),
                    )
                )
                await asyncio.sleep(0.15)
                files = list(tdp.glob("security-*.ndjson"))
                record = json.loads(
                    files[0].read_text(encoding="utf-8").splitlines()[0]
                )
                assert "audio_capture_pending" in record["errors"]
                assert "audio_poll_miss" not in record["errors"]

            await _drive(consumer, body)

    asyncio.run(go())


def test_ring_buffer_get_recent_cycles_newest_first() -> None:
    async def go() -> None:
        with tempfile.TemporaryDirectory() as td:
            tdp = Path(td)
            state = PerceptionState()
            xiaozhi = FakeXiaozhi()
            consumer = _make(tdp, state, xiaozhi, interval=0.05, wait=0.02)

            async def body() -> None:
                state.broadcast(
                    PerceptionEvent(
                        device_id="dev-1",
                        name="state_changed",
                        data={"state": "security"},
                        ts=time.time(),
                    )
                )
                # Allow several cycles to fire
                await asyncio.sleep(0.6)
                recent = consumer.get_recent_cycles()
                assert len(recent) >= 2
                # newest first
                assert recent[0]["ts"] >= recent[-1]["ts"]

            await _drive(consumer, body)

    asyncio.run(go())
