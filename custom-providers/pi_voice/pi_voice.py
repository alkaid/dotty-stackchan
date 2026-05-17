"""PiVoiceLLM — xiaozhi-server LLM provider that routes voice turns
through the dotty-pi container instead of bridge.py.

The Tier1Slim provider parses OpenAI-style `tool_calls` and dispatches
each one xiaozhi-side. PiVoiceLLM doesn't do that: pi itself owns the
agent loop and the tool dispatch happens inside the dotty-pi-ext
extension. From xiaozhi's perspective this provider is a much simpler
shape — translate the dialogue into a single pi prompt, stream pi's
user-visible text chunks back to TTS, done.

Per #36 Step-5 contract:
  - PiVoiceLLM owns ONE PiClient — long-lived across all turns.
  - Between turns we issue `new_session` to reset pi's working state
    without re-spawning the process.
  - Thinking deltas + extension UI requests are filtered inside
    PiClient (see pi_client.py) — by the time text reaches `response()`
    only TTS-bound chunks remain.

Configuration via `data/.config.yaml`:

```yaml
selected_module:
  LLM: PiVoiceLLM

LLM:
  PiVoiceLLM:
    type: pi_voice
    container_name: dotty-pi
    # Optional — flags appended after the default ones in PiClient.
    extra_pi_flags: ""
```
"""

from __future__ import annotations

import os
from typing import Iterator

from .pi_client import PiClient, PiClientError, make_default_pi_client


try:
    from config.logger import setup_logging  # type: ignore
    from core.providers.llm.base import LLMProviderBase  # type: ignore
except ImportError:  # pragma: no cover — only on dev workstation
    # Provide tiny stand-ins so this file imports cleanly during
    # extension-side unit tests. xiaozhi-server overrides both.
    class LLMProviderBase:  # type: ignore[no-redef]
        pass

    def setup_logging():  # type: ignore[no-redef]
        import logging
        return logging.getLogger("pi_voice")


TAG = __name__
logger = setup_logging()


def _last_user_text(dialogue: list[dict]) -> str:
    """Find the most recent user-turn content. xiaozhi's dialogue is a
    list of {role, content} dicts in chronological order; the last user
    entry is the utterance we want pi to react to."""
    for msg in reversed(dialogue):
        if msg.get("role") == "user":
            return str(msg.get("content") or "")
    return ""


class LLMProvider(LLMProviderBase):
    """xiaozhi-server LLM provider backed by the dotty-pi container."""

    def __init__(self, config: dict):
        self._container = config.get("container_name") or os.environ.get(
            "DOTTY_PI_CONTAINER", "dotty-pi",
        )
        self._client: PiClient = make_default_pi_client()
        self._first_turn = True
        try:
            logger.bind(tag=TAG).info(  # type: ignore[attr-defined]
                "PiVoiceLLM ready (container=%s)", self._container,
            )
        except AttributeError:
            logger.info("PiVoiceLLM ready (container=%s)", self._container)

    # xiaozhi-server's voice loop calls this as a sync generator.
    # Each yielded string becomes a TTS chunk.
    def response(self, session_id, dialogue, **kwargs) -> Iterator[str]:
        prompt = _last_user_text(dialogue)
        if not prompt:
            yield "(empty turn)"
            return

        # Reset pi state between voice turns. First turn skips this —
        # the freshly-spawned process is already clean.
        if not self._first_turn:
            try:
                self._client.new_session()
            except PiClientError:
                logger.exception("PiVoiceLLM: new_session failed, continuing")
        self._first_turn = False

        try:
            for chunk in self._client.iter_turn_text(prompt):
                yield chunk
        except PiClientError as exc:
            logger.error("PiVoiceLLM turn failed: %s", exc)
            for line in self._client.recent_stderr()[-5:]:
                logger.error("  pi.stderr: %s", line)
            yield "(brain offline — try again in a moment)"

    def close(self) -> None:
        """xiaozhi may call this on shutdown — make sure pi cleans up."""
        self._client.close()
