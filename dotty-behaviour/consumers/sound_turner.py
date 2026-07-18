"""On `sound_event`, turn the head toward the sound direction.

Idle-only — face wins, conversation wins (this is the "curious about
an ambient noise" turn, not the deliberate "look at who summoned me"
turn that the wake-word consumer does).

Mirrors bridge.py's `_perception_sound_turner` including:

  * skip if face_present (face tracker owns gaze)
  * skip if a chat happened within QUIET_AFTER_CHAT_SEC
    (the user's own continuing speech shouldn't yank Dotty around)
  * per-device cooldown
  * rejects saturated/non-finite balance values from unhealthy channels
  * direction left/centre/center/right → ±YAW_DEG / 0
  * re-broadcasts a synthetic `head_turn` event for the dashboard
"""

from __future__ import annotations

import asyncio
import logging
import math

from dispatch import XiaozhiAdminClient
from perception import PerceptionEvent, PerceptionState

log = logging.getLogger("dotty-behaviour.consumers.sound_turner")

_MAX_HEALTHY_BALANCE = 0.95


class SoundTurner:
    def __init__(
        self,
        state: PerceptionState,
        xiaozhi: XiaozhiAdminClient,
        *,
        cooldown_sec: float,
        yaw_deg: int,
        speed: int,
        quiet_after_chat_sec: float,
    ) -> None:
        self._state = state
        self._xiaozhi = xiaozhi
        self._cooldown_sec = cooldown_sec
        self._yaw_deg = yaw_deg
        self._speed = speed
        self._quiet_after_chat_sec = quiet_after_chat_sec
        self._tasks: set[asyncio.Task] = set()
        self._unhealthy_balance_devices: set[str] = set()

    def _has_healthy_balance(self, device_id: str, data: dict) -> bool:
        if "balance" not in data:
            return True

        raw_balance = data["balance"]
        try:
            balance = float(raw_balance)
        except (TypeError, ValueError):
            balance = math.nan

        healthy = (
            math.isfinite(balance)
            and abs(balance) <= _MAX_HEALTHY_BALANCE
        )
        if healthy:
            self._unhealthy_balance_devices.discard(device_id)
            return True

        if device_id not in self._unhealthy_balance_devices:
            log.warning(
                "unhealthy sound balance; suppressing head turns: "
                "device=%s balance=%r",
                device_id,
                raw_balance,
            )
            self._unhealthy_balance_devices.add(device_id)
        return False

    def _spawn(self, coro, *, name: str | None = None) -> None:
        t = asyncio.create_task(coro, name=name)
        self._tasks.add(t)
        t.add_done_callback(self._tasks.discard)

    async def run(self) -> None:
        log.info(
            "sound turner started (cooldown=%.0fs yaw=±%d speed=%d quiet=%.0fs)",
            self._cooldown_sec,
            self._yaw_deg,
            self._speed,
            self._quiet_after_chat_sec,
        )
        q = self._state.subscribe()
        try:
            while True:
                event = await q.get()
                if event.name != "sound_event":
                    continue
                device_id = event.device_id
                if not device_id or device_id == "unknown":
                    continue
                data = event.data or {}
                direction = data.get("direction", "")
                if direction not in ("left", "centre", "center", "right"):
                    continue
                # CoreS3 currently exposes mic + AEC reference as two input
                # channels. A saturated "balance" is a channel fault, not a
                # trustworthy left/right direction.
                if not self._has_healthy_balance(device_id, data):
                    continue

                now = event.ts
                dev_state = self._state.state.setdefault(device_id, {})
                if dev_state.get("face_present"):
                    continue
                last_chat = dev_state.get("last_chat_t", 0.0)
                if now - last_chat < self._quiet_after_chat_sec:
                    continue
                last_turn = dev_state.get("last_sound_turn_t", 0.0)
                if now - last_turn < self._cooldown_sec:
                    continue
                dev_state["last_sound_turn_t"] = now

                if direction == "left":
                    yaw = -self._yaw_deg
                elif direction == "right":
                    yaw = self._yaw_deg
                else:
                    yaw = 0
                log.info(
                    "sound_event → head-turn: device=%s direction=%s yaw=%d",
                    device_id,
                    direction,
                    yaw,
                )
                self._spawn(
                    self._xiaozhi.set_head_angles(
                        device_id, yaw, 0, self._speed
                    ),
                    name="sound_turner_set_head_angles",
                )
                head_turn_data = {
                    "yaw": yaw,
                    "pitch": 0,
                    "speed": self._speed,
                    "reason": "sound_localizer",
                    "direction": direction,
                    "energy": data.get("energy"),
                }
                self._state.update_state(
                    device_id, "head_turn", head_turn_data, now
                )
                self._state.broadcast(
                    PerceptionEvent(
                        device_id=device_id,
                        name="head_turn",
                        data=head_turn_data,
                        ts=now,
                    )
                )
        except asyncio.CancelledError:
            log.info("sound turner cancelled")
            for t in list(self._tasks):
                if not t.done():
                    t.cancel()
            raise
        except Exception:
            log.exception("sound turner crashed")
        finally:
            self._state.unsubscribe(q)
