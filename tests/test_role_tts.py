import importlib.util
import inspect
import asyncio
import queue
import sys
import types
from abc import ABC, abstractmethod
from pathlib import Path
from unittest.mock import AsyncMock, patch

import numpy as np


class _Logger:
    def bind(self, **_kwargs):
        return self

    def info(self, *_args, **_kwargs):
        pass

    def error(self, *_args, **_kwargs):
        pass


class _FakeBase(ABC):
    def __init__(self, _config, _delete_audio_file):
        self.tts_text_queue = queue.Queue()
        self.tts_audio_queue = queue.Queue()
        self.tts_stop_request = False
        self.processed_chars = 0
        self.tts_text_buff = []

    @abstractmethod
    def text_to_speak(self, text, output_file):
        raise NotImplementedError

    async def close(self):
        pass


class _FakeOpusEncoder:
    def __init__(self, **_kwargs):
        pass

    def encode_pcm_to_opus_stream(self, pcm, end_of_stream, callback):
        if pcm:
            callback(b"opus")

    def close(self):
        pass


def _load_provider_module():
    logger_module = types.ModuleType("config.logger")
    logger_module.setup_logging = lambda: _Logger()
    base_module = types.ModuleType("core.providers.tts.base")
    base_module.TTSProviderBase = _FakeBase
    dto_module = types.ModuleType("core.providers.tts.dto.dto")
    dto_module.ContentType = types.SimpleNamespace(TEXT="text", FILE="file")
    dto_module.InterfaceType = types.SimpleNamespace(SINGLE_STREAM="single_stream")
    dto_module.SentenceType = types.SimpleNamespace(
        FIRST="first", MIDDLE="middle", LAST="last"
    )
    dto_module.TTSMessageDTO = lambda **kwargs: types.SimpleNamespace(**kwargs)
    profile_module = types.ModuleType("core.providers.tts.profile_state")
    profile_module.DEFAULT_PROFILE = {
        "provider": "chattts",
        "config": {"seed": 42},
    }
    profile_module.load_active_voice = lambda *_args: profile_module.DEFAULT_PROFILE
    utils_module = types.ModuleType("core.utils")
    utils_module.opus_encoder_utils = types.SimpleNamespace(
        OpusEncoderUtils=_FakeOpusEncoder
    )
    utils_module.textUtils = types.SimpleNamespace(
        get_string_no_punctuation_or_emoji=lambda value: value
    )
    tts_utils_module = types.ModuleType("core.utils.tts")
    tts_utils_module.MarkdownCleaner = types.SimpleNamespace(
        clean_markdown=lambda value: value
    )
    edge_module = types.ModuleType("edge_tts")
    edge_module.Communicate = object
    pydub_module = types.ModuleType("pydub")
    pydub_module.AudioSegment = object
    stubs = {
        "config": types.ModuleType("config"),
        "config.logger": logger_module,
        "core": types.ModuleType("core"),
        "core.providers": types.ModuleType("core.providers"),
        "core.providers.tts": types.ModuleType("core.providers.tts"),
        "core.providers.tts.base": base_module,
        "core.providers.tts.dto": types.ModuleType("core.providers.tts.dto"),
        "core.providers.tts.dto.dto": dto_module,
        "core.providers.tts.profile_state": profile_module,
        "core.utils": utils_module,
        "core.utils.tts": tts_utils_module,
        "edge_tts": edge_module,
        "pydub": pydub_module,
    }
    path = (
        Path(__file__).parents[1]
        / "custom-providers"
        / "role_tts"
        / "role_tts.py"
    )
    spec = importlib.util.spec_from_file_location("role_tts_under_test", path)
    module = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, stubs):
        spec.loader.exec_module(module)
    return module


def test_provider_implements_tts_base_contract():
    provider_module = _load_provider_module()

    assert not inspect.isabstract(provider_module.TTSProvider)


def test_edge_profile_does_not_load_chattts_during_provider_init():
    provider_module = _load_provider_module()
    provider = provider_module.TTSProvider(
        {"model_path": "/missing-until-chattts-is-selected"}, False
    )

    assert provider.chat is None
    assert provider._ChatTTS is None
    assert provider.edge_streaming is True


