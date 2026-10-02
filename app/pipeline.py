"""Dua arah terjemahan yang berbagi satu Whisper + satu TranslateGemma:

- Dengar : speaker (loopback) -> Whisper -> TranslateGemma -> subtitle
- Bicara : mic -> Whisper -> TranslateGemma -> XTTS (suara Anda) -> virtual mic (VB-Audio Cable)
"""

import datetime
import os
import queue
import threading
import time
from dataclasses import dataclass

import numpy as np

from . import gpu_check
from .audio_capture import TARGET_SR, AudioPlayer, InputCapture, list_output_devices
from .config import BUILTIN_MT_MODEL, LLAMA_SERVER, TRANSCRIPT_DIR
from .segmenter import SpeechSegmenter

LISTEN = "listen"
SPEAK = "speak"

# Kalau loopback tidak mengirim audio selama ini, kalimat yang sedang berjalan dianggap selesai.
STALE_FLUSH_SEC = 0.8
# Laporan level audio ke UI (level meter) paling sering sekali per interval ini.
LEVEL_INTERVAL_SEC = 0.1
MONITOR_GAIN = 0.35


@dataclass
class Result:
    direction: str
    original: str
    translation: str
    language: str
    asr_ms: int
    mt_ms: int


class _Direction:
    """Satu arah: capture -> potong kalimat -> ASR -> terjemah -> sink."""

    def __init__(self, session, name, capture_factory, segmenter, source_lang, target_lang, sink=None):
        self.session = session
        self.name = name
        self.segmenter = segmenter
        self.source_lang = None if source_lang == "auto" else source_lang
        self.target_lang = target_lang
        self.sink = sink
        self.queue = queue.Queue()
        self.capture = capture_factory(self.queue.put)
        self.thread = threading.Thread(target=self._run, daemon=True)

    def start(self):
        self.capture.start()
        self.thread.start()

    def stop(self):
        self.capture.stop()

    def _run(self):
        try:
            self._loop()
        except Exception as e:
            self.session.fail("{}: {}".format(self.name, e))

    def _loop(self):
        stop = self.session.stop_event
        last_audio = time.monotonic()
        last_level, peak = 0.0, 0.0
        while not stop.is_set():
            try:
                chunk = self.queue.get(timeout=0.2)
            except queue.Empty:
                if self.segmenter.in_speech and time.monotonic() - last_audio > STALE_FLUSH_SEC:
                    seg = self.segmenter.flush()
                    if seg is not None:
                        self._process(seg)
                self.session.level(self.name, -90.0)
                continue
            last_audio = time.monotonic()
            if len(chunk):
                peak = max(peak, float(np.sqrt(np.mean(chunk * chunk))))
            if last_audio - last_level >= LEVEL_INTERVAL_SEC:
                self.session.level(self.name, 20 * np.log10(peak + 1e-9))
                last_level, peak = last_audio, 0.0
            for seg in self.segmenter.push(chunk):
                self._process(seg)

    def _process(self, audio):
        s = self.session
        t0 = time.perf_counter()
        with s.asr_lock:
            text, detected = s.asr.transcribe(audio, language=self.source_lang)
        t1 = time.perf_counter()
        if not text:
            return

        if detected == self.target_lang:
            translation = text
        else:
            try:
                translation = s.translator.translate(text, detected, self.target_lang)
            except Exception as e:
                s.status("Gagal menerjemahkan: {}".format(e))
                return
        t2 = time.perf_counter()

        s.emit(Result(self.name, text, translation, detected, int((t1 - t0) * 1000), int((t2 - t1) * 1000)))
        if self.sink is not None and translation:
            self.sink(translation)


