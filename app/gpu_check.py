"""Deteksi GPU NVIDIA + driver, supaya pengguna tahu kenapa aplikasi lambat (mode CPU) dan apa yang harus dilakukan.

Status:
- "ok"      : GPU NVIDIA + driver cukup baru untuk CUDA 12.4
- "old"     : GPU NVIDIA ada, tapi driver lebih lama dari MIN_DRIVER
- "missing" : GPU NVIDIA ada, tapi driver belum terinstal (Windows memakai "Microsoft Basic Display Adapter")
- "none"    : tidak ada GPU NVIDIA -> semua model jalan di CPU
"""

import json
import os
import shutil
import subprocess
from dataclasses import dataclass

# Versi driver minimum untuk CUDA 12.4 (dipakai PyTorch cu124 dan llama.cpp cuda-12.4) di Windows.
MIN_DRIVER = (551, 61)
# Whisper + TranslateGemma + XTTS bersama-sama butuh kira-kira 6 GB VRAM.
MIN_VRAM_MB = 5800
DRIVER_URL = "https://www.nvidia.com/Download/index.aspx"
NVIDIA_VENDOR = "VEN_10DE"
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


@dataclass
class GpuInfo:
    status: str
    name: str = ""
    driver: str = ""
    vram_mb: int = 0

    @property
    def has_cuda(self):
        """False = pasti tidak ada CUDA; model langsung dimuat di CPU tanpa mencoba GPU dulu."""
        return self.status in ("ok", "old")

    def message(self):
        if self.status == "ok":
            msg = "GPU: {} ({:.0f} GB), driver {}".format(self.name, self.vram_mb / 1024, self.driver)
            if self.vram_mb and self.vram_mb < MIN_VRAM_MB:
                msg += " — VRAM di bawah 6 GB, XTTS mungkin dipindah ke CPU"
            return msg
        if self.status == "old":
            return "Driver NVIDIA {} terlalu lama (disarankan {}.{} atau lebih baru). GPU mungkin gagal dipakai, sehingga aplikasi jalan di CPU dan lambat.".format(
                self.driver, *MIN_DRIVER
            )
        if self.status == "missing":
            return "{} terdeteksi, tapi driver NVIDIA belum terinstal. Aplikasi jalan di CPU dan lambat.".format(
                self.name or "GPU NVIDIA"
            )
        return (
            "Tidak ada GPU NVIDIA: aplikasi jalan di CPU. Subtitle tertunda ±5 detik, "
            "dan fitur Bicara tidak disarankan (suara akan patah-patah)."
        )


def _driver_from_windows_version(v):
    """'32.0.15.9186' -> '591.86' (format versi driver NVIDIA dari versi driver Windows)."""
    parts = v.split(".")
    if len(parts) != 4:
        return ""
    digits = (parts[2] + parts[3])[-5:]
    return "{}.{}".format(digits[:3], digits[3:]) if len(digits) == 5 else ""


def _version_tuple(s):
    try:
        major, minor = s.split(".")[:2]
        return int(major), int(minor)
    except ValueError:
        return (0, 0)


def _nvidia_smi():
    exe = shutil.which("nvidia-smi") or os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "nvidia-smi.exe")
    if not os.path.exists(exe):
        return None
    try:
        out = subprocess.run(
            [exe, "--query-gpu=name,memory.total,driver_version", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=10, creationflags=_NO_WINDOW,
        ).stdout.strip().splitlines()
    except (OSError, subprocess.SubprocessError):
        return None
    if not out:
        return None
    name, vram, driver = [x.strip() for x in out[0].split(",")]
    return name, int(float(vram)), driver


def _video_controllers():
    cmd = "Get-CimInstance Win32_VideoController | Select-Object Name,PNPDeviceID,DriverVersion | ConvertTo-Json"
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", cmd],
            capture_output=True, text=True, timeout=20, creationflags=_NO_WINDOW,
        ).stdout
        data = json.loads(out) if out.strip() else []
    except (OSError, subprocess.SubprocessError, ValueError):
        return []
    return data if isinstance(data, list) else [data]


def detect():
    smi = _nvidia_smi()
    if smi is not None:
        name, vram, driver = smi
        status = "ok" if _version_tuple(driver) >= MIN_DRIVER else "old"
        return GpuInfo(status, name, driver, vram)

    for c in _video_controllers():
        if NVIDIA_VENDOR not in (c.get("PNPDeviceID") or "").upper():
            continue
        name = c.get("Name") or ""
        if "NVIDIA" not in name.upper():  # perangkat NVIDIA tapi masih memakai driver bawaan Windows
            return GpuInfo("missing", name="GPU NVIDIA")
        driver = _driver_from_windows_version(c.get("DriverVersion") or "")
        status = "ok" if driver and _version_tuple(driver) >= MIN_DRIVER else "old"
        return GpuInfo(status, name, driver)
    return GpuInfo("none")


_cached = None


def get():
    """Hasil deteksi (di-cache; pemanggilan pertama ±1 detik)."""
    global _cached
    if _cached is None:
        _cached = detect()
    return _cached