def test_chattts_is_loaded_once_on_first_use():
    provider_module = _load_provider_module()
    provider = provider_module.TTSProvider({"model_path": "/models/chattts"}, False)
    loads = []

    class FakeCuda:
        @staticmethod
        def is_available():
            return False

    class FakeTorch:
        cuda = FakeCuda()

        @staticmethod
        def device(name):
            return types.SimpleNamespace(type=name)

    class FakeChat:
        def load(self, **kwargs):
            loads.append(kwargs)
            return True

    fake_chattts = types.SimpleNamespace(Chat=FakeChat)
    with (
        patch.object(
            provider_module,
            "_load_chattts_dependencies",
            return_value=(fake_chattts, FakeTorch),
        ),
        patch.object(provider_module.os.path, "isdir", return_value=True),
    ):
        provider._ensure_chattts_loaded()
        provider._ensure_chattts_loaded()

    assert len(loads) == 1
    assert provider.device.type == "cpu"


def test_edge_stream_emits_pcm_before_the_full_mp3_arrives():
    provider_module = _load_provider_module()

    async def scenario():
        release_tail = asyncio.Event()
        first_pcm = asyncio.Event()

        class FakeStdout:
            def __init__(self):
                self.items = asyncio.Queue()

            async def read(self, _size=-1):
                return await self.items.get()

        stdout = FakeStdout()

        class FakeStdin:
            def __init__(self):
                self.closing = False

            def write(self, data):
                if data == b"mp3-head":
                    stdout.items.put_nowait(b"p" * provider_module._PCM_FRAME_BYTES)

            async def drain(self):
                pass

            def is_closing(self):
                return self.closing

            def close(self):
                self.closing = True
                stdout.items.put_nowait(b"")

            async def wait_closed(self):
                pass

        class FakeStderr:
            async def read(self):
                return b""

        class FakeProcess:
            def __init__(self):
                self.stdin = FakeStdin()
                self.stdout = stdout
                self.stderr = FakeStderr()
                self.returncode = None

            async def wait(self):
                self.returncode = 0
                return 0

            def terminate(self):
                self.returncode = -15
                if not self.stdin.is_closing():
                    self.stdin.close()

        class FakeCommunicate:
            async def stream(self):
                yield {"type": "audio", "data": b"mp3-head"}
                await release_tail.wait()
                yield {"type": "audio", "data": b"mp3-tail"}

        provider = object.__new__(provider_module.TTSProvider)
        provider.ffmpeg_path = "ffmpeg"
        provider.conn = types.SimpleNamespace(client_abort=False)
        provider.tts_stop_request = False
        provider.pcm_buffer = bytearray()

        def encoded():
            provider.pcm_buffer.clear()
            first_pcm.set()

        provider._encode_available_pcm = encoded
        process = FakeProcess()
        provider_module.edge_tts.Communicate = lambda *_args, **_kwargs: FakeCommunicate()
        with patch.object(
            provider_module.asyncio,
            "create_subprocess_exec",
            AsyncMock(return_value=process),
        ):
            stream_task = asyncio.create_task(provider._stream_edge_audio("whole sentence", {}))
            await asyncio.wait_for(first_pcm.wait(), timeout=1)
            assert not release_tail.is_set(), "PCM must arrive before the MP3 stream ends"
            release_tail.set()
            assert await asyncio.wait_for(stream_task, timeout=1) is True

    asyncio.run(scenario())


class _FakeTimer:
    def __init__(self, interval, function, args=()):
        self.interval = interval
        self.function = function
        self.args = args
        self.daemon = False
        self.started = False
        self.cancelled = False

    def start(self):
        self.started = True

    def cancel(self):
        self.cancelled = True

    def fire(self):
        if not self.cancelled:
            self.function(*self.args)


def _filler_provider(provider_module):
    provider = provider_module.TTSProvider({}, False)
    provider.filler_enabled = True
    provider.filler_delay_ms = 1200
    provider.conn = types.SimpleNamespace(
        _dotty_chat_generation=7,
        _dotty_turn_id="trace-7",
        _dotty_tts_segment_started=False,
        _dotty_tts_segment_logged=False,
        _dotty_answer_first_opus=False,
        client_abort=False,
        sentence_id="sentence-7",
    )
    provider._ensure_filler_cache = lambda *_args: None
    provider._load_filler_cache = lambda *_args: ("让我想想。", [b"one", b"two"])
    return provider


