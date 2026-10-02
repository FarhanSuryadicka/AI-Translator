"""Text-to-Speech yang meniru suara Anda (XTTS-v2, Coqui).

Lisensi model XTTS-v2: Coqui Public Model License (non-komersial).
"""

import os

import numpy as np

from .config import MODELS_DIR

XTTS_MODEL = "tts_models/multilingual/multi-dataset/xtts_v2"
SAMPLE_RATE = 24000

# Bahasa keluaran yang didukung XTTS-v2 (Bahasa Indonesia tidak termasuk).
XTTS_LANGUAGES = ["en", "es", "fr", "de", "it", "pt", "pl", "tr", "ru", "nl", "cs", "ar", "zh", "ja", "hu", "ko", "hi"]


def _xtts_code(code):
    return "zh-cn" if code == "zh" else code


class VoiceCloner:
    def __init__(self, voice_sample, device="cuda", log=print):
        if not os.path.exists(voice_sample):
            raise RuntimeError(
                "Sampel suara belum ada ({}). Rekam dulu di tab 'Bicara'.".format(voice_sample)
            )
        # Persetujuan lisensi CPML diminta di UI sebelum sampai ke sini.
        os.environ["COQUI_TOS_AGREED"] = "1"
        # Model XTTS disimpan di <aplikasi>/models/tts agar ikut dibundel installer.
        os.environ["TTS_HOME"] = MODELS_DIR
        import torch
        from TTS.api import TTS

        self._torch = torch
        tts = TTS(XTTS_MODEL, progress_bar=False)
        self.device = device
        if device == "cuda" and not torch.cuda.is_available():
            log("CUDA tidak tersedia untuk XTTS, memakai CPU (lebih lambat).")
            self.device = "cpu"
        try:
            tts.to(self.device)
        except RuntimeError as e:  # biasanya VRAM habis
            if self.device == "cpu":
                raise
            log("XTTS gagal di GPU ({}), pindah ke CPU.".format(e))
            torch.cuda.empty_cache()
            self.device = "cpu"
            tts.to("cpu")
        self.model = tts.synthesizer.tts_model
        with torch.inference_mode():
            self.gpt_latent, self.speaker_emb = self.model.get_conditioning_latents(audio_path=[voice_sample])
        # Panaskan sekali: panggilan pertama XTTS jauh lebih lambat (alokasi CUDA/kernel).
        for _ in self.stream("Hello, this is a warm up.", "en"):
            pass

    def stream(self, text, language="en"):
        """Hasilkan potongan audio float32 24 kHz secara bertahap (mulai diputar lebih cepat)."""
        with self._torch.inference_mode():
            for chunk in self.model.inference_stream(
                text,
                _xtts_code(language),
                self.gpt_latent,
                self.speaker_emb,
                enable_text_splitting=True,
            ):
                yield chunk.detach().cpu().numpy().astype(np.float32)
