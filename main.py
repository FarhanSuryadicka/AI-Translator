import os
import sys
import traceback

from app.config import DATA_DIR, FROZEN

LOG_PATH = os.path.join(DATA_DIR, "app.log")


def _setup_logging():
    # Aplikasi .exe tanpa konsol: sys.stdout/stderr = None, padahal progress bar (tqdm) menulis ke sana.
    if FROZEN or sys.stderr is None:
        log = open(LOG_PATH, "a", encoding="utf-8", buffering=1)
        sys.stdout = sys.stderr = log

    def hook(exc_type, exc, tb):
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            traceback.print_exception(exc_type, exc, tb, file=f)
        sys.__excepthook__(exc_type, exc, tb)

    sys.excepthook = hook


def selftest():
    """Muat semua model dan uji terjemahan + suara tanpa UI. Hasil ditulis ke app.log."""
    import time

    import numpy as np

    from app.asr import Transcriber
    from app.config import BUILTIN_MT_MODEL, LLAMA_SERVER
    from app.translator import LlamaServerTranslator

    t = time.time()
    asr = Transcriber("small", log=print)
    print("[selftest] Whisper OK di", asr.device, "%.1fs" % (time.time() - t))
    asr.transcribe(np.zeros(16000, dtype=np.float32))

    mt = LlamaServerTranslator(LLAMA_SERVER, BUILTIN_MT_MODEL)
    mt.check()
    try:
        print("[selftest] Terjemahan:", mt.translate("Good morning everyone.", "en", "id"))
        sample = os.path.join(DATA_DIR, "voices", "my_voice.wav")
        if len(sys.argv) > 2:
            sample = sys.argv[2]
        if os.path.exists(sample):
            from app.tts import VoiceCloner

            tts = VoiceCloner(sample, "cuda", log=print)
            n = sum(len(c) for c in tts.stream("Hello everyone.", "en"))
            print("[selftest] XTTS OK di", tts.device, "-", n, "sampel audio")
        else:
            import TTS.tts.layers.xtts.tokenizer  # noqa: F401  (pastikan spacy & data XTTS ikut terbundel)

            print("[selftest] XTTS modul OK (tanpa sampel suara)")
    finally:
        mt.close()
    print("[selftest] SELESAI")


def main():
    _setup_logging()
    if "--setup-audio" in sys.argv:
        # Dipanggil installer (sudah admin) atau dari UI lewat UAC.
        from app import audio_setup

        ok = audio_setup.is_installed() and audio_setup.configure(log=lambda m: print("[setup-audio]", m))
        print("[setup-audio]", "SELESAI" if ok else "GAGAL / VB-CABLE belum siap (mungkin perlu restart)")
        sys.stdout.flush()
        os._exit(0 if ok else 1)
    if "--selftest" in sys.argv:
        selftest()
        # Thread latar dari torch/TTS kadang menahan proses .exe agar tidak keluar.
        sys.stdout.flush()
        os._exit(0)

    import ctypes

    from PySide6.QtGui import QIcon
    from PySide6.QtWidgets import QApplication

    from app.config import ICON_PATH, Config

    # Supaya taskbar memakai ikon aplikasi ini, bukan ikon python.exe (saat dijalankan dari source).
    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("AITranslator.App")
    from app.ui.main_window import MainWindow

    app = QApplication(sys.argv)
    app.setApplicationName("AI Translator")
    app.setWindowIcon(QIcon(ICON_PATH))
    window = MainWindow(Config.load())
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