def test_cached_filler_is_queued_once_before_a_slow_answer():
    provider_module = _load_provider_module()
    provider = _filler_provider(provider_module)
    profile = {
        "provider": "edge",
        "config": {"voice": "zh-CN-XiaoxiaoNeural"},
    }
    timer = None

    def make_timer(*args, **kwargs):
        nonlocal timer
        timer = _FakeTimer(*args, **kwargs)
        return timer

    with (
        patch.object(provider_module, "load_active_voice", return_value=profile),
        patch.object(provider_module.threading, "Timer", side_effect=make_timer),
    ):
        provider.arm_filler("trace-7", 7, "zh")
        assert timer is not None and timer.started
        assert timer.interval == 1.2
        timer.fire()

    assert provider.tts_audio_queue.get_nowait() == (
        "first", [b"one", b"two"], "让我想想。", "sentence-7"
    )
    assert provider.tts_audio_queue.empty()


def test_filler_delay_is_measured_from_the_turn_origin():
    provider_module = _load_provider_module()
    provider = _filler_provider(provider_module)
    provider.conn._dotty_turn_started_at = 99.4
    profile = {
        "provider": "edge",
        "config": {"voice": "zh-CN-XiaoxiaoNeural"},
    }
    timer = None

    def make_timer(*args, **kwargs):
        nonlocal timer
        timer = _FakeTimer(*args, **kwargs)
        return timer

    with (
        patch.object(provider_module, "load_active_voice", return_value=profile),
        patch.object(provider_module.time, "monotonic", return_value=100.0),
        patch.object(provider_module.threading, "Timer", side_effect=make_timer),
    ):
        provider.arm_filler("trace-7", 7, "zh")

    assert timer is not None and timer.started
    assert abs(timer.interval - 0.6) < 1e-9


def test_answer_segment_cancels_pending_filler():
    provider_module = _load_provider_module()
    provider = _filler_provider(provider_module)
    profile = {
        "provider": "edge",
        "config": {"voice": "zh-CN-XiaoxiaoNeural"},
    }
    timer = None

    def make_timer(*args, **kwargs):
        nonlocal timer
        timer = _FakeTimer(*args, **kwargs)
        return timer

    with (
        patch.object(provider_module, "load_active_voice", return_value=profile),
        patch.object(provider_module.threading, "Timer", side_effect=make_timer),
    ):
        provider.arm_filler("trace-7", 7, "zh")
        provider._mark_answer_segment_started()
        assert timer is not None and timer.cancelled
        timer.fire()

    assert provider.tts_audio_queue.empty()


def test_stale_or_aborted_turn_never_plays_filler():
    provider_module = _load_provider_module()
    for stale, aborted in ((True, False), (False, True)):
        provider = _filler_provider(provider_module)
        state = {
            "turn_id": "trace-7",
            "generation": 6 if stale else 7,
            "profile": {"provider": "edge", "config": {"voice": "zh-CN-X"}},
            "language": "zh",
        }
        state["timer"] = _FakeTimer(1.2, lambda: None)
        provider._pending_filler = state
        provider.conn.client_abort = aborted

        provider._play_filler_if_waiting(state)

        assert provider.tts_audio_queue.empty()


def test_pcm_gain_boosts_quiet_chattts_and_limits_peaks():
    provider_module = _load_provider_module()
    quiet = provider_module._pcm16_bytes([0.25], gain_db=6.0)
    peak = provider_module._pcm16_bytes([0.9], gain_db=6.0)

    assert 16000 < np.frombuffer(quiet, dtype=np.int16)[0] < 16500
    assert np.frombuffer(peak, dtype=np.int16)[0] == 32767


def test_text_to_speak_routes_to_profile_provider():
    provider_module = _load_provider_module()
    provider = object.__new__(provider_module.TTSProvider)
    calls = []
    provider._speak_chattts = lambda text, is_last, config: calls.append(
        ("chattts", text, is_last, config)
    )
    provider._speak_edge = lambda text, is_last, config: calls.append(
        ("edge", text, is_last, config)
    )

    provider.text_to_speak(
        "hello", True, profile={"provider": "edge", "config": {"voice": "au"}}
    )
    provider.text_to_speak(
        "你好", False, profile={"provider": "chattts", "config": {"seed": 7}}
    )

    assert calls == [
        ("edge", "hello", True, {"voice": "au"}),
        ("chattts", "你好", False, {"seed": 7}),
    ]
