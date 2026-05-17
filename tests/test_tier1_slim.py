"""Smoke tests for the Tier1Slim voice LLM provider.

tier1_slim.py is the live voice path (per CLAUDE.md) but had zero test
coverage. These cover the structural regressions — config validation,
hot-swap, message assembly, the tool-escalation handshake to bridge.py,
and the [REMEMBER:] extraction path. The HTTP layer is mocked via
unittest.mock.patch("requests.post", ...).

Like test_zeroclaw_persona, the module under test imports xiaozhi-server
internals (config.logger, core.providers.llm.base) that only exist
inside the container, so we install MagicMock entries in sys.modules
before exec'ing the source by path. The snapshot/restore pattern keeps
the pollution from leaking into neighbouring test modules.
"""
from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch


def _import_tier1_slim():
    polluted_keys = (
        "config",
        "config.logger",
        "core",
        "core.providers",
        "core.providers.llm",
        "core.providers.llm.base",
        "core.utils",
        "core.utils.textUtils",
    )
    _MISSING = object()
    saved = {k: sys.modules.get(k, _MISSING) for k in polluted_keys}

    try:
        mock_logger_mod = MagicMock()
        mock_logger_mod.setup_logging.return_value = MagicMock()
        for pkg in polluted_keys[:-1]:
            sys.modules.setdefault(pkg, MagicMock())
        sys.modules["config.logger"] = mock_logger_mod

        # tier1_slim does `class LLMProvider(LLMProviderBase): ...` — if the
        # base is a MagicMock attribute, the class definition produces a
        # Mock-class and every constructor call returns a Mock. Install a
        # real empty base class so subclassing works as intended.
        import types as _types
        base_mod = _types.ModuleType("core.providers.llm.base")
        class LLMProviderBase:  # noqa: D401 — minimal test stub
            pass
        base_mod.LLMProviderBase = LLMProviderBase  # type: ignore[attr-defined]
        sys.modules["core.providers.llm.base"] = base_mod

        repo_root = Path(__file__).resolve().parents[1]

        # Real textUtils — tier1_slim imports ALLOWED_EMOJIS, FALLBACK_EMOJI,
        # build_turn_suffix and uses them in string ops, so a Mock breaks.
        text_utils_path = repo_root / "custom-providers" / "textUtils.py"
        tu_spec = importlib.util.spec_from_file_location(
            "core.utils.textUtils", text_utils_path,
        )
        tu_mod = importlib.util.module_from_spec(tu_spec)  # type: ignore[arg-type]
        tu_spec.loader.exec_module(tu_mod)  # type: ignore[union-attr]
        sys.modules["core.utils.textUtils"] = tu_mod

        src = repo_root / "custom-providers" / "tier1_slim" / "tier1_slim.py"
        spec = importlib.util.spec_from_file_location("tier1_slim_provider", src)
        mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
        spec.loader.exec_module(mod)  # type: ignore[union-attr]
        return mod
    finally:
        for k, v in saved.items():
            if v is _MISSING:
                sys.modules.pop(k, None)
            else:
                sys.modules[k] = v  # type: ignore[assignment]


_t1 = _import_tier1_slim()


def _make_provider(**overrides):
    cfg = {
        "url": "http://test.local/v1",
        "model": "test-model",
        "api_key": "test-key",
    }
    cfg.update(overrides)
    return _t1.LLMProvider(cfg)


def _streaming_response(chunks, status=200):
    """Build a Mock that imitates requests.post(stream=True). Each chunk is
    serialised as an SSE-style `data: {...}\\n` line; the iterator ends with
    `data: [DONE]`."""
    resp = MagicMock()
    resp.status_code = status
    resp.raise_for_status = MagicMock()
    if status >= 400:
        resp.raise_for_status.side_effect = Exception(f"HTTP {status}")
    lines = []
    for c in chunks:
        payload = {"choices": [{"delta": {"content": c}}]}
        lines.append(f"data: {json.dumps(payload)}")
    lines.append("data: [DONE]")
    resp.iter_lines = MagicMock(return_value=iter(lines))
    return resp


# ---------------------------------------------------------------------------
# Constructor + config validation
# ---------------------------------------------------------------------------

