import asyncio
import io
import os
import queue
import threading
import traceback
import uuid

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


def _pcm16_bytes(waveform):
    samples = np.asarray(waveform, dtype=np.float32)
    if samples.ndim > 1:
        samples = samples[0]
    samples = np.nan_to_num(samples.reshape(-1), nan=0.0, posinf=1.0, neginf=-1.0)
    return (np.clip(samples, -1.0, 1.0) * 32767.0).astype(np.int16).tobytes()


class TTSProvider(TTSProviderBase):
    """Role-aware ChatTTS/EdgeTTS provider with per-utterance selection."""

    def __init__(self, config, delete_audio_file):
        super().__init__(config, delete_audio_file)
        import ChatTTS
        import torch

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
        if not os.path.isdir(self.model_path):
            raise ValueError(f"role_tts: model_path missing: {self.model_path!r}")

        requested_device = str(config.get("device", "auto")).strip().lower()
        if requested_device == "auto":
            requested_device = "cuda" if torch.cuda.is_available() else "cpu"
        if requested_device.startswith("cuda") and not torch.cuda.is_available():
            raise ValueError("role_tts: CUDA requested but torch.cuda is unavailable")
        self.device = torch.device(requested_device)
        self._torch = torch
        self._ChatTTS = ChatTTS

        self.chat = ChatTTS.Chat()
        loaded = self.chat.load(
            source="custom",
            custom_path=self.model_path,
            device=self.device,
            compile=False,
        )
        if not loaded:
            raise RuntimeError("role_tts: ChatTTS model validation or loading failed")

        self.opus_encoder = opus_encoder_utils.OpusEncoderUtils(
            sample_rate=24000, channels=1, frame_size_ms=60
        )
        self.pcm_buffer = bytearray()
        self._speakers = {}
        self._preview_profiles = {}
        self._preview_lock = threading.Lock()
        logger.bind(tag=TAG).info(
            f"role_tts loaded model={self.model_path!r} device={self.device}"
        )

    def _speaker_for_seed(self, seed):
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
        frame_bytes = 24000 * 60 // 1000 * 2
        while len(self.pcm_buffer) >= frame_bytes:
            frame = bytes(self.pcm_buffer[:frame_bytes])
            del self.pcm_buffer[:frame_bytes]
            self.opus_encoder.encode_pcm_to_opus_stream(
                frame, end_of_stream=False, callback=self.handle_opus
            )
        if end_of_stream and self.pcm_buffer:
            self.opus_encoder.encode_pcm_to_opus_stream(
                bytes(self.pcm_buffer), end_of_stream=True, callback=self.handle_opus
            )
            self.pcm_buffer.clear()

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

    def _speak_chattts(self, text, is_last, config):
        self._begin_audio(text)
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
        stream = self.chat.infer(
            [text], stream=True, split_text=False,
            params_refine_text=params_refine,
            params_infer_code=params_infer,
        )
        produced_audio = False
        try:
            for waveform in stream:
                if self.tts_stop_request or self.conn.client_abort:
                    self.chat.interrupt()
                    break
                pcm = _pcm16_bytes(waveform)
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

    def _speak_edge(self, text, is_last, config):
        self._begin_audio(text)
        pcm = asyncio.run(self._edge_pcm(text, config))
        produced_audio = bool(pcm)
        if pcm:
            self.pcm_buffer.extend(pcm)
            self._encode_available_pcm()
        self._finish_audio(produced_audio, is_last)

    async def close(self):
        self.chat.interrupt()
        await super().close()
        if hasattr(self, "opus_encoder"):
            self.opus_encoder.close()
