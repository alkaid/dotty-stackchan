import importlib.util
import inspect
import queue
import sys
import types
from abc import ABC, abstractmethod
from pathlib import Path
from unittest.mock import patch


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
    utils_module.opus_encoder_utils = types.SimpleNamespace(OpusEncoderUtils=object)
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


def test_pcm_gain_boosts_quiet_chattts_and_limits_peaks():
    provider_module = _load_provider_module()
    quiet = provider_module._pcm16_bytes([0.25], gain_db=6.0)
    peak = provider_module._pcm16_bytes([0.9], gain_db=6.0)

    import numpy as np

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