class ConstructorTests(unittest.TestCase):
    def test_missing_url_raises(self):
        with self.assertRaises(ValueError) as cm:
            _t1.LLMProvider({"model": "x"})
        self.assertIn("url", str(cm.exception))

    def test_missing_model_raises(self):
        with self.assertRaises(ValueError) as cm:
            _t1.LLMProvider({"url": "http://x/v1"})
        self.assertIn("model", str(cm.exception))

    def test_defaults_applied(self):
        p = _make_provider()
        self.assertEqual(p.api_key, "test-key")
        self.assertEqual(p.max_tokens, 256)
        self.assertEqual(p.temperature, 0.7)
        self.assertEqual(p.timeout, 60.0)

    def test_trailing_slash_stripped(self):
        p = _make_provider(url="http://test.local/v1/")
        self.assertEqual(p.base_url, "http://test.local/v1")

    def test_persona_file_loaded_over_system_prompt(self):
        with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False) as f:
            f.write("PERSONA-FROM-FILE")
            persona_path = f.name
        try:
            p = _make_provider(persona_file=persona_path, system_prompt="IGNORED")
            self.assertEqual(p._persona, "PERSONA-FROM-FILE")
        finally:
            Path(persona_path).unlink(missing_ok=True)

    def test_persona_falls_back_to_system_prompt_when_file_missing(self):
        p = _make_provider(persona_file="/nonexistent/x.md", system_prompt="FALLBACK")
        self.assertEqual(p._persona, "FALLBACK")


# ---------------------------------------------------------------------------
# set_runtime hot-swap
# ---------------------------------------------------------------------------

class SetRuntimeTests(unittest.TestCase):
    def test_model_only(self):
        p = _make_provider()
        p.set_runtime(model="new-model")
        self.assertEqual(p.model, "new-model")
        self.assertEqual(p.base_url, "http://test.local/v1")  # unchanged
        self.assertEqual(p.api_key, "test-key")  # unchanged

    def test_url_strips_trailing_slash(self):
        p = _make_provider()
        p.set_runtime(url="http://new.host/v2/")
        self.assertEqual(p.base_url, "http://new.host/v2")

    def test_all_three(self):
        p = _make_provider()
        p.set_runtime(model="m2", url="http://u/v3", api_key="k2")
        self.assertEqual(p.model, "m2")
        self.assertEqual(p.base_url, "http://u/v3")
        self.assertEqual(p.api_key, "k2")

    def test_no_args_is_noop(self):
        p = _make_provider()
        p.set_runtime()
        self.assertEqual(p.model, "test-model")
        self.assertEqual(p.base_url, "http://test.local/v1")


# ---------------------------------------------------------------------------
# _build_messages
# ---------------------------------------------------------------------------

class BuildMessagesTests(unittest.TestCase):
    def test_persona_overrides_dialogue_systems(self):
        p = _make_provider(system_prompt="PERSONA")
        dialogue = [
            {"role": "system", "content": "DIALOGUE-SYS-1"},
            {"role": "system", "content": "DIALOGUE-SYS-2"},
            {"role": "user", "content": "Hi"},
        ]
        msgs = p._build_messages(dialogue)
        self.assertEqual(msgs[0], {"role": "system", "content": "PERSONA"})
        # System messages from dialogue must be dropped, not duplicated.
        sys_count = sum(1 for m in msgs if m["role"] == "system")
        self.assertEqual(sys_count, 1)

    def test_no_persona_merges_dialogue_systems(self):
        p = _make_provider()
        p._persona = ""  # explicit override
        dialogue = [
            {"role": "system", "content": "A"},
            {"role": "system", "content": "B"},
            {"role": "user", "content": "Hi"},
        ]
        msgs = p._build_messages(dialogue)
        self.assertEqual(msgs[0]["role"], "system")
        self.assertIn("A", msgs[0]["content"])
        self.assertIn("B", msgs[0]["content"])

    def test_turn_suffix_appended_to_last_user_only(self):
        p = _make_provider(system_prompt="P")
        dialogue = [
            {"role": "user", "content": "first"},
            {"role": "assistant", "content": "ack"},
            {"role": "user", "content": "second"},
        ]
        msgs = p._build_messages(dialogue)
        # The non-system messages are in indices 1..3.
        user_msgs = [m for m in msgs if m["role"] == "user"]
        self.assertEqual(len(user_msgs), 2)
        self.assertEqual(user_msgs[0]["content"], "first")  # no suffix
        self.assertTrue(user_msgs[1]["content"].startswith("second"))
        self.assertGreater(len(user_msgs[1]["content"]), len("second"))  # suffix present


# ---------------------------------------------------------------------------
# _completions_url
# ---------------------------------------------------------------------------

class CompletionsUrlTests(unittest.TestCase):
    def test_appends_chat_completions_when_missing(self):
        p = _make_provider(url="http://x/v1")
        self.assertEqual(p._completions_url(), "http://x/v1/chat/completions")

    def test_does_not_double_append(self):
        p = _make_provider(url="http://x/v1/chat/completions")
        self.assertEqual(p._completions_url(), "http://x/v1/chat/completions")


