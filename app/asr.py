"""Speech-to-Text dengan faster-whisper (otomatis mendeteksi bahasa sumber)."""

import importlib.util
import os
import sys

import numpy as np

from .config import MODELS_DIR

WHISPER_DIR = os.path.join(MODELS_DIR, "whisper")

# Kalimat "hantu" yang sering dihasilkan Whisper dari suara hening/musik.
HALLUCINATIONS = {
    "thank you.",
    "thanks for watching!",
    "thank you for watching.",
    "thank you for watching!",
    "please subscribe.",
    "you",
    "terima kasih.",
    "terima kasih telah menonton.",
    "ご視聴ありがとうございました",
    "字幕由amara.org社区提供",
}


def _add_cuda_dll_paths():
    """Daftarkan DLL cuBLAS/cuDNN (bawaan PyTorch) agar Whisper/CTranslate2 bisa memakai GPU."""
    dirs = []
    if hasattr(sys, "_MEIPASS"):  # aplikasi hasil PyInstaller
        dirs.append(os.path.join(sys._MEIPASS, "torch", "lib"))
    spec = importlib.util.find_spec("torch")
    if spec is not None and spec.submodule_search_locations:
        dirs.append(os.path.join(list(spec.submodule_search_locations)[0], "lib"))
    for d in dirs:
        if os.path.isdir(d):
            os.environ["PATH"] = d + os.pathsep + os.environ.get("PATH", "")
            os.add_dll_directory(d)
    # CTranslate2 membawa cudnn64_9.dll versi lain. Muat PyTorch lebih dulu agar satu proses
    # memakai satu set cuDNN yang sama (kalau tidak, XTTS crash: "cudnnGetLibConfig").
    try:
        import torch  # noqa: F401
    except ImportError:
        pass


class Transcriber:
    def __init__(self, model_size, device="cuda", compute_type="int8_float16", log=print):
        _add_cuda_dll_paths()
        from faster_whisper import WhisperModel

        # Model bawaan installer: models/whisper/faster-whisper-<ukuran>/ (file biasa, tanpa cache HF).
        local = os.path.join(WHISPER_DIR, "faster-whisper-" + model_size)
        if os.path.isfile(os.path.join(local, "model.bin")):
            model_size = local

        self.device = device
        try:
            self.model = WhisperModel(model_size, device=device, compute_type=compute_type, download_root=WHISPER_DIR)
            self._warmup()
        except Exception as e:  # CUDA/cuDNN tidak tersedia -> pakai CPU
            if device == "cpu":
                raise
            log("GPU gagal dipakai untuk Whisper ({}), pindah ke CPU.".format(e))
            self.device = "cpu"
            self.model = WhisperModel(model_size, device="cpu", compute_type="int8", download_root=WHISPER_DIR)
            self._warmup()

    def _warmup(self):
        # Error CUDA/cuDNN baru muncul saat inferensi pertama, jadi dipaksa di sini.
        segments, _ = self.model.transcribe(np.zeros(16000, dtype=np.float32), language="en")
        list(segments)

    def transcribe(self, audio, language=None):
        """Kembalikan (teks, kode_bahasa)."""
        segments, info = self.model.transcribe(
            audio,
            language=language,
            beam_size=1,
            vad_filter=True,
            condition_on_previous_text=False,
            without_timestamps=True,
        )
        parts = []
        for s in segments:
            if s.no_speech_prob > 0.6 and s.avg_logprob < -1.0:
                continue
            text = s.text.strip()
            if text and text.lower() not in HALLUCINATIONS:
                parts.append(text)
        return " ".join(parts).strip(), info.language
