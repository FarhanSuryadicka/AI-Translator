import json
import os
import sys
from dataclasses import asdict, dataclass, field, fields

FROZEN = getattr(sys, "frozen", False)

# APP_DIR: file bawaan aplikasi (model, llama.cpp) - read-only saat terinstal di Program Files.
# DATA_DIR: pengaturan, transkrip, sampel suara - selalu bisa ditulis.
if FROZEN:
    APP_DIR = os.path.dirname(sys.executable)
    DATA_DIR = os.path.join(os.environ.get("APPDATA", APP_DIR), "AI Translator")
else:
    APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    DATA_DIR = APP_DIR
os.makedirs(DATA_DIR, exist_ok=True)

MODELS_DIR = os.path.join(APP_DIR, "models")
VENDOR_DIR = os.path.join(APP_DIR, "vendor")
CONFIG_PATH = os.path.join(DATA_DIR, "config.json")
TRANSCRIPT_DIR = os.path.join(DATA_DIR, "transcripts")
ICON_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "icon.ico")
LLAMA_SERVER = os.path.join(VENDOR_DIR, "llama", "llama-server.exe")
BUILTIN_MT_MODEL = os.path.join(MODELS_DIR, "translategemma", "translategemma-4b-it.Q4_K_M.gguf")


@dataclass
class Config:
    # Mesin terjemahan: "builtin" = llama.cpp di dalam aplikasi, "ollama" = server Ollama (lokal/VPS)
    translator_backend: str = "builtin"
    ollama_url: str = "http://localhost:11434"
    ollama_model: str = "translategemma:4b"

    # Speech-to-Text
    whisper_model: str = "small"
    whisper_device: str = "cuda"
    whisper_compute_type: str = "int8_float16"
    source_language: str = "auto"
    target_language: str = "id"

    # Arah "Dengar": suara dari speaker -> subtitle. Nama perangkat kosong = output default Windows
    listen_enabled: bool = True
    loopback_device: str = ""
    # Nama .exe (mis. "Zoom.exe"): hanya suara dari aplikasi itu yang ditangkap. Kosong = semua suara.
    loopback_app: str = ""

    # Arah "Bicara": mic Anda -> terjemahan -> suara tiruan Anda -> virtual mic (VB-Audio Cable)
    speak_enabled: bool = False
    mic_device: str = ""
    mic_language: str = "id"
    speak_target_language: str = "en"
    # Kosong = otomatis: speaker VB-CABLE ("AI Translator Speaker" setelah dirapikan, atau "CABLE Input").
    virtual_mic_device: str = ""
    voice_sample: str = os.path.join(DATA_DIR, "voices", "my_voice.wav")
    tts_device: str = "cuda"
    xtts_license_agreed: bool = False

    # Overlay
    show_original: bool = True
    font_size: int = 22
    overlay_opacity: float = 0.75
    hide_from_capture: bool = True
    overlay_geometry: list = field(default_factory=list)

    save_transcript: bool = True

    @classmethod
    def load(cls):
        if not os.path.exists(CONFIG_PATH):
            return cls()
        try:
            with open(CONFIG_PATH, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            return cls()
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in known})

    def save(self):
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(asdict(self), f, indent=2, ensure_ascii=False)
