"""Terjemahan teks dengan TranslateGemma.

- LlamaServerTranslator: llama.cpp bawaan aplikasi (tanpa instalasi tambahan).
- OllamaTranslator: server Ollama (lokal atau VPS).
"""

import os
import socket
import subprocess
import time

import requests

from .languages import language_name

# Format prompt resmi TranslateGemma.
PROMPT = (
    "You are a professional {src} ({sc}) to {tgt} ({tc}) translator. "
    "Your goal is to accurately convey the meaning and nuances of the original {src} text "
    "while adhering to {tgt} grammar, vocabulary, and cultural sensitivities.\n"
    "Produce only the {tgt} translation, without any additional explanations or commentary. "
    "Please translate the following {src} text into {tgt}:\n\n\n{text}"
)


def build_prompt(text, src_code, tgt_code):
    return PROMPT.format(
        src=language_name(src_code),
        sc=src_code,
        tgt=language_name(tgt_code),
        tc=tgt_code,
        text=text,
    )


class OllamaTranslator:
    def __init__(self, base_url, model, timeout=60):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout

    def check(self):
        """Pastikan server Ollama hidup dan model sudah di-pull. Raise RuntimeError jika tidak."""
        try:
            r = requests.get(self.base_url + "/api/tags", timeout=5)
            r.raise_for_status()
        except requests.RequestException as e:
            raise RuntimeError(
                "Tidak bisa terhubung ke Ollama di {} ({}). Pastikan Ollama sudah terinstal dan berjalan.".format(
                    self.base_url, e
                )
            )
        names = {m.get("name", "") for m in r.json().get("models", [])}
        wanted = self.model if ":" in self.model else self.model + ":latest"
        if wanted not in names:
            raise RuntimeError(
                "Model '{}' belum ada di Ollama. Jalankan: ollama pull {}".format(self.model, self.model)
            )

    def translate(self, text, src_code, tgt_code):
        prompt = build_prompt(text, src_code, tgt_code)
        r = requests.post(
            self.base_url + "/api/generate",
            json={
                "model": self.model,
                "prompt": prompt,
                "stream": False,
                "keep_alive": "30m",
                "options": {"temperature": 0, "num_ctx": 2048},
            },
            timeout=self.timeout,
        )
        r.raise_for_status()
        return r.json().get("response", "").strip()

    def close(self):
        pass


