"""Unduh semua model + llama.cpp yang tidak disimpan di git (total ~5 GB).

    .venv\\Scripts\\python.exe packaging\\download_models.py [--xtts]

--xtts juga mengunduh XTTS-v2 (~1,8 GB). Dengan opsi ini Anda menyetujui lisensi
Coqui Public Model License (non-komersial): https://coqui.ai/cpml
"""

import io
import os
import shutil
import sys
import urllib.request
import zipfile

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
MODELS = os.path.join(ROOT, "models")
LLAMA_DIR = os.path.join(ROOT, "vendor", "llama")

GGUF_REPO = "mradermacher/translategemma-4b-it-GGUF"
GGUF_FILE = "translategemma-4b-it.Q4_K_M.gguf"
WHISPER_REPO = "Systran/faster-whisper-small"
LLAMA_RELEASE = "b11344"
LLAMA_ZIPS = [
    "llama-{0}-bin-win-cuda-12.4-x64.zip".format(LLAMA_RELEASE),
    "cudart-llama-bin-win-cuda-12.4-x64.zip",
]
# Visual C++ runtime untuk llama-server.exe. Ikut dibundel (app-local) agar PC tujuan
# tidak perlu menginstal "VC++ Redistributable".
VC_RUNTIME = ["msvcp140.dll", "vcruntime140.dll", "vcruntime140_1.dll"]


def translategemma():
    from huggingface_hub import hf_hub_download

    dest = os.path.join(MODELS, "translategemma")
    if os.path.exists(os.path.join(dest, GGUF_FILE)):
        return print("[ok] TranslateGemma sudah ada")
    print("[..] TranslateGemma 4B Q4_K_M (~2,4 GB)")
    hf_hub_download(GGUF_REPO, GGUF_FILE, local_dir=dest)


def whisper():
    from huggingface_hub import snapshot_download

    dest = os.path.join(MODELS, "whisper", "faster-whisper-small")
    if os.path.exists(os.path.join(dest, "model.bin")):
        return print("[ok] Whisper small sudah ada")
    print("[..] Whisper small (~480 MB)")
    # local_dir = file biasa (bukan symlink cache HF) agar aman dibundel installer.
    snapshot_download(WHISPER_REPO, local_dir=dest)


def llama_cpp():
    if os.path.exists(os.path.join(LLAMA_DIR, "llama-server.exe")):
        print("[ok] llama.cpp sudah ada")
    else:
        os.makedirs(LLAMA_DIR, exist_ok=True)
        for name in LLAMA_ZIPS:
            url = "https://github.com/ggml-org/llama.cpp/releases/download/{}/{}".format(LLAMA_RELEASE, name)
            print("[..]", url)
            with urllib.request.urlopen(url) as r:
                zipfile.ZipFile(io.BytesIO(r.read())).extractall(LLAMA_DIR)
    vc_runtime()


def vc_runtime():
    system32 = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32")
    for name in VC_RUNTIME:
        dest = os.path.join(LLAMA_DIR, name)
        if not os.path.exists(dest):
            src = os.path.join(system32, name)
            if not os.path.exists(src):
                sys.exit("{} tidak ada di System32. Instal 'VC++ Redistributable x64' lalu ulangi.".format(name))
            shutil.copy2(src, dest)
            print("[..] salin", name, "-> vendor/llama")


def xtts():
    os.environ["COQUI_TOS_AGREED"] = "1"
    os.environ["TTS_HOME"] = MODELS
    from TTS.utils.manage import ModelManager

    print("[..] XTTS-v2 (~1,8 GB)")
    ModelManager(progress_bar=True).download_model("tts_models/multilingual/multi-dataset/xtts_v2")


def main():
    translategemma()
    whisper()
    llama_cpp()
    if "--xtts" in sys.argv:
        xtts()
    else:
        print("[--] XTTS-v2 dilewati (tambahkan --xtts, atau biarkan aplikasi mengunduhnya saat fitur Bicara dipakai)")
    print("Selesai.")


if __name__ == "__main__":
    main()
