import asyncio
import hashlib
import io
import json
import os
import queue
import threading
import time
import traceback
import uuid
import wave

import edge_tts
import numpy as np
from pydub import AudioSegment

from config.logger import setup_logging
from core.providers.tts.base import TTSProviderBase
from core.providers.tts.dto.dto import (
    ContentType,
    InterfaceType,
    SentenceType,
    TTSMessageDTO,
)
from core.providers.tts.profile_state import DEFAULT_PROFILE, load_active_voice
from core.utils import opus_encoder_utils, textUtils
from core.utils.tts import MarkdownCleaner

TAG = __name__
logger = setup_logging()
_SPEAKER_LOCK = threading.Lock()
_PCM_FRAME_BYTES = 24000 * 60 // 1000 * 2
_FILLER_CACHE_VERSION = 1
_FILLER_PHRASES = {
    "zh": "让我想想。",
    "en": "Let me think.",
}

_TEXT_TRANSLATION = str.maketrans(
    {
        0x2018: "'",
        0x2019: "'",
        0x201C: '"',
        0x201D: '"',
        0x2013: "-",
        0x2014: "-",
        0x2026: "...",
    }
)


def _pcm16_bytes(waveform, gain_db=3.0):
    samples = np.asarray(waveform, dtype=np.float32)
    if samples.ndim > 1:
        samples = samples[0]
    samples = np.nan_to_num(samples.reshape(-1), nan=0.0, posinf=1.0, neginf=-1.0)
    samples *= 10.0 ** (float(gain_db) / 20.0)
    return (np.clip(samples, -1.0, 1.0) * 32767.0).astype(np.int16).tobytes()


def _config_bool(value, default=False):
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ("1", "true", "yes", "on")


def _load_chattts_dependencies():
    import ChatTTS
    import torch

    return ChatTTS, torch


