"""Security capture loop — text-only per-device watch on state=security.

When the firmware enters the `security` State, this consumer starts a
per-device interval timer. Each tick:

  1. take_photo → firmware → /api/vision/explain → vision_cache update
  2. capture_audio → firmware → /api/audio/explain → audio_cache update
     (audio leg gracefully degrades when the relay returns 404)
  3. One NDJSON record per cycle to `<LOG_DIR>/security-YYYY-MM-DD.ndjson`,
     plus an in-memory ring buffer (last N cycles) the dashboard reads.

Persistence is deliberately text-only — the JPEG / audio bytes never
leave the in-memory caches; only the VLM/ASR descriptions land on
disk.

Ported from bridge/security_watch.py with the same loop shape; the
HTTP-loopback vision_poll is replaced with a direct read of the
in-process vision_cache (we live in the same process so the indirection
is unnecessary), and the audio leg uses the new audio_cache that
landed with /api/audio/explain in the prior slice.
"""

from __future__ import annotations

import asyncio
import collections
import logging
import time

from dispatch import XiaozhiAdminClient
from logs import NdjsonWriter
from perception import PerceptionState

log = logging.getLogger("dotty-behaviour.consumers.security_cycle")


class SecurityCycle:
    def __init__(
        self,
        state: PerceptionState,
        xiaozhi: XiaozhiAdminClient,
        writer: NdjsonWriter,
        *,
        interval_sec: float,
        audio_duration_ms: int,
        vlm_prompt: str,
        vlm_wait_sec: float,
        ring_buffer_size: int,
    ) -> None:
        self._state = state
        self._xiaozhi = xiaozhi
        self._writer = writer
        self._interval_sec = interval_sec
        self._audio_duration_ms = audio_duration_ms
        self._vlm_prompt = vlm_prompt
        self._vlm_wait_sec = vlm_wait_sec
        # Last N cycles surfaced via get_recent_cycles() — bounded so the
        # daemon's memory doesn't grow with uptime.
        self.recent_cycles: collections.deque[dict] = collections.deque(
            maxlen=ring_buffer_size
        )
        # device_id → running capture task. Started on state→security,
        # cancelled on transition away.
        self._device_timers: dict[str, asyncio.Task] = {}

    # ------------------------------------------------------------------
    # Per-device timer management
    # ------------------------------------------------------------------

    def _start_device_timer(self, device_id: str) -> None:
        existing = self._device_timers.get(device_id)
        if existing is not None and not existing.done():
            return  # idempotent
        self._device_timers[device_id] = asyncio.create_task(
            self._device_capture_loop(device_id),
            name=f"security_capture[{device_id}]",
        )
        log.info(
            "security: started capture loop for device=%s", device_id
        )

    def _stop_device_timer(self, device_id: str) -> bool:
        t = self._device_timers.pop(device_id, None)
        if t is None or t.done():
            return False
        t.cancel()
        return True

    def _stop_all_timers(self) -> None:
        for did in list(self._device_timers):
            self._stop_device_timer(did)

    # ------------------------------------------------------------------
    # Capture cycle
    # ------------------------------------------------------------------

    async def _wait_for_fresh_vision(
        self, device_id: str, *, pre_wall_ts: float
    ) -> str | None:
        """Poll the in-process vision_cache for a fresh entry after a
        take_photo dispatch. Returns the description or None on miss /
        timeout."""
        deadline = time.monotonic() + self._vlm_wait_sec
        while time.monotonic() < deadline:
            entry = self._state.vision_cache.get(device_id) or {}
            new_ts = entry.get("wall_ts") or 0.0
            desc = (entry.get("description") or "").strip()
            if desc and new_ts > pre_wall_ts:
                return desc
            await asyncio.sleep(0.05)
        return None

    async def _wait_for_fresh_audio(
        self, device_id: str, *, pre_wall_ts: float, deadline_s: float
    ) -> tuple[str | None, str | None]:
        """Similar to _wait_for_fresh_vision but for the audio cache.
        Returns (transcript, classification) — currently both come from
        the single 'description' field; classification is a placeholder
        for when an ambient classifier model is added.
        """
        deadline = time.monotonic() + deadline_s
        while time.monotonic() < deadline:
            entry = self._state.audio_cache.get(device_id) or {}
            new_ts = entry.get("wall_ts") or 0.0
            desc = (entry.get("description") or "").strip()
            if desc and new_ts > pre_wall_ts:
                return desc, None
            await asyncio.sleep(0.05)
        return None, None

    async def _run_one_cycle(self, device_id: str) -> dict:
        errors: list[str] = []
        photo_desc = ""
        audio_transcript: str | None = None
        audio_classification: str | None = None

        # Photo leg
        pre_vision_ts = (
            self._state.vision_cache.get(device_id, {}).get("wall_ts") or 0.0
        )
        photo_ok = await self._xiaozhi.take_photo(
            device_id, question=self._vlm_prompt
        )
        if not photo_ok:
            errors.append("photo_dispatch_failed")
        else:
            desc = await self._wait_for_fresh_vision(
                device_id, pre_wall_ts=pre_vision_ts
            )
            if desc:
                photo_desc = desc
                # Tag the cache entry as a security capture so the
                # dashboard can differentiate from room_view captures.
                entry = self._state.vision_cache.get(device_id)
                if entry is not None:
                    entry["source"] = "security_capture"
            else:
                errors.append("photo_poll_miss")

        # Audio leg
        pre_audio_ts = (
            self._state.audio_cache.get(device_id, {}).get("wall_ts") or 0.0
        )
        audio_ok = await self._xiaozhi.capture_audio(
            device_id, duration_ms=self._audio_duration_ms
        )
        if not audio_ok:
            errors.append("audio_capture_pending")
        else:
            transcript, classification = await self._wait_for_fresh_audio(
                device_id,
                pre_wall_ts=pre_audio_ts,
                deadline_s=self._vlm_wait_sec,
            )
            if transcript:
                audio_transcript = transcript
                audio_classification = classification
            else:
                errors.append("audio_poll_miss")

        record = {
            "ts": self._writer.now_isoformat(),
            "device": device_id,
            "photo_desc": photo_desc,
            "audio_transcript": audio_transcript,
            "audio_classification": audio_classification,
            "errors": errors,
        }
        self._writer.append(record)
        self.recent_cycles.append(record)
        log.info(
            "security cycle device=%s desc_len=%d errors=%s",
            device_id, len(photo_desc), errors,
        )
        return record

    async def _device_capture_loop(self, device_id: str) -> None:
        log.info(
            "security capture loop started device=%s interval=%.0fs",
            device_id, self._interval_sec,
        )
        try:
            while True:
                try:
                    await self._run_one_cycle(device_id)
                except Exception:
                    log.exception(
                        "security cycle crashed device=%s", device_id
                    )
                await asyncio.sleep(self._interval_sec)
        except asyncio.CancelledError:
            log.info(
                "security capture loop cancelled device=%s", device_id
            )
            raise

    # ------------------------------------------------------------------
    # Bus subscriber
    # ------------------------------------------------------------------

    def get_recent_cycles(self, limit: int | None = None) -> list[dict]:
        """Return the most-recent cycles (newest first). Dashboard reads
        this to surface a recent-events panel."""
        items = list(self.recent_cycles)
        items.reverse()
        if limit is not None:
            items = items[:limit]
        return items

    async def run(self) -> None:
        log.info(
            "security capture consumer started "
            "(interval=%.0fs audio=%dms prompt=%r)",
            self._interval_sec,
            self._audio_duration_ms,
            self._vlm_prompt[:80],
        )
        q = self._state.subscribe()
        try:
            while True:
                event = await q.get()
                if event.name != "state_changed":
                    continue
                if not event.device_id or event.device_id == "unknown":
                    continue
                new_state = (
                    (event.data or {}).get("state") or ""
                ).strip().lower()
                if new_state == "security":
                    self._start_device_timer(event.device_id)
                else:
                    if self._stop_device_timer(event.device_id):
                        log.info(
                            "security: stopped capture loop for "
                            "device=%s (new state=%s)",
                            event.device_id, new_state,
                        )
        except asyncio.CancelledError:
            log.info("security capture consumer cancelled")
            self._stop_all_timers()
            raise
        except Exception:
            log.exception("security capture consumer crashed")
            self._stop_all_timers()
        finally:
            self._state.unsubscribe(q)