def _kill_with_parent(proc):
    """Masukkan proses ke Windows Job Object agar ikut mati saat aplikasi ditutup/crash."""
    if os.name != "nt":
        return
    import ctypes
    from ctypes import wintypes

    class IO_COUNTERS(ctypes.Structure):
        _fields_ = [(n, ctypes.c_ulonglong) for n in (
            "ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
            "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]

    class BASIC_LIMIT(ctypes.Structure):
        _fields_ = [
            ("PerProcessUserTimeLimit", ctypes.c_int64),
            ("PerJobUserTimeLimit", ctypes.c_int64),
            ("LimitFlags", wintypes.DWORD),
            ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t),
            ("ActiveProcessLimit", wintypes.DWORD),
            ("Affinity", ctypes.c_size_t),
            ("PriorityClass", wintypes.DWORD),
            ("SchedulingClass", wintypes.DWORD),
        ]

    class EXTENDED_LIMIT(ctypes.Structure):
        _fields_ = [
            ("BasicLimitInformation", BASIC_LIMIT),
            ("IoInfo", IO_COUNTERS),
            ("ProcessMemoryLimit", ctypes.c_size_t),
            ("JobMemoryLimit", ctypes.c_size_t),
            ("PeakProcessMemoryUsed", ctypes.c_size_t),
            ("PeakJobMemoryUsed", ctypes.c_size_t),
        ]

    JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x2000
    JobObjectExtendedLimitInformation = 9
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateJobObjectW.restype = wintypes.HANDLE
    kernel32.OpenProcess.restype = wintypes.HANDLE
    job = kernel32.CreateJobObjectW(None, None)
    info = EXTENDED_LIMIT()
    info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    kernel32.SetInformationJobObject(
        wintypes.HANDLE(job), JobObjectExtendedLimitInformation, ctypes.byref(info), ctypes.sizeof(info)
    )
    handle = kernel32.OpenProcess(0x1F0FFF, False, proc.pid)  # PROCESS_ALL_ACCESS
    kernel32.AssignProcessToJobObject(wintypes.HANDLE(job), wintypes.HANDLE(handle))
    kernel32.CloseHandle(wintypes.HANDLE(handle))
    # Handle job sengaja tidak ditutup: saat proses aplikasi berakhir, Windows menutupnya
    # dan llama-server ikut dimatikan.
    return job


def _free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class LlamaServerTranslator:
    """Menjalankan llama-server.exe (llama.cpp) sebagai proses latar belakang."""

    def __init__(self, server_exe, model_path, gpu_layers=99, ctx=1536, parallel=2, timeout=60):
        self.server_exe = server_exe
        self.model_path = model_path
        self.gpu_layers = gpu_layers
        # 2 slot: terjemahan sementara (subtitle langsung) tidak perlu menunggu terjemahan kalimat final.
        # Konteks dibagi rata per slot (768 token; prompt + 1 kalimat + hasil < 500 token).
        self.ctx = ctx
        self.parallel = parallel
        self.timeout = timeout
        self._proc = None
        self.base_url = ""

    def check(self):
        """Jalankan server dan tunggu sampai model selesai dimuat."""
        for path, what in ((self.server_exe, "llama-server.exe"), (self.model_path, "model TranslateGemma")):
            if not os.path.exists(path):
                raise RuntimeError("File {} tidak ditemukan: {}".format(what, path))
        port = _free_port()
        self.base_url = "http://127.0.0.1:{}".format(port)
        self._proc = subprocess.Popen(
            [
                self.server_exe,
                "-m", self.model_path,
                "--host", "127.0.0.1",
                "--port", str(port),
                "-ngl", str(self.gpu_layers),
                "-c", str(self.ctx),
                "--parallel", str(self.parallel),
                # Hemat VRAM agar muat bersama Whisper + XTTS di GPU 6 GB.
                "-b", "256",
                "-ub", "256",
                "-fa", "on",
                # Template bawaan TranslateGemma butuh format pesan khusus; prompt dibentuk sendiri di translate().
                "--no-jinja",
                "--chat-template", "gemma",
            ],
            cwd=os.path.dirname(self.server_exe),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        self._job = _kill_with_parent(self._proc)
        deadline = time.monotonic() + 180
        while time.monotonic() < deadline:
            if self._proc.poll() is not None:
                raise RuntimeError("llama-server berhenti saat memuat model (kode {}).".format(self._proc.returncode))
            try:
                if requests.get(self.base_url + "/health", timeout=2).status_code == 200:
                    return
            except requests.RequestException:
                pass
            time.sleep(0.5)
        self.close()
        raise RuntimeError("llama-server tidak siap dalam 180 detik.")

    def translate(self, text, src_code, tgt_code):
        # Format chat Gemma; BOS ditambahkan otomatis oleh llama-server.
        prompt = "<start_of_turn>user\n{}<end_of_turn>\n<start_of_turn>model\n".format(
            build_prompt(text, src_code, tgt_code)
        )
        r = requests.post(
            self.base_url + "/completion",
            json={
                "prompt": prompt,
                "temperature": 0,
                "n_predict": 320,
                "stop": ["<end_of_turn>"],
                "cache_prompt": True,
            },
            timeout=self.timeout,
        )
        r.raise_for_status()
        return r.json().get("content", "").strip()

    def close(self):
        if self._proc is not None and self._proc.poll() is None:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._proc.kill()
        self._proc = None