class TTSProvider(TTSProviderBase):
    """Role-aware ChatTTS/EdgeTTS provider with per-utterance selection."""

    def __init__(self, config, delete_audio_file):
        super().__init__(config, delete_audio_file)
        self.interface_type = InterfaceType.SINGLE_STREAM
        self.audio_format = "pcm"
        self.before_stop_play_files = []
        self.roles_path = str(
            config.get("roles_path", "/var/lib/dotty-bridge/state/roles.json")
        )
        self.voices_path = str(
            config.get("voices_path", "/var/lib/dotty-bridge/state/voices.json")
        )
        self.model_path = str(
            config.get("model_path", "/opt/xiaozhi-esp32-server/models/chattts")
        )
        self._requested_device = str(config.get("device", "auto")).strip().lower()
        self.edge_streaming = _config_bool(config.get("edge_streaming"), True)
        self.ffmpeg_path = str(config.get("ffmpeg_path", "ffmpeg"))
        filler_config = config.get("filler") or {}
        self.filler_enabled = _config_bool(filler_config.get("enabled"), False)
        self.filler_delay_ms = max(0, int(filler_config.get("delay_ms", 1200)))
        self.filler_cache_dir = str(
            filler_config.get(
                "cache_dir", "/opt/xiaozhi-esp32-server/tmp/filler-cache"
            )
        )
        self.filler_max_cache_bytes = max(
            0, int(filler_config.get("max_cache_bytes", 16 * 1024 * 1024))
        )
        self.device = None
        self._torch = None
        self._ChatTTS = None
        self.chat = None
        self._chat_load_lock = threading.Lock()
        self._chat_infer_lock = threading.Lock()

        self.opus_encoder = opus_encoder_utils.OpusEncoderUtils(
            sample_rate=24000, channels=1, frame_size_ms=60
        )
        self.pcm_buffer = bytearray()
        self._speakers = {}
        self._preview_profiles = {}
        self._preview_lock = threading.Lock()
        self._filler_lock = threading.RLock()
        self._filler_cache = {}
        self._filler_warming = set()
        self._pending_chat_warms = {}
        self._pending_filler = None
        logger.bind(tag=TAG).info(
            f"role_tts ready edge_streaming={self.edge_streaming} "
            f"chattts=lazy filler={self.filler_enabled}"
        )
        if self.filler_enabled:
            profile = load_active_voice(
                self.roles_path, self.voices_path, DEFAULT_PROFILE
            )
            for language in self._supported_filler_languages(profile):
                self._ensure_filler_cache(profile, language)

    def _ensure_chattts_loaded(self):
        if self.chat is not None:
            return
        with self._chat_load_lock:
            if self.chat is not None:
                return
            ChatTTS, torch = _load_chattts_dependencies()
            if not os.path.isdir(self.model_path):
                raise ValueError(f"role_tts: model_path missing: {self.model_path!r}")

            requested_device = self._requested_device
            if requested_device == "auto":
                requested_device = "cuda" if torch.cuda.is_available() else "cpu"
            if requested_device.startswith("cuda") and not torch.cuda.is_available():
                raise ValueError("role_tts: CUDA requested but torch.cuda is unavailable")

            device = torch.device(requested_device)
            chat = ChatTTS.Chat()
            loaded = chat.load(
                source="custom",
                custom_path=self.model_path,
                device=device,
                compile=False,
            )
            if not loaded:
                raise RuntimeError("role_tts: ChatTTS model validation or loading failed")

            self.device = device
            self._torch = torch
            self._ChatTTS = ChatTTS
            self.chat = chat
            logger.bind(tag=TAG).info(
                f"role_tts loaded model={self.model_path!r} device={self.device}"
            )

    def _speaker_for_seed(self, seed):
        self._ensure_chattts_loaded()
        seed = int(seed)
        if seed in self._speakers:
            return self._speakers[seed]
        with _SPEAKER_LOCK:
            if seed not in self._speakers:
                self._torch.manual_seed(seed)
                if self.device.type == "cuda":
                    self._torch.cuda.manual_seed_all(seed)
                self._speakers[seed] = self.chat.sample_random_speaker()
        return self._speakers[seed]

    def _profile_for_sentence(self):
        sentence_id = getattr(self, "current_sentence_id", None)
        with self._preview_lock:
            preview = self._preview_profiles.get(sentence_id)
        if preview:
            return preview
        return load_active_voice(self.roles_path, self.voices_path, DEFAULT_PROFILE)

    def _log_latency(self, phase):
        turn_id = getattr(self.conn, "_dotty_turn_id", None)
        started_at = getattr(self.conn, "_dotty_turn_started_at", None)
        if not turn_id or started_at is None:
            return
        elapsed_ms = max(0, round((time.monotonic() - started_at) * 1000))
        logger.bind(tag=TAG).info(
            f"DOTTY_LATENCY component=role_tts turn={turn_id} "
            f"phase={phase} elapsed_ms={elapsed_ms}"
        )

    def _profile_cache_payload(self, profile, language):
        return {
            "version": _FILLER_CACHE_VERSION,
            "provider": profile.get("provider"),
            "config": profile.get("config") or {},
            "language": language,
            "text": _FILLER_PHRASES[language],
        }

    def _filler_cache_key(self, profile, language):
        payload = json.dumps(
            self._profile_cache_payload(profile, language),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()

    def _supported_filler_languages(self, profile):
        provider = profile.get("provider")
        if provider == "chattts":
            return ("zh", "en")
        if provider == "edge":
            voice = str((profile.get("config") or {}).get("voice", "")).lower()
            if voice.startswith(("zh-", "yue-")):
                return ("zh",)
            if voice.startswith("en-"):
                return ("en",)
        return ()

    def _normalise_filler_language(self, profile, language):
        value = str(language or "").strip().lower()
        if value.startswith(("zh", "yue")):
            candidate = "zh"
        elif value.startswith("en"):
            candidate = "en"
        else:
            return None
        return candidate if candidate in self._supported_filler_languages(profile) else None

    def _cache_path(self, key):
        return os.path.join(self.filler_cache_dir, f"{key}.wav")

    def _pcm_to_opus_packets(self, pcm):
        encoder = opus_encoder_utils.OpusEncoderUtils(
            sample_rate=24000, channels=1, frame_size_ms=60
        )
        packets = []

        def collect(packet):
            if packet:
                packets.append(packet)

        try:
            for offset in range(0, len(pcm), _PCM_FRAME_BYTES):
                frame = pcm[offset : offset + _PCM_FRAME_BYTES]
                is_last = offset + _PCM_FRAME_BYTES >= len(pcm)
                if len(frame) < _PCM_FRAME_BYTES:
                    frame += b"\x00" * (_PCM_FRAME_BYTES - len(frame))
                encoder.encode_pcm_to_opus_stream(
                    frame, end_of_stream=is_last, callback=collect
                )
        finally:
            encoder.close()
        return packets

    def _load_filler_cache(self, profile, language):
        key = self._filler_cache_key(profile, language)
        with self._filler_lock:
            cached = self._filler_cache.get(key)
        if cached is not None:
            return cached

        path = self._cache_path(key)
        try:
            with wave.open(path, "rb") as wav_file:
                if (
                    wav_file.getnchannels() != 1
                    or wav_file.getsampwidth() != 2
                    or wav_file.getframerate() != 24000
                ):
                    raise ValueError("unexpected filler WAV format")
                pcm = wav_file.readframes(wav_file.getnframes())
            packets = self._pcm_to_opus_packets(pcm)
            if not packets:
                return None
            cached = (_FILLER_PHRASES[language], packets)
            with self._filler_lock:
                self._filler_cache[key] = cached
            return cached
        except (OSError, EOFError, ValueError, wave.Error):
            return None

    def _write_filler_cache(self, profile, language, pcm):
        if not pcm:
            return
        os.makedirs(self.filler_cache_dir, exist_ok=True)
        key = self._filler_cache_key(profile, language)
        path = self._cache_path(key)
        temporary = f"{path}.{uuid.uuid4().hex}.tmp"
        try:
            with wave.open(temporary, "wb") as wav_file:
                wav_file.setnchannels(1)
                wav_file.setsampwidth(2)
                wav_file.setframerate(24000)
                wav_file.writeframes(pcm)
            os.replace(temporary, path)
            self._prune_filler_cache()
            self._load_filler_cache(profile, language)
        finally:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass

    def _prune_filler_cache(self):
        if self.filler_max_cache_bytes <= 0:
            return
        try:
            entries = [
                entry
                for entry in os.scandir(self.filler_cache_dir)
                if entry.is_file() and entry.name.endswith(".wav")
            ]
            total = sum(entry.stat().st_size for entry in entries)
            for entry in sorted(entries, key=lambda item: item.stat().st_mtime):
                if total <= self.filler_max_cache_bytes:
                    break
                size = entry.stat().st_size
                os.unlink(entry.path)
                total -= size
        except OSError:
            logger.bind(tag=TAG).warning("RoleTTS filler cache pruning failed")

    def _render_chattts_pcm(self, text, config):
        self._ensure_chattts_loaded()
        params_refine, params_infer = self._chattts_params(config)
        pcm_parts = []
        with self._chat_infer_lock:
            stream = self.chat.infer(
                [text], stream=True, split_text=False,
                params_refine_text=params_refine,
                params_infer_code=params_infer,
            )
            try:
                for waveform in stream:
                    pcm = _pcm16_bytes(waveform, config.get("gain_db", 3.0))
                    if pcm:
                        pcm_parts.append(pcm)
            finally:
                close = getattr(stream, "close", None)
                if close:
                    close()
        return b"".join(pcm_parts)

    def _render_filler(self, profile, language):
        key = self._filler_cache_key(profile, language)
        try:
            config = profile.get("config") or {}
            if profile.get("provider") == "edge":
                pcm = asyncio.run(self._edge_pcm(_FILLER_PHRASES[language], config))
            else:
                pcm = self._render_chattts_pcm(_FILLER_PHRASES[language], config)
            self._write_filler_cache(profile, language, pcm)
        except Exception as exc:
            logger.bind(tag=TAG).warning(
                f"RoleTTS filler warm failed provider={profile.get('provider')!r} "
                f"language={language!r}: {exc}"
            )
        finally:
            with self._filler_lock:
                self._filler_warming.discard(key)

    def _ensure_filler_cache(self, profile, language):
        if self._load_filler_cache(profile, language) is not None:
            return
        key = self._filler_cache_key(profile, language)
        with self._filler_lock:
            if key in self._filler_warming:
                return
            self._filler_warming.add(key)
            if profile.get("provider") == "chattts":
                self._pending_chat_warms[key] = (profile, language)
                return
        thread = threading.Thread(
            target=self._render_filler,
            args=(profile, language),
            name=f"role-tts-filler-{language}",
            daemon=True,
        )
        thread.start()

    def _warm_pending_chat_fillers(self):
        with self._filler_lock:
            pending = list(self._pending_chat_warms.values())
            self._pending_chat_warms.clear()
        for profile, language in pending:
            if self.conn.client_abort or not self.tts_text_queue.empty():
                key = self._filler_cache_key(profile, language)
                with self._filler_lock:
                    self._filler_warming.discard(key)
                continue
            self._render_filler(profile, language)

    def arm_filler(self, turn_id, generation, language):
        if not self.filler_enabled or self.conn is None:
            return
        profile = load_active_voice(self.roles_path, self.voices_path, DEFAULT_PROFILE)
        language = self._normalise_filler_language(profile, language)
        if language is None:
            return
        self._ensure_filler_cache(profile, language)

        with self._filler_lock:
            if self._pending_filler is not None:
                self._pending_filler["timer"].cancel()
            state = {
                "turn_id": turn_id,
                "generation": generation,
                "profile": profile,
                "language": language,
            }
            delay_seconds = self.filler_delay_ms / 1000.0
            started_at = getattr(self.conn, "_dotty_turn_started_at", None)
            if isinstance(started_at, (int, float)):
                elapsed_seconds = max(0.0, time.monotonic() - started_at)
                delay_seconds = max(0.0, delay_seconds - elapsed_seconds)
            timer = threading.Timer(
                delay_seconds,
                self._play_filler_if_waiting,
                args=(state,),
            )
            timer.daemon = True
            state["timer"] = timer
            self._pending_filler = state
            timer.start()

    def _play_filler_if_waiting(self, state):
        with self._filler_lock:
            if self._pending_filler is not state:
                return
            if (
                getattr(self.conn, "_dotty_chat_generation", None)
                != state["generation"]
                or getattr(self.conn, "_dotty_turn_id", None) != state["turn_id"]
                or getattr(self.conn, "_dotty_tts_segment_started", False)
                or self.conn.client_abort
            ):
                self._pending_filler = None
                return
            cached = self._load_filler_cache(state["profile"], state["language"])
            if cached is None:
                self._pending_filler = None
                return
            text, packets = cached
            sentence_id = getattr(self.conn, "sentence_id", None)
            if not sentence_id:
                self._pending_filler = None
                return
            self.tts_audio_queue.put((SentenceType.FIRST, packets, text, sentence_id))
            self._pending_filler = None
            self._log_latency("filler_start")

    def _mark_answer_segment_started(self):
        self.conn._dotty_tts_segment_started = True
        with self._filler_lock:
            state = self._pending_filler
            if state is not None:
                state["timer"].cancel()
                self._pending_filler = None
        if not getattr(self.conn, "_dotty_tts_segment_logged", False):
            self.conn._dotty_tts_segment_logged = True
            self._log_latency("tts_segment_start")

    def queue_preview(self, text, profile):
        sentence_id = uuid.uuid4().hex
        with self._preview_lock:
            # A new preview supersedes any queued preview. Stale sentence IDs
            # are discarded by the TTS thread, so their profiles can go too.
            self._preview_profiles.clear()
            self._preview_profiles[sentence_id] = profile
        self.conn.sentence_id = sentence_id
        for sentence_type, content in (
            (SentenceType.FIRST, ""),
            (SentenceType.MIDDLE, text),
            (SentenceType.LAST, ""),
        ):
            self.tts_text_queue.put(TTSMessageDTO(
                sentence_id=sentence_id,
                sentence_type=sentence_type,
                content_type=ContentType.TEXT,
                content_detail=content,
            ))
        return sentence_id

    def tts_text_priority_thread(self):
        while not self.conn.stop_event.is_set():
            try:
                message = self.tts_text_queue.get(timeout=1)
                if self.conn.client_abort:
                    if self.chat is not None:
                        self.chat.interrupt()
                    continue
                if message.sentence_id != self.conn.sentence_id:
                    if message.sentence_type == SentenceType.LAST:
                        with self._preview_lock:
                            self._preview_profiles.pop(message.sentence_id, None)
                    continue
                if message.sentence_type == SentenceType.FIRST:
                    self.current_sentence_id = message.sentence_id
                    self.tts_stop_request = False
                    self.processed_chars = 0
                    self.tts_text_buff = []
                    self.before_stop_play_files.clear()
                elif ContentType.TEXT == message.content_type:
                    self.tts_text_buff.append(message.content_detail)
                    segment_text = self._get_segment_text()
                    if segment_text:
                        self.to_tts_single_stream(segment_text)
                elif ContentType.FILE == message.content_type:
                    if message.content_file and os.path.exists(message.content_file):
                        self._process_audio_file_stream(
                            message.content_file,
                            callback=lambda audio_data: self.handle_audio_file(
                                audio_data, message.content_detail
                            ),
                        )
                if message.sentence_type == SentenceType.LAST:
                    try:
                        self._process_remaining_text_stream(True)
                    finally:
                        with self._preview_lock:
                            self._preview_profiles.pop(message.sentence_id, None)
                        self._warm_pending_chat_fillers()
            except queue.Empty:
                continue
            except Exception as exc:
                logger.bind(tag=TAG).error(
                    f"RoleTTS text thread error: {exc}\n{traceback.format_exc()}"
                )

    def _process_remaining_text_stream(self, is_last=False):
        full_text = "".join(self.tts_text_buff)
        remaining_text = full_text[self.processed_chars :]
        if remaining_text:
            segment_text = textUtils.get_string_no_punctuation_or_emoji(remaining_text)
            if segment_text:
                self.to_tts_single_stream(segment_text, is_last)
                self.processed_chars = len(full_text)
                return
        self._process_before_stop_play_files()

    def to_tts_single_stream(self, text, is_last=False):
        text = MarkdownCleaner.clean_markdown(text).translate(_TEXT_TRANSLATION)
        profile = self._profile_for_sentence()
        self._mark_answer_segment_started()
        try:
            self.text_to_speak(text, is_last, profile=profile)
        except Exception as exc:
            logger.bind(tag=TAG).error(
                f"RoleTTS synth failed provider={profile.get('provider')!r} "
                f"text={text!r}: {exc}\n{traceback.format_exc()}"
            )
            self.tts_audio_queue.put(
                (SentenceType.LAST, [], None, getattr(self, "current_sentence_id", None))
            )
        return None

    def text_to_speak(self, text, is_last, *, profile=None):
        profile = profile or self._profile_for_sentence()
        config = profile.get("config") or {}
        if profile.get("provider") == "edge":
            return self._speak_edge(text, is_last, config)
        return self._speak_chattts(text, is_last, config)

    def _encode_available_pcm(self, end_of_stream=False):
        while len(self.pcm_buffer) >= _PCM_FRAME_BYTES:
            frame = bytes(self.pcm_buffer[:_PCM_FRAME_BYTES])
            del self.pcm_buffer[:_PCM_FRAME_BYTES]
            self.opus_encoder.encode_pcm_to_opus_stream(
                frame, end_of_stream=False, callback=self.handle_opus
            )
        if end_of_stream and self.pcm_buffer:
            self.opus_encoder.encode_pcm_to_opus_stream(
                bytes(self.pcm_buffer), end_of_stream=True, callback=self.handle_opus
            )
            self.pcm_buffer.clear()

    def handle_opus(self, opus_data):
        if opus_data and not getattr(self.conn, "_dotty_answer_first_opus", False):
            self.conn._dotty_answer_first_opus = True
            self._log_latency("answer_first_opus")
        super().handle_opus(opus_data)

    def _begin_audio(self, text):
        self.pcm_buffer.clear()
        self.tts_audio_queue.put(
            (SentenceType.FIRST, [], text, getattr(self, "current_sentence_id", None))
        )

    def _finish_audio(self, produced_audio, is_last):
        if produced_audio and not (self.tts_stop_request or self.conn.client_abort):
            self._encode_available_pcm(end_of_stream=True)
        else:
            self.pcm_buffer.clear()
        if is_last:
            self._process_before_stop_play_files()

    def _chattts_params(self, config):
        self._ensure_chattts_loaded()
        params_refine = self._ChatTTS.Chat.RefineTextParams(
            prompt=str(config.get("refine_prompt", "[oral_2][laugh_0][break_4]")),
            show_tqdm=False,
        )
        params_infer = self._ChatTTS.Chat.InferCodeParams(
            prompt=str(config.get("code_prompt", "[speed_5]")),
            spk_emb=self._speaker_for_seed(config.get("seed", 42)),
            temperature=float(config.get("temperature", 0.3)),
            top_P=float(config.get("top_p", 0.7)),
            top_K=int(config.get("top_k", 20)),
            stream_batch=24,
            stream_speed=12000,
            pass_first_n_batches=2,
            show_tqdm=False,
        )
        return params_refine, params_infer

    def _speak_chattts(self, text, is_last, config):
        params_refine, params_infer = self._chattts_params(config)
        self._begin_audio(text)
        produced_audio = False
        with self._chat_infer_lock:
            stream = self.chat.infer(
                [text], stream=True, split_text=False,
                params_refine_text=params_refine,
                params_infer_code=params_infer,
            )
            try:
                for waveform in stream:
                    if self.tts_stop_request or self.conn.client_abort:
                        self.chat.interrupt()
                        break
                    pcm = _pcm16_bytes(waveform, config.get("gain_db", 3.0))
                    if pcm:
                        produced_audio = True
                        self.pcm_buffer.extend(pcm)
                        self._encode_available_pcm()
            finally:
                close = getattr(stream, "close", None)
                if close:
                    close()
        self._finish_audio(produced_audio, is_last)

    async def _edge_pcm(self, text, config):
        communicate = edge_tts.Communicate(
            text,
            voice=str(config.get("voice", "zh-CN-XiaoxiaoNeural")),
            rate=str(config.get("rate", "+0%")),
            volume=str(config.get("volume", "+0%")),
            pitch=str(config.get("pitch", "+0Hz")),
        )
        mp3_buffer = bytearray()
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                mp3_buffer.extend(chunk["data"])
        if not mp3_buffer:
            return b""
        segment = AudioSegment.from_file(io.BytesIO(bytes(mp3_buffer)), format="mp3")
        return segment.set_channels(1).set_frame_rate(24000).set_sample_width(2).raw_data

    def _turn_aborted(self):
        return self.tts_stop_request or self.conn.client_abort

    async def _stream_edge_audio(self, text, config):
        communicate = edge_tts.Communicate(
            text,
            voice=str(config.get("voice", "zh-CN-XiaoxiaoNeural")),
            rate=str(config.get("rate", "+0%")),
            volume=str(config.get("volume", "+0%")),
            pitch=str(config.get("pitch", "+0Hz")),
        )
        process = await asyncio.create_subprocess_exec(
            self.ffmpeg_path,
            "-nostdin",
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "mp3",
            "-i",
            "pipe:0",
            "-f",
            "s16le",
            "-ac",
            "1",
            "-ar",
            "24000",
            "pipe:1",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        assert process.stdin is not None
        assert process.stdout is not None
        assert process.stderr is not None
        produced_audio = False

        async def feed_mp3():
            try:
                async for chunk in communicate.stream():
                    if self._turn_aborted():
                        return
                    if chunk["type"] == "audio" and chunk.get("data"):
                        process.stdin.write(chunk["data"])
                        await process.stdin.drain()
            finally:
                if not process.stdin.is_closing():
                    process.stdin.close()
                    try:
                        await process.stdin.wait_closed()
                    except (BrokenPipeError, ConnectionResetError):
                        pass

        async def drain_pcm():
            nonlocal produced_audio
            while True:
                pcm = await process.stdout.read(_PCM_FRAME_BYTES * 4)
                if not pcm:
                    return
                if self._turn_aborted():
                    continue
                produced_audio = True
                self.pcm_buffer.extend(pcm)
                self._encode_available_pcm()

        async def watch_abort():
            while process.returncode is None:
                if self._turn_aborted():
                    process.terminate()
                    return True
                await asyncio.sleep(0.05)
            return False

        feed_task = asyncio.create_task(feed_mp3())
        drain_task = asyncio.create_task(drain_pcm())
        stderr_task = asyncio.create_task(process.stderr.read())
        abort_task = asyncio.create_task(watch_abort())
        try:
            done, _ = await asyncio.wait(
                (feed_task, abort_task), return_when=asyncio.FIRST_COMPLETED
            )
            if abort_task in done and abort_task.result():
                feed_task.cancel()
                await asyncio.gather(feed_task, return_exceptions=True)
            else:
                await feed_task

            return_code = await process.wait()
            await drain_task
            stderr = (await stderr_task).decode("utf-8", errors="replace").strip()
            if return_code != 0 and not self._turn_aborted():
                raise RuntimeError(
                    f"ffmpeg edge stream exited {return_code}: {stderr or 'no detail'}"
                )
            return produced_audio
        finally:
            abort_task.cancel()
            if process.returncode is None:
                process.terminate()
                await process.wait()
            for task in (drain_task, stderr_task):
                if not task.done():
                    task.cancel()
            await asyncio.gather(abort_task, drain_task, stderr_task, return_exceptions=True)

    def _speak_edge(self, text, is_last, config):
        self._begin_audio(text)
        use_streaming = _config_bool(config.get("streaming"), self.edge_streaming)
        if use_streaming:
            produced_audio = asyncio.run(self._stream_edge_audio(text, config))
        else:
            pcm = asyncio.run(self._edge_pcm(text, config))
            produced_audio = bool(pcm)
            if pcm:
                self.pcm_buffer.extend(pcm)
                self._encode_available_pcm()
        self._finish_audio(produced_audio, is_last)

    async def close(self):
        with self._filler_lock:
            if self._pending_filler is not None:
                self._pending_filler["timer"].cancel()
                self._pending_filler = None
        if self.chat is not None:
            self.chat.interrupt()
        await super().close()
        if hasattr(self, "opus_encoder"):
            self.opus_encoder.close()
