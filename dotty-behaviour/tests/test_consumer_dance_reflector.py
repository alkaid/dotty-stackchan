"""DanceReflector — on dance_ended, write LLM reflection to NDJSON."""

from __future__ import annotations

import asyncio
import json
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from consumers import DanceReflector
from logs import NdjsonWriter
from perception import PerceptionEvent, PerceptionState

from ._fakes import let_consumer_settle


@dataclass
class _FakeNarrative:
    calls: list[dict[str, Any]] = field(default_factory=list)
    response: str | None = "A spinning joy, brief and ridiculous."

    async def chat(
        self,
        user_prompt: str,
        *,
        system_prompt: str,
        model: str | None = None,
        max_tokens: int = 1200,
        temperature: float = 0.9,
    ) -> str | None:
        self.calls.append(
            {
                "user_prompt": user_prompt,
                "system_prompt": system_prompt,
                "max_tokens": max_tokens,
                "temperature": temperature,
            }
        )
        return self.response


async def _spin(state, narrative, td: Path, body):
    consumer = DanceReflector(
        state,
        narrative,
        NdjsonWriter(td, "dances", ZoneInfo("UTC")),
        role_name_provider=lambda: "Mochi",
    )
    task = asyncio.create_task(consumer.run())
    try:
        await let_consumer_settle()
        await body()
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


def test_dance_ended_writes_reflection() -> None:
    async def go() -> None:
        with tempfile.TemporaryDirectory() as td:
            tdp = Path(td)
            state = PerceptionState()
            narrative = _FakeNarrative()

            async def body() -> None:
                state.broadcast(
                    PerceptionEvent(
                        device_id="dev-1",
                        name="dance_ended",
                        data={"dance": "happy"},
                        ts=1.0,
                    )
                )
                # Let _fire spawn + finish
                await let_consumer_settle()
                await asyncio.sleep(0.05)
                files = list(tdp.glob("dances-*.ndjson"))
                assert len(files) == 1
                record = json.loads(files[0].read_text(encoding="utf-8"))
                assert record["type"] == "dance"
                assert record["device"] == "dev-1"
                assert record["dance"] == "happy"
                assert "spinning joy" in record["reflection"]
                # LLM was asked about "happy"
                assert "happy" in narrative.calls[0]["user_prompt"]
                # Per bridge.py: max_tokens=200, temperature=0.85
                assert narrative.calls[0]["max_tokens"] == 200
                assert narrative.calls[0]["temperature"] == 0.85
                assert "You are Mochi" in narrative.calls[0]["system_prompt"]

            await _spin(state, narrative, tdp, body)

    asyncio.run(go())


def test_dance_ended_with_missing_name_falls_back() -> None:
    async def go() -> None:
        with tempfile.TemporaryDirectory() as td:
            tdp = Path(td)
            state = PerceptionState()
            narrative = _FakeNarrative()

            async def body() -> None:
                state.broadcast(
                    PerceptionEvent(
                        device_id="dev-1",
                        name="dance_ended",
                        data={},
                        ts=1.0,
                    )
                )
                await let_consumer_settle()
                await asyncio.sleep(0.05)
                files = list(tdp.glob("dances-*.ndjson"))
                assert len(files) == 1
                record = json.loads(files[0].read_text(encoding="utf-8"))
                assert record["dance"] == "the dance"

            await _spin(state, narrative, tdp, body)

    asyncio.run(go())


def test_dance_with_no_llm_response_is_skipped() -> None:
    async def go() -> None:
        with tempfile.TemporaryDirectory() as td:
            tdp = Path(td)
            state = PerceptionState()
            narrative = _FakeNarrative(response=None)

            async def body() -> None:
                state.broadcast(
                    PerceptionEvent(
                        device_id="dev-1",
                        name="dance_ended",
                        data={"dance": "boring"},
                        ts=1.0,
                    )
                )
                await let_consumer_settle()
                await asyncio.sleep(0.05)
                # LLM was called but no record was written
                assert len(narrative.calls) == 1
                files = list(tdp.glob("dances-*.ndjson"))
                assert files == []

            await _spin(state, narrative, tdp, body)

    asyncio.run(go())
