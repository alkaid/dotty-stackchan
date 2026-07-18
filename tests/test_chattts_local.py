import importlib.util
import queue
import sys
import types
from pathlib import Path
from unittest.mock import patch

import numpy as np


class _Logger:
    def bind(self, **_kwargs):
        return self

    def info(self, *_args, **_kwargs):
        pass

    def warning(self, *_args, **_kwargs):
        pass

    def error(self, *_args, **_kwargs):
        pass


class _FakeBase:
    def __init__(self, _config, _delete_audio_file):
        self.tts_text_queue = queue.Queue()
        self.tts_audio_queue = queue.Queue()
        self.tts_stop_request = False
        self.processed_chars = 0
        self.tts_text_buff = []

    def handle_opus(self, data):
        self.tts_audio_queue.put(("middle", data, None, None))

    def _process_before_stop_play_files(self):
        self.tts_audio_queue.put(("last", [], None, None))

    async def close(self):
        pass


class _FakeEncoder:
    instances = []

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.calls = []
        self.closed = False
        self.__class__.instances.append(self)

    def encode_pcm_to_opus_stream(self, pcm, end_of_stream, callback):
        self.calls.append((pcm, end_of_stream))
        callback(b"opus")

    def close(self):
        self.closed = True


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
    utils_module = types.ModuleType("core.utils")
    utils_module.opus_encoder_utils = types.SimpleNamespace(
        OpusEncoderUtils=_FakeEncoder
    )
    utils_module.textUtils = types.SimpleNamespace(
        get_string_no_punctuation_or_emoji=lambda value: value
    )
    tts_utils_module = types.ModuleType("core.utils.tts")
    tts_utils_module.MarkdownCleaner = types.SimpleNamespace(
        clean_markdown=lambda value: value
    )
    stubs = {
        "config": types.ModuleType("config"),
        "config.logger": logger_module,
        "core": types.ModuleType("core"),
        "core.providers": types.ModuleType("core.providers"),
        "core.providers.tts": types.ModuleType("core.providers.tts"),
        "core.providers.tts.base": base_module,
        "core.providers.tts.dto": types.ModuleType("core.providers.tts.dto"),
        "core.providers.tts.dto.dto": dto_module,
        "core.utils": utils_module,
        "core.utils.tts": tts_utils_module,
    }
    path = (
        Path(__file__).parents[1]
        / "custom-providers"
        / "chattts_local"
        / "chattts_local.py"
    )
    spec = importlib.util.spec_from_file_location("chattts_local_under_test", path)
    module = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, stubs):
        spec.loader.exec_module(module)
    return module


PROVIDER = _load_provider_module()


class _Device:
    def __init__(self, value):
        self.value = value
        self.type = value.split(":", 1)[0]

    def __str__(self):
        return self.value


class _Cuda:
    available = True

    @classmethod
    def is_available(cls):
        return cls.available

    @staticmethod
    def manual_seed_all(_seed):
        pass


class _Params:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


class _Chat:
    RefineTextParams = _Params
    InferCodeParams = _Params
    next_waves = []

    def __init__(self):
        self.loaded = None
        self.interrupts = 0

    def load(self, **kwargs):
        self.loaded = kwargs
        return True

    def sample_random_speaker(self):
        return "stable-speaker"

    def infer(self, *_args, **_kwargs):
        yield from self.next_waves

    def interrupt(self):
        self.interrupts += 1


def _fake_runtime(cuda=True):
    _Cuda.available = cuda
    torch_module = types.ModuleType("torch")
    torch_module.cuda = _Cuda
    torch_module.device = _Device
    torch_module.manual_seed = lambda _seed: None
    chattts_module = types.ModuleType("ChatTTS")
    chattts_module.Chat = _Chat
    return {"torch": torch_module, "ChatTTS": chattts_module}


def test_pcm16_bytes_clips_and_sanitizes():
    pcm = PROVIDER._pcm16_bytes(
        np.array([[np.nan, -2.0, -0.5, 0.5, 2.0]], dtype=np.float32),
        gain_db=0.0,
    )
    assert np.frombuffer(pcm, dtype=np.int16).tolist() == [
        0,
        -32767,
        -16383,
        16383,
        32767,
    ]


def test_chattts_text_translation_removes_typographic_punctuation():
    text = "I\u2019m ready \u2014 really\u2026 \u201chello\u201d"
    assert text.translate(PROVIDER._CHAT_TTS_TEXT_TRANSLATION) == (
        'I\'m ready - really... "hello"'
    )


def test_provider_loads_custom_model_on_auto_cuda(tmp_path):
    _FakeEncoder.instances.clear()
    with patch.dict(sys.modules, _fake_runtime(cuda=True)):
        provider = PROVIDER.TTSProvider({"model_path": str(tmp_path)}, True)
    assert str(provider.device) == "cuda"
    assert provider.chat.loaded["source"] == "custom"
    assert provider.chat.loaded["custom_path"] == str(tmp_path)
    assert provider.params_infer_code.spk_emb == "stable-speaker"
    assert _FakeEncoder.instances[-1].kwargs == {
        "sample_rate": 24000,
        "channels": 1,
        "frame_size_ms": 60,
    }


def test_stream_encodes_full_frame_and_flushes_tail(tmp_path):
    _FakeEncoder.instances.clear()
    _Chat.next_waves = [
        np.full((1, 1440), 0.25, dtype=np.float32),
        np.full((1, 720), -0.25, dtype=np.float32),
    ]
    with patch.dict(sys.modules, _fake_runtime(cuda=True)):
        provider = PROVIDER.TTSProvider({"model_path": str(tmp_path)}, True)
    provider.conn = types.SimpleNamespace(client_abort=False)
    provider.current_sentence_id = "sentence-1"
    provider.text_to_speak("hello 你好", is_last=True)

    calls = _FakeEncoder.instances[-1].calls
    assert [len(pcm) for pcm, _end in calls] == [2880, 1440]
    assert [end for _pcm, end in calls] == [False, True]
    first = provider.tts_audio_queue.get_nowait()
    assert first == ("first", [], "hello 你好", "sentence-1")
    assert provider.tts_audio_queue.qsize() == 3


def test_stream_interrupt_discards_audio(tmp_path):
    _FakeEncoder.instances.clear()
    _Chat.next_waves = [np.full((1, 1440), 0.25, dtype=np.float32)]
    with patch.dict(sys.modules, _fake_runtime(cuda=False)):
        provider = PROVIDER.TTSProvider({"model_path": str(tmp_path)}, True)
    provider.conn = types.SimpleNamespace(client_abort=True)
    provider.text_to_speak("stop", is_last=False)
    assert provider.chat.interrupts == 1
    assert _FakeEncoder.instances[-1].calls == []