# ---------------------------------------------------------------------------
# _strip_remember
# ---------------------------------------------------------------------------

class StripRememberTests(unittest.TestCase):
    def test_extracts_single_fact(self):
        clean, facts = _t1._strip_remember("Sure! [REMEMBER: user's birthday is March 4]")
        self.assertEqual(facts, ["user's birthday is March 4"])
        self.assertEqual(clean, "Sure!")

    def test_extracts_multiple_facts(self):
        clean, facts = _t1._strip_remember(
            "Got it [REMEMBER: cat is named Mochi] and [REMEMBER: lives in Brisbane]."
        )
        self.assertEqual(facts, ["cat is named Mochi", "lives in Brisbane"])
        self.assertNotIn("REMEMBER", clean)

    def test_no_markers_returns_input_unchanged(self):
        clean, facts = _t1._strip_remember("just text")
        self.assertEqual(clean, "just text")
        self.assertEqual(facts, [])

    def test_empty_input(self):
        clean, facts = _t1._strip_remember("")
        self.assertEqual(clean, "")
        self.assertEqual(facts, [])


# ---------------------------------------------------------------------------
# _dispatch_tool
# ---------------------------------------------------------------------------

class DispatchToolTests(unittest.TestCase):
    def test_success_returns_result(self):
        p = _make_provider()
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {"result": "the answer"}
        with patch("requests.post", return_value=mock_resp) as mp:
            out = p._dispatch_tool("memory_lookup", {"query": "birthday"}, "sess-1")
        self.assertEqual(out, "the answer")
        # Sanity: posted to escalate endpoint with the right shape.
        kwargs = mp.call_args.kwargs
        self.assertIn("/api/voice/escalate", mp.call_args.args[0])
        self.assertEqual(kwargs["json"]["tool"], "memory_lookup")
        self.assertEqual(kwargs["json"]["session_id"], "sess-1")

    def test_think_hard_uses_long_timeout(self):
        p = _make_provider()
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {"result": "ok"}
        with patch("requests.post", return_value=mock_resp) as mp:
            p._dispatch_tool("think_hard", {"question": "?"}, "s")
        self.assertEqual(mp.call_args.kwargs["timeout"], _t1.BRIDGE_TIMEOUT_LONG)

    def test_other_tools_use_short_timeout(self):
        p = _make_provider()
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {"result": "ok"}
        with patch("requests.post", return_value=mock_resp) as mp:
            p._dispatch_tool("memory_lookup", {}, "s")
        self.assertEqual(mp.call_args.kwargs["timeout"], _t1.BRIDGE_TIMEOUT_SHORT)

    def test_timeout_returns_friendly_string(self):
        p = _make_provider()
        import requests as _requests
        with patch(
            "requests.post",
            side_effect=_requests.exceptions.Timeout("slow"),
        ):
            out = p._dispatch_tool("think_hard", {}, "s")
        self.assertIn("took too long", out)
        self.assertIn("think_hard", out)

    def test_generic_failure_returns_unavailable(self):
        p = _make_provider()
        with patch(
            "requests.post",
            side_effect=ConnectionError("refused"),
        ):
            out = p._dispatch_tool("memory_lookup", {}, "s")
        self.assertIn("unavailable", out)

    def test_result_truncated_to_1000_chars(self):
        p = _make_provider()
        long_result = "x" * 5000
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {"result": long_result}
        with patch("requests.post", return_value=mock_resp):
            out = p._dispatch_tool("memory_lookup", {}, "s")
        self.assertEqual(len(out), 1000)


# ---------------------------------------------------------------------------
# response() — the live voice path
# ---------------------------------------------------------------------------

