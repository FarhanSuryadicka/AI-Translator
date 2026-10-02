# PyInstaller spec: menghasilkan folder "AI Translator" (onedir) berisi AI Translator.exe.
# Model (models/) dan llama.cpp (vendor/) TIDAK dimasukkan di sini; installer menaruhnya di samping exe.
# Jalankan lewat packaging\build.ps1

import os

from PyInstaller.utils.hooks import collect_all

ROOT = os.path.abspath(os.path.join(SPECPATH, ".."))

datas, binaries, hiddenimports = [], [], []
for pkg in (
    "TTS",
    "trainer",
    "coqpit",
    "spacy",
    "thinc",
    "num2words",
    "faster_whisper",
    "ctranslate2",
    "tokenizers",
    "pyaudiowpatch",
    # Dependensi coqui-tts yang membawa file data / metadata entry-point.
    "gruut",
    "gruut_ipa",
    "gruut_lang_en",
    "dateparser",
    "dateparser_data",
    "babel",
    "librosa",
    "encodec",
    "anyascii",
    "pysbd",
    "inflect",
    "langcodes",
    "soundfile",
    "soxr",
    "spacy_legacy",
    "spacy_loggers",
    "srsly",
    "confection",
    "weasel",
    "catalogue",
    "pycrfsuite",
    "monotonic_alignment_search",
    "jsonlines",
    "tzdata",
):
    d, b, h = collect_all(pkg)
    datas += d
    binaries += b
    hiddenimports += h

datas += [(os.path.join(ROOT, "app", "assets"), os.path.join("app", "assets"))]
ICON = os.path.join(ROOT, "app", "assets", "icon.ico")

hiddenimports += [
    "transformers.models.gpt2",
    "transformers.generation",
]

a = Analysis(
    [os.path.join(ROOT, "main.py")],
    pathex=[ROOT],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=["tkinter", "IPython", "jupyter", "notebook", "pytest"],
    # Library ini membaca source .py-nya sendiri (inspect.getsource: typeguard, TorchScript, dll).
    module_collection_mode={
        "inflect": "py",
        "typeguard": "py",
        "TTS": "pyz+py",
        "torch": "pyz+py",
        "transformers": "pyz+py",
    },
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="AI Translator",
    console=False,
    icon=ICON,
)
coll = COLLECT(exe, a.binaries, a.datas, name="AI Translator")
