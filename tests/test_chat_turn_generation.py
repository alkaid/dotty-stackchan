"""Regression coverage for abort state leaking into a replacement voice turn."""

import importlib.util
import pathlib
import sys
import types
import unittest
from contextlib import contextmanager


_ROOT = pathlib.Path(__file__).parent.parent


def _stub_module(name: str, **attrs) -> None:
    module = types.ModuleType(name)
    for key, value in attrs.items():
        setattr(module, key, value)
    sys.modules[name] = module


@contextmanager
def _container_import_stubs():
    names = (
        "core",
        "core.utils",
        "core.handle",
        "core.utils.util",
        "core.utils.textUtils",
        "core.handle.abortHandle",
        "core.handle.intentHandler",
        "core.utils.output_counter",
        "core.handle.sendAudioHandle",
        "core.utils.device_command",
    )
    missing = object()
    previous = {name: sys.modules.get(name, missing) for name in names}
    try:
        for package in ("core", "core.utils", "core.handle"):
            _stub_module(package)
        _stub_module("core.utils.util", audio_to_data=lambda *_args, **_kwargs: None)
        _stub_module(
            "core.utils.textUtils",
            build_response_language_instruction=lambda *_args, **_kwargs: "",
        )
        _stub_module("core.handle.abortHandle", handleAbortMessage=lambda *_args: None)
        _stub_module("core.handle.intentHandler", handle_user_intent=lambda *_args: None)
        _stub_module(
            "core.utils.output_counter",
            check_device_output_limit=lambda *_args: False,
        )
        _stub_module(
            "core.handle.sendAudioHandle",
            send_stt_message=lambda *_args: None,
            SentenceType=object,
        )
        _stub_module("core.utils.device_command", call_tool=lambda *_args, **_kwargs: None)
        yield
    finally:
        for name, module in previous.items():
            if module is missing:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = module


with _container_import_stubs():
    _spec = importlib.util.spec_from_file_location(
        "receive_audio_chat_turn_under_test", _ROOT / "receiveAudioHandle.py"
    )
    assert _spec is not None and _spec.loader is not None
    _receive_audio = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(_receive_audio)

_patch_spec = importlib.util.spec_from_file_location(
    "connection_turn_patch_under_test",
    _ROOT
    / "custom-providers"
    / "xiaozhi-patches"
    / "patch_connection_turn_generation.py",
)
assert _patch_spec is not None and _patch_spec.loader is not None
_connection_patch = importlib.util.module_from_spec(_patch_spec)
_patch_spec.loader.exec_module(_connection_patch)


class _Logger:
    def bind(self, **_kwargs):
        return self

    def debug(self, *_args, **_kwargs):
        pass


class _Executor:
    def __init__(self):
        self.calls = []

    def submit(self, *args):
        self.calls.append(args)
        return types.SimpleNamespace()


class _Conn:
    def __init__(self):
        self.logger = _Logger()
        self.executor = _Executor()
        self.client_abort = True

    def chat(self, *_args):
        pass


class TestChatTurnGeneration(unittest.TestCase):
    def test_replacement_turn_gets_a_new_generation_without_reviving_old_turn(self):
        conn = _Conn()

        _receive_audio._submit_chat(conn, "first")
        conn.client_abort = True
        _receive_audio._submit_chat(conn, "replacement")

        self.assertEqual(conn._dotty_chat_generation, 2)
        self.assertTrue(
            conn.client_abort,
            "abort stays set until replacement chat owns its new sentence id",
        )
        self.assertEqual(conn.executor.calls[0], (conn.chat, "first", 0, 1))
        self.assertEqual(conn.executor.calls[1], (conn.chat, "replacement", 0, 2))

    def test_connection_patch_has_fail_closed_upstream_anchors(self):
        fixture = '''    def chat(self, query, depth=0):
        # 保存当前任务的sentence_id到局部变量，避免被新任务覆盖
        current_sentence_id = None
            self.sentence_id = current_sentence_id  # 更新共享属性
            self.dialogue.put(Message(role="user", content=query))
            for response in llm_responses:
                if self.client_abort:
                    break
            return
        # 处理function call
        # 存储对话内容
        if len(response_message) > 0:
            self.chat(None, depth=depth + 1)
'''

        patched = _connection_patch.patch_source(fixture)

        self.assertIn("turn_generation=None", patched)
        self.assertIn("Skipping stale chat turn", patched)
        self.assertIn("self.client_abort = False", patched)
        self.assertIn("Discarding stale chat turn", patched)
        self.assertIn("turn_generation=turn_generation", patched)

    def test_connection_patch_rejects_upstream_drift(self):
        with self.assertRaisesRegex(RuntimeError, "chat signature"):
            _connection_patch.patch_source("def unrelated(): pass\n")


if __name__ == "__main__":
    unittest.main()