class ResponseTextOnlyPathTests(unittest.TestCase):
    """No tool_calls in the first-call response — fast path."""

    def test_yields_content_and_logs_memory(self):
        p = _make_provider()
        first_resp = MagicMock()
        first_resp.status_code = 200
        first_resp.raise_for_status = MagicMock()
        first_resp.json.return_value = {
            "choices": [{"message": {"role": "assistant", "content": "😊 Hi there!"}}],
        }

        with patch("requests.post") as mp:
            mp.return_value = first_resp
            out = list(p.response("sess-1", [{"role": "user", "content": "hello"}]))

        full = "".join(out)
        self.assertIn("Hi there!", full)
        # First call = chat/completions; second call = /api/voice/memory_log (fire-and-forget).
        urls_posted = [c.args[0] for c in mp.call_args_list]
        self.assertTrue(any("chat/completions" in u for u in urls_posted))
        self.assertTrue(any("/api/voice/memory_log" in u for u in urls_posted))

    def test_strips_remember_marker_and_posts_async(self):
        p = _make_provider()
        first_resp = MagicMock()
        first_resp.status_code = 200
        first_resp.raise_for_status = MagicMock()
        first_resp.json.return_value = {
            "choices": [{"message": {
                "role": "assistant",
                "content": "😊 Got it! [REMEMBER: birthday is May 4]",
            }}],
        }
        with patch("requests.post") as mp:
            mp.return_value = first_resp
            out = list(p.response("s", [{"role": "user", "content": "my bday is may 4"}]))

        full = "".join(out)
        self.assertNotIn("REMEMBER", full)
        # /api/voice/remember posted with the extracted fact.
        remember_calls = [
            c for c in mp.call_args_list
            if "/api/voice/remember" in c.args[0]
        ]
        self.assertEqual(len(remember_calls), 1)
        self.assertEqual(
            remember_calls[0].kwargs["json"]["fact"], "birthday is May 4",
        )

    def test_first_call_failure_yields_fallback(self):
        p = _make_provider()
        with patch(
            "requests.post",
            side_effect=ConnectionError("backend down"),
        ):
            out = list(p.response("s", [{"role": "user", "content": "hi"}]))
        full = "".join(out)
        self.assertIn("brain is offline", full)


class ResponseToolPathTests(unittest.TestCase):
    """First-call returns tool_calls — escalation handshake."""

    def test_escalation_chains_to_streaming_final(self):
        p = _make_provider()

        first_resp = MagicMock()
        first_resp.status_code = 200
        first_resp.raise_for_status = MagicMock()
        first_resp.json.return_value = {
            "choices": [{"message": {
                "role": "assistant",
                "content": "",
                "tool_calls": [{
                    "id": "call-1",
                    "function": {
                        "name": "memory_lookup",
                        "arguments": '{"query": "birthday"}',
                    },
                }],
            }}],
        }
        escalate_resp = MagicMock()
        escalate_resp.raise_for_status = MagicMock()
        escalate_resp.json.return_value = {"result": "user's birthday is March 4"}
        stream_resp = _streaming_response(["😊 Your", " birthday", " is March 4."])

        def fake_post(url, **kwargs):
            if "chat/completions" in url and kwargs.get("stream"):
                return stream_resp
            if "chat/completions" in url:
                return first_resp
            if "/api/voice/escalate" in url:
                return escalate_resp
            if "/api/voice/memory_log" in url:
                return MagicMock(raise_for_status=MagicMock())
            raise AssertionError(f"unexpected POST to {url}")

        with patch("requests.post", side_effect=fake_post) as mp:
            out = list(p.response("s", [{"role": "user", "content": "what's my birthday"}]))

        full = "".join(out)
        self.assertIn("March 4", full)
        # The escalation call must have happened with the right tool name.
        escalate_calls = [
            c for c in mp.call_args_list if "/api/voice/escalate" in c.args[0]
        ]
        self.assertEqual(len(escalate_calls), 1)
        self.assertEqual(escalate_calls[0].kwargs["json"]["tool"], "memory_lookup")
        self.assertEqual(
            escalate_calls[0].kwargs["json"]["args"], {"query": "birthday"},
        )

    def test_take_photo_filler_yielded_before_dispatch(self):
        p = _make_provider()

        first_resp = MagicMock()
        first_resp.status_code = 200
        first_resp.raise_for_status = MagicMock()
        first_resp.json.return_value = {
            "choices": [{"message": {
                "role": "assistant",
                "content": "",
                "tool_calls": [{
                    "id": "c1",
                    "function": {"name": "take_photo", "arguments": "{}"},
                }],
            }}],
        }
        escalate_resp = MagicMock()
        escalate_resp.raise_for_status = MagicMock()
        escalate_resp.json.return_value = {"result": "I see a cat"}
        stream_resp = _streaming_response(["😊 A cat!"])

        def fake_post(url, **kwargs):
            if "chat/completions" in url and kwargs.get("stream"):
                return stream_resp
            if "chat/completions" in url:
                return first_resp
            if "/api/voice/escalate" in url:
                return escalate_resp
            return MagicMock(raise_for_status=MagicMock())

        with patch("requests.post", side_effect=fake_post):
            out = list(p.response("s", [{"role": "user", "content": "what do you see"}]))

        # The filler ("Let me have a look") must appear before the final answer.
        full = "".join(out)
        self.assertIn("have a look", full)
        self.assertIn("cat", full)
        self.assertLess(full.index("have a look"), full.index("cat"))


if __name__ == "__main__":
    unittest.main()