class _VoiceOutput:
    """Antrian kalimat -> XTTS (streaming) -> virtual mic. Jalan di thread sendiri agar mic tetap didengar."""

    def __init__(self, session, tts, player, language, monitor=None):
        self.session = session
        self.tts = tts
        self.player = player
        self.language = language
        # Pemantauan ke headset diputar di thread terpisah agar tidak menunda virtual mic.
        self.monitor = monitor
        self._monitor_queue = queue.Queue()
        self.queue = queue.Queue()
        self.thread = threading.Thread(target=self._run, daemon=True)

    def start(self):
        self.thread.start()
        if self.monitor is not None:
            threading.Thread(target=self._run_monitor, daemon=True).start()

    def _run_monitor(self):
        from .tts import SAMPLE_RATE

        stop = self.session.stop_event
        while not stop.is_set():
            try:
                chunk = self._monitor_queue.get(timeout=0.2)
            except queue.Empty:
                continue
            try:
                self.monitor.play(chunk * MONITOR_GAIN, SAMPLE_RATE)
            except Exception:
                pass

    def say(self, text):
        self.queue.put(text)

    def _run(self):
        from .tts import SAMPLE_RATE

        stop = self.session.stop_event
        while not stop.is_set():
            try:
                text = self.queue.get(timeout=0.2)
            except queue.Empty:
                continue
            try:
                for chunk in self.tts.stream(text, self.language):
                    if stop.is_set():
                        break
                    if self.monitor is not None:
                        self._monitor_queue.put(chunk)
                    self.player.play(chunk, SAMPLE_RATE)
            except Exception as e:
                self.session.status("Gagal membuat suara: {}".format(e))

    def close(self):
        self.player.close()
        if self.monitor is not None:
            self.monitor.close()


def _virtual_mic(cfg):
    """Perangkat output untuk suara terjemahan: pilihan pengguna, atau speaker VB-CABLE yang terdeteksi."""
    from . import audio_setup

    names = list_output_devices()
    if cfg.virtual_mic_device in names:
        return cfg.virtual_mic_device
    auto = audio_setup.speaker_name()
    if auto in names:
        return auto
    raise RuntimeError("Virtual mic (VB-CABLE) tidak ditemukan. Instal ulang AI Translator dengan opsi VB-CABLE, lalu restart PC.")


def _listen_capture(on_audio, cfg):
    if cfg.loopback_app:
        from .process_loopback import ProcessLoopbackCapture

        return ProcessLoopbackCapture(on_audio, cfg.loopback_app)
    return InputCapture(on_audio, cfg.loopback_device, loopback=True)


