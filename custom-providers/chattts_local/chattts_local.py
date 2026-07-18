import os
import queue
import traceback

import numpy as np

from config.logger import setup_logging
from core.providers.tts.base import TTSProviderBase
from core.providers.tts.dto.dto import ContentType, InterfaceType, SentenceType
from core.utils import opus_encoder_utils, textUtils
from core.utils.tts import MarkdownCleaner

TAG = __name__
logger = setup_logging()

_CHAT_TTS_TEXT_TRANSLATION = str.maketrans(
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


class TTSProvider(TTSProviderBase):
    """Local bilingual ChatTTS with incremental 24 kHz Opus output."""

    def __init__(self, config, delete_audio_file):
        super().__init__(config, delete_audio_file)
        import ChatTTS
        import torch

        self.interface_type = InterfaceType.SINGLE_STREAM
        self.audio_format = "pcm"
        self.before_stop_play_files = []
        self.model_path = config.get(
            "model_path", "/opt/xiaozhi-esp32-server/models/chattts"
        )
        if not os.path.isdir(self.model_path):
            raise ValueError(
                f"chattts_local: model_path missing or not a directory: {self.model_path!r}"
            )

        requested_device = str(config.get("device", "auto")).strip().lower()
        if requested_device == "auto":
            requested_device = "cuda" if torch.cuda.is_available() else "cpu"
        if requested_device.startswith("cuda") and not torch.cuda.is_available():
            raise ValueError("chattts_local: CUDA requested but torch.cuda is unavailable")
        self.device = torch.device(requested_device)

        self.seed = int(config.get("seed", 42))
        self.temperature = float(config.get("temperature", 0.3))
        self.top_p = float(config.get("top_p", 0.7))
        self.top_k = int(config.get("top_k", 20))
        self.refine_prompt = str(
            config.get("refine_prompt", "[oral_2][laugh_0][break_4]")
        )
        self.code_prompt = str(config.get("code_prompt", "[speed_5]"))
        self.gain_db = float(config.get("gain_db", 3.0))
        if not -12.0 <= self.gain_db <= 12.0:
            raise ValueError("chattts_local: gain_db must be between -12 and 12")
        self.stream_batch = int(config.get("stream_batch", 24))
        self.stream_speed = int(config.get("stream_speed", 12000))
        self.pass_first_n_batches = int(config.get("pass_first_n_batches", 2))

        torch.manual_seed(self.seed)
        if self.device.type == "cuda":
            torch.cuda.manual_seed_all(self.seed)

        self.chat = ChatTTS.Chat()
        loaded = self.chat.load(
            source="custom",
            custom_path=self.model_path,
            device=self.device,
            compile=False,
        )
        if not loaded:
            raise RuntimeError(
                "chattts_local: model validation or loading failed; run `make fetch-models`"
            )

        self.speaker = self.chat.sample_random_speaker()
        self.params_refine_text = ChatTTS.Chat.RefineTextParams(
            prompt=self.refine_prompt,
            show_tqdm=False,
        )
        self.params_infer_code = ChatTTS.Chat.InferCodeParams(
            prompt=self.code_prompt,
            spk_emb=self.speaker,
            temperature=self.temperature,
            top_P=self.top_p,
            top_K=self.top_k,
            stream_batch=self.stream_batch,
            stream_speed=self.stream_speed,
            pass_first_n_batches=self.pass_first_n_batches,
            show_tqdm=False,
        )

        self.opus_encoder = opus_encoder_utils.OpusEncoderUtils(
            sample_rate=24000, channels=1, frame_size_ms=60
        )
        self.pcm_buffer = bytearray()
        logger.bind(tag=TAG).info(
            f"chattts_local loaded model={self.model_path!r} device={self.device} "
            f"seed={self.seed} streaming=true"
        )

    def tts_text_priority_thread(self):
        while not self.conn.stop_event.is_set():
            try:
                message = self.tts_text_queue.get(timeout=1)
                if self.conn.client_abort:
                    self.chat.interrupt()
                    continue
                if message.sentence_id != self.conn.sentence_id:
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
                    self._process_remaining_text_stream(True)
            except queue.Empty:
                continue
            except Exception as exc:
                logger.bind(tag=TAG).error(
                    f"ChatTTS text thread error: {exc}\n{traceback.format_exc()}"
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
        text = MarkdownCleaner.clean_markdown(text).translate(
            _CHAT_TTS_TEXT_TRANSLATION
        )
        try:
            self.text_to_speak(text, is_last)
        except Exception as exc:
            logger.bind(tag=TAG).error(
                f"ChatTTS synth failed for {text!r}: {exc}\n{traceback.format_exc()}"
            )
            self.tts_audio_queue.put(
                (SentenceType.LAST, [], None, getattr(self, "current_sentence_id", None))
            )
        return None

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

    def text_to_speak(self, text, is_last):
        self.pcm_buffer.clear()
        self.tts_audio_queue.put(
            (SentenceType.FIRST, [], text, getattr(self, "current_sentence_id", None))
        )
        stream = self.chat.infer(
            [text],
            stream=True,
            split_text=False,
            params_refine_text=self.params_refine_text,
            params_infer_code=self.params_infer_code,
        )
        produced_audio = False
        try:
            for waveform in stream:
                if self.tts_stop_request or self.conn.client_abort:
                    self.chat.interrupt()
                    break
                pcm = _pcm16_bytes(waveform, self.gain_db)
                if pcm:
                    produced_audio = True
                    self.pcm_buffer.extend(pcm)
                    self._encode_available_pcm()
        finally:
            close = getattr(stream, "close", None)
            if close:
                close()

        if produced_audio and not (self.tts_stop_request or self.conn.client_abort):
            self._encode_available_pcm(end_of_stream=True)
        else:
            self.pcm_buffer.clear()
        if not produced_audio:
            logger.bind(tag=TAG).warning(f"ChatTTS returned no audio for {text!r}")
        if is_last:
            self._process_before_stop_play_files()

    async def close(self):
        self.chat.interrupt()
        await super().close()
        self.opus_encoder.close()
