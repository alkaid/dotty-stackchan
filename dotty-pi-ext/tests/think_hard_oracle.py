#!/usr/bin/env python3
"""think_hard request-body oracle for the environment-driven route.

Usage:
    python3 think_hard_oracle.py "<question>"

The TS test loads this JSON and asserts buildThinkRequest produces the
same shape (model name aside — we pin it on both sides). Body equivalence
is what the oracle covers; the LLM response itself isn't deterministic
so the TS test handles success/timeout/error paths separately via mocks.
"""

from __future__ import annotations

import json
import os
import sys


def build_think_request(question: str, model: str | None = None) -> dict:
    raw_max_tokens = os.environ.get("DOTTY_PI_THINK_MAX_TOKENS", "4096")
    try:
        max_tokens = int(raw_max_tokens)
        if max_tokens <= 0:
            raise ValueError
    except ValueError:
        max_tokens = 4096
    reasoning = os.environ.get("DOTTY_PI_THINK_REASONING", "true").lower() in {
        "1", "true", "yes", "on",
    }
    body = {
        "model": model or os.environ.get("VOICE_THINKER_MODEL", "dotty-think"),
        "messages": [
            {"role": "system", "content":
                "Answer the user's question concisely in 1-2 sentences. Be precise."},
            {"role": "user", "content": question},
        ],
        "max_tokens": max_tokens,
        "temperature": 0.3,
        "stream": False,
        "chat_template_kwargs": {"enable_thinking": reasoning},
    }
    effort = os.environ.get("DOTTY_PI_THINK_REASONING_EFFORT", "high").strip()
    if effort:
        body["reasoning_effort"] = effort
    return body


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: think_hard_oracle.py <question>", file=sys.stderr)
        return 2
    question = sys.argv[1]
    body = build_think_request(question)
    print(json.dumps(body, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