class Session:
    def __init__(self, cfg, on_result, on_status, on_level=None):
        self.cfg = cfg
        self._on_result = on_result
        self._on_status = on_status
        self._on_level = on_level
        self.stop_event = threading.Event()
        self.asr_lock = threading.Lock()
        self._thread = None
        self._error = None
        self._transcript = None
        self.translator = None
        self._transcript_lock = threading.Lock()

    # ---------- API untuk UI ----------
    def start(self):
        self.stop_event.clear()
        self._error = None
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        self.stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None

    @property
    def running(self):
        return self._thread is not None and self._thread.is_alive()

    # ---------- dipanggil dari thread pekerja ----------
    def status(self, msg):
        self._on_status(msg)

    def level(self, direction, db):
        if self._on_level is not None:
            self._on_level(direction, db)

    def fail(self, msg):
        self._error = msg
        self.stop_event.set()

    def emit(self, result):
        self._on_result(result)
        if self._transcript is not None:
            stamp = datetime.datetime.now().strftime("%H:%M:%S")
            tag = "DENGAR" if result.direction == LISTEN else "BICARA"
            with self._transcript_lock:
                self._transcript.write(
                    "[{}] {} ({}) {}\n           -> {}\n".format(
                        stamp, tag, result.language, result.original, result.translation
                    )
                )
                self._transcript.flush()

    # ---------- internal ----------
    def _run(self):
        self._directions = []
        self._voice = None
        try:
            self._setup()
            self.stop_event.wait()
        except Exception as e:
            self._error = str(e)
        finally:
            for d in self._directions:
                d.stop()
            if self._voice is not None:
                self._voice.thread.join(timeout=3)
                self._voice.close()
            if self._transcript is not None:
                self._transcript.close()
                self._transcript = None
            if self.translator is not None:
                self.translator.close()
                self.translator = None
            if self._error:
                self._on_status("ERROR: {}".format(self._error))
            self._on_status("STOPPED")

    def _setup(self):
        from .asr import Transcriber
        from .translator import LlamaServerTranslator, OllamaTranslator

        cfg = self.cfg
        gpu = gpu_check.get()
        if not gpu.has_cuda:
            self.status(gpu.message())
        if not cfg.listen_enabled and not cfg.speak_enabled:
            raise RuntimeError("Aktifkan minimal satu: 'Dengar' atau 'Bicara'.")
        if cfg.speak_enabled:
            # Validasi mic & virtual mic lebih dulu agar error muncul sebelum memuat model yang lama.
            probe = InputCapture(lambda _: None, cfg.mic_device, loopback=False)
            probe.start()
            probe.stop()
            AudioPlayer(_virtual_mic(cfg)).close()

        if cfg.translator_backend == "ollama":
            self.status("Memeriksa Ollama ({})...".format(cfg.ollama_url))
            self.translator = OllamaTranslator(cfg.ollama_url, cfg.ollama_model)
        else:
            self.status("Memuat TranslateGemma (llama.cpp bawaan)...")
            self.translator = LlamaServerTranslator(LLAMA_SERVER, BUILTIN_MT_MODEL, gpu_layers=99 if gpu.has_cuda else 0)
        self.translator.check()

        self.status("Memuat Whisper '{}' (pertama kali akan mengunduh model)...".format(cfg.whisper_model))
        if gpu.has_cuda:
            self.asr = Transcriber(cfg.whisper_model, cfg.whisper_device, cfg.whisper_compute_type, log=self.status)
        else:
            self.asr = Transcriber(cfg.whisper_model, "cpu", "int8", log=self.status)

        self.status("Memanaskan TranslateGemma...")
        self.translator.translate("Hello", "en", "id")

        voice = None
        if cfg.speak_enabled:
            from .tts import VoiceCloner

            self.status("Memuat XTTS-v2 (pertama kali mengunduh ~1,8 GB)...")
            tts = VoiceCloner(cfg.voice_sample, cfg.tts_device if gpu.has_cuda else "cpu", log=self.status)
            player = AudioPlayer(_virtual_mic(cfg))
            monitor = AudioPlayer("") if cfg.speak_monitor else None
            voice = self._voice = _VoiceOutput(self, tts, player, cfg.speak_target_language, monitor)
            voice.start()

        if cfg.save_transcript:
            os.makedirs(TRANSCRIPT_DIR, exist_ok=True)
            name = datetime.datetime.now().strftime("%Y-%m-%d_%H%M%S") + ".txt"
            self._transcript = open(os.path.join(TRANSCRIPT_DIR, name), "a", encoding="utf-8")

        directions = self._directions
        if cfg.listen_enabled:
            directions.append(
                _Direction(
                    self,
                    LISTEN,
                    lambda cb: _listen_capture(cb, cfg),
                    SpeechSegmenter(sr=TARGET_SR, silence_ms=cfg.listen_pause_ms),
                    cfg.source_language,
                    cfg.target_language,
                )
            )
        if voice is not None:
            directions.append(
                _Direction(
                    self,
                    SPEAK,
                    lambda cb: InputCapture(cb, cfg.mic_device, loopback=False),
                    SpeechSegmenter(sr=TARGET_SR, threshold_db=-50.0, max_segment_ms=12000, adaptive=True),
                    cfg.mic_language,
                    cfg.speak_target_language,
                    sink=voice.say,
                )
            )
        for d in directions:
            d.start()
        self._on_status("RUNNING")

        parts = []
        for d in directions:
            label = "Dengar" if d.name == LISTEN else "Bicara"
            parts.append("{}: {}".format(label, d.capture.device_label))
        if voice is not None:
            parts.append("Virtual mic: {} | XTTS di {}".format(voice.player.device_label, voice.tts.device.upper()))
        parts.append("Whisper di {}".format(self.asr.device.upper()))
        self.status(" | ".join(parts))
