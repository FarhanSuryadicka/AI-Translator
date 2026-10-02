"""Tangkap audio dari SATU aplikasi saja (WASAPI process loopback, Windows 10 20348+ / Windows 11).

Berbeda dengan loopback biasa yang merekam semua suara di speaker, di sini hanya suara dari
proses target (beserta proses anaknya, mis. tab Chrome / WebView Teams) yang ditangkap.
Notifikasi Windows, musik, dll. tidak ikut diterjemahkan.

Murni ctypes (tanpa comtypes): ActivateAudioInterfaceAsync -> IAudioClient -> IAudioCaptureClient.
"""

import ctypes
import os
import threading
from ctypes import wintypes

import numpy as np

from .audio_capture import TARGET_SR, resample

_ole32 = ctypes.WinDLL("ole32")
_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
_user32 = ctypes.WinDLL("user32")

S_OK = 0
E_NOINTERFACE = -2147467262  # 0x80004002
COINIT_MULTITHREADED = 0
VT_BLOB = 65
AUDIOCLIENT_ACTIVATION_TYPE_PROCESS_LOOPBACK = 1
PROCESS_LOOPBACK_MODE_INCLUDE_TARGET_PROCESS_TREE = 0
AUDCLNT_SHAREMODE_SHARED = 0
AUDCLNT_STREAMFLAGS_LOOPBACK = 0x00020000
AUDCLNT_STREAMFLAGS_EVENTCALLBACK = 0x00040000
AUDCLNT_STREAMFLAGS_SRC_DEFAULT_QUALITY = 0x08000000
AUDCLNT_STREAMFLAGS_AUTOCONVERTPCM = 0x80000000
AUDCLNT_BUFFERFLAGS_SILENT = 0x2
WAVE_FORMAT_PCM = 1
WAIT_TIMEOUT_MS = 200
VIRTUAL_AUDIO_DEVICE_PROCESS_LOOPBACK = "VAD\\Process_Loopback"


class GUID(ctypes.Structure):
    _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD), ("Data3", wintypes.WORD), ("Data4", ctypes.c_ubyte * 8)]

    @classmethod
    def parse(cls, s):
        g = cls()
        _ole32.CLSIDFromString(ctypes.c_wchar_p("{" + s + "}"), ctypes.byref(g))
        return g

    def __eq__(self, other):
        return bytes(self) == bytes(other)


IID_IUnknown = GUID.parse("00000000-0000-0000-C000-000000000046")
IID_IAgileObject = GUID.parse("94EA2B94-E9CC-49E0-C0FF-EE64CA8F5B90")
IID_IActivateAudioInterfaceCompletionHandler = GUID.parse("41D949AB-9862-444A-80F6-C261334DA5EB")
IID_IAudioClient = GUID.parse("1CB9AD4C-DBFA-4C32-B178-C2F568A703B2")
IID_IAudioCaptureClient = GUID.parse("C8ADBD64-E71E-48A0-A4DE-185C395CD317")


class WAVEFORMATEX(ctypes.Structure):
    _pack_ = 1
    _fields_ = [
        ("wFormatTag", wintypes.WORD),
        ("nChannels", wintypes.WORD),
        ("nSamplesPerSec", wintypes.DWORD),
        ("nAvgBytesPerSec", wintypes.DWORD),
        ("nBlockAlign", wintypes.WORD),
        ("wBitsPerSample", wintypes.WORD),
        ("cbSize", wintypes.WORD),
    ]


class AUDIOCLIENT_ACTIVATION_PARAMS(ctypes.Structure):
    _fields_ = [("ActivationType", ctypes.c_int), ("TargetProcessId", wintypes.DWORD), ("ProcessLoopbackMode", ctypes.c_int)]


class PROPVARIANT_BLOB(ctypes.Structure):
    _fields_ = [
        ("vt", wintypes.WORD),
        ("r1", wintypes.WORD),
        ("r2", wintypes.WORD),
        ("r3", wintypes.WORD),
        ("cbSize", wintypes.ULONG),
        ("pBlobData", ctypes.c_void_p),
    ]


def _com(ptr, index, argtypes, *args, restype=ctypes.HRESULT):
    """Panggil method ke-`index` dari vtable objek COM `ptr`. HRESULT gagal -> OSError."""
    vtbl = ctypes.cast(ptr, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
    fn = ctypes.WINFUNCTYPE(restype, ctypes.c_void_p, *argtypes)(vtbl[index])
    return fn(ptr, *args)


def _release(ptr):
    if ptr:
        _com(ptr, 2, [], restype=wintypes.ULONG)


_QI_T = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, ctypes.POINTER(GUID), ctypes.POINTER(ctypes.c_void_p))
_REF_T = ctypes.WINFUNCTYPE(wintypes.ULONG, ctypes.c_void_p)
_DONE_T = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, ctypes.c_void_p)


class _CompletionHandler:
    """Objek COM minimal untuk IActivateAudioInterfaceCompletionHandler (juga IAgileObject).

    Masa hidupnya dipegang Python (self), jadi AddRef/Release cukup pura-pura.
    """

    def __init__(self):
        self.done = threading.Event()
        self.hr = S_OK
        self.audio_client = None
        self._fns = (_QI_T(self._query), _REF_T(lambda this: 1), _REF_T(lambda this: 1), _DONE_T(self._completed))
        self._vtbl = (ctypes.c_void_p * 4)(*[ctypes.cast(f, ctypes.c_void_p) for f in self._fns])
        self._obj = ctypes.c_void_p(ctypes.addressof(self._vtbl))
        self.ptr = ctypes.addressof(self._obj)

    def _query(self, this, riid, ppv):
        if riid.contents in (IID_IUnknown, IID_IAgileObject, IID_IActivateAudioInterfaceCompletionHandler):
            ppv[0] = this
            return S_OK
        ppv[0] = None
        return E_NOINTERFACE

    def _completed(self, this, operation):
        try:
            hr = ctypes.c_long()
            unk = ctypes.c_void_p()
            # IActivateAudioInterfaceAsyncOperation::GetActivateResult
            _com(operation, 3, [ctypes.POINTER(ctypes.c_long), ctypes.POINTER(ctypes.c_void_p)], ctypes.byref(hr), ctypes.byref(unk))
            self.hr = hr.value
            if hr.value >= 0 and unk:
                client = ctypes.c_void_p()
                _com(unk.value, 0, [ctypes.POINTER(GUID), ctypes.POINTER(ctypes.c_void_p)], ctypes.byref(IID_IAudioClient), ctypes.byref(client))
                self.audio_client = client.value
            _release(unk.value)
        except OSError as e:
            self.hr = e.winerror or -1
        finally:
            self.done.set()
        return S_OK


def _activate(pid):
    params = AUDIOCLIENT_ACTIVATION_PARAMS(
        AUDIOCLIENT_ACTIVATION_TYPE_PROCESS_LOOPBACK, pid, PROCESS_LOOPBACK_MODE_INCLUDE_TARGET_PROCESS_TREE
    )
    prop = PROPVARIANT_BLOB(vt=VT_BLOB, cbSize=ctypes.sizeof(params), pBlobData=ctypes.addressof(params))
    handler = _CompletionHandler()
    op = ctypes.c_void_p()
    fn = ctypes.WinDLL("Mmdevapi").ActivateAudioInterfaceAsync
    fn.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(GUID), ctypes.c_void_p, ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)]
    fn.restype = ctypes.HRESULT
    fn(VIRTUAL_AUDIO_DEVICE_PROCESS_LOOPBACK, ctypes.byref(IID_IAudioClient), ctypes.byref(prop), handler.ptr, ctypes.byref(op))
    try:
        if not handler.done.wait(5):
            raise RuntimeError("Aktivasi process loopback tidak merespons.")
    finally:
        _release(op.value)
    if handler.hr < 0 or not handler.audio_client:
        raise RuntimeError("Aktivasi process loopback gagal (HRESULT 0x{:08X}).".format(handler.hr & 0xFFFFFFFF))
    return handler.audio_client


def _wave_format(rate, channels):
    block = channels * 2
    return WAVEFORMATEX(WAVE_FORMAT_PCM, channels, rate, rate * block, block, 16, 0)


# ---------- Daftar aplikasi ----------

# Proses bawaan Windows yang punya jendela tapi bukan sumber suara.
_SYSTEM_APPS = {
    "explorer.exe",
    "applicationframehost.exe",
    "textinputhost.exe",
    "systemsettings.exe",
    "shellexperiencehost.exe",
    "searchhost.exe",
    "startmenuexperiencehost.exe",
    "lockapp.exe",
}


def _windowed_pids():
    pids = set()
    proc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def cb(hwnd, _):
        if _user32.IsWindowVisible(hwnd) and _user32.GetWindowTextLengthW(hwnd) > 0:
            pid = wintypes.DWORD()
            _user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            pids.add(pid.value)
        return True

    _user32.EnumWindows(proc(cb), 0)
    return pids


def list_audio_apps():
    """Nama .exe aplikasi yang punya jendela (kandidat sumber suara), urut abjad."""
    return [name for name, _ in list_audio_apps_with_paths()]


def list_audio_apps_with_paths():
    """[(nama .exe, path lengkap .exe)] untuk aplikasi yang punya jendela, urut abjad (path dipakai untuk ikon)."""
    import psutil

    apps = {}
    me = os.getpid()
    for pid in _windowed_pids():
        if pid in (0, me):
            continue
        try:
            proc = psutil.Process(pid)
            name = proc.name()
            if name.lower() not in _SYSTEM_APPS and name not in apps:
                try:
                    apps[name] = proc.exe()
                except (psutil.Error, OSError):
                    apps[name] = ""
        except (psutil.Error, OSError):
            pass
    return sorted(apps.items(), key=lambda kv: kv[0].lower())


def find_app_pid(exe_name):
    """PID proses induk teratas dari aplikasi `exe_name` (agar semua proses anaknya ikut tertangkap)."""
    import psutil

    target = exe_name.lower()
    roots = []
    for p in psutil.process_iter(["name", "ppid", "create_time"]):
        if (p.info["name"] or "").lower() != target:
            continue
        try:
            parent = psutil.Process(p.info["ppid"]).name().lower()
        except (psutil.Error, OSError):
            parent = ""
        if parent != target:
            roots.append((p.info["create_time"] or 0, p.pid))
    if not roots:
        raise RuntimeError("Aplikasi '{}' tidak sedang berjalan. Buka dulu aplikasinya, lalu klik Mulai.".format(exe_name))
    return min(roots)[1]


# ---------- Capture ----------

class ProcessLoopbackCapture:
    """Antarmuka sama dengan audio_capture.InputCapture: on_audio(float32 mono 16 kHz)."""

    def __init__(self, on_audio, exe_name):
        self._on_audio = on_audio
        self._exe_name = exe_name
        self._stop = threading.Event()
        self._ready = threading.Event()
        self._error = None
        self._thread = None
        self.device_label = ""

    def start(self):
        pid = find_app_pid(self._exe_name)
        self.device_label = "aplikasi {} (PID {})".format(self._exe_name, pid)
        self._stop.clear()
        self._ready.clear()
        self._error = None
        self._thread = threading.Thread(target=self._run, args=(pid,), daemon=True)
        self._thread.start()
        self._ready.wait(10)
        if self._error is not None:
            self._thread.join(2)
            raise self._error

    def stop(self):
        self._stop.set()
        if self._thread is not None:
            self._thread.join(2)
            self._thread = None

    def _run(self, pid):
        _ole32.CoInitializeEx(None, COINIT_MULTITHREADED)
        client = capture = event = None
        try:
            client = _activate(pid)
            # Coba langsung 16 kHz mono (Windows yang resample); kalau ditolak, pakai 48 kHz stereo.
            flags = (
                AUDCLNT_STREAMFLAGS_LOOPBACK
                | AUDCLNT_STREAMFLAGS_EVENTCALLBACK
                | AUDCLNT_STREAMFLAGS_AUTOCONVERTPCM
                | AUDCLNT_STREAMFLAGS_SRC_DEFAULT_QUALITY
            )
            init_args = [ctypes.c_int, wintypes.DWORD, ctypes.c_longlong, ctypes.c_longlong, ctypes.POINTER(WAVEFORMATEX), ctypes.c_void_p]
            for rate, channels in ((TARGET_SR, 1), (48000, 2)):
                fmt = _wave_format(rate, channels)
                try:
                    _com(client, 3, init_args, AUDCLNT_SHAREMODE_SHARED, flags, 2000000, 0, ctypes.byref(fmt), None)
                    break
                except OSError:
                    if channels == 2:
                        raise
            event = _kernel32.CreateEventW(None, False, False, None)
            _com(client, 13, [wintypes.HANDLE], event)  # SetEventHandle
            cap = ctypes.c_void_p()
            _com(client, 14, [ctypes.POINTER(GUID), ctypes.POINTER(ctypes.c_void_p)], ctypes.byref(IID_IAudioCaptureClient), ctypes.byref(cap))
            capture = cap.value
            _com(client, 10, [])  # Start
        except Exception as e:
            self._error = e if isinstance(e, RuntimeError) else RuntimeError("Gagal menangkap audio aplikasi: {}".format(e))
            self._ready.set()
            self._cleanup(client, capture, event)
            return
        self._ready.set()
        try:
            self._loop(capture, event, fmt)
        except Exception:
            import traceback

            traceback.print_exc()
        finally:
            try:
                _com(client, 11, [])  # Stop
            except OSError:
                pass
            self._cleanup(client, capture, event)

    @staticmethod
    def _cleanup(client, capture, event):
        _release(capture)
        _release(client)
        if event:
            _kernel32.CloseHandle(event)
        _ole32.CoUninitialize()

    def _loop(self, capture, event, fmt):
        data = ctypes.c_void_p()
        frames = ctypes.c_uint32()
        flags = wintypes.DWORD()
        packet = ctypes.c_uint32()
        get_args = [ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(ctypes.c_uint32), ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p, ctypes.c_void_p]
        channels, rate, block = fmt.nChannels, fmt.nSamplesPerSec, fmt.nBlockAlign
        while not self._stop.is_set():
            _kernel32.WaitForSingleObject(event, WAIT_TIMEOUT_MS)
            chunks = []
            while True:
                _com(capture, 5, [ctypes.POINTER(ctypes.c_uint32)], ctypes.byref(packet))  # GetNextPacketSize
                if packet.value == 0:
                    break
                _com(capture, 3, get_args, ctypes.byref(data), ctypes.byref(frames), ctypes.byref(flags), None, None)
                n = frames.value
                if flags.value & AUDCLNT_BUFFERFLAGS_SILENT or not data.value:
                    chunks.append(np.zeros(n * channels, dtype=np.int16))
                else:
                    chunks.append(np.frombuffer(ctypes.string_at(data.value, n * block), dtype=np.int16).copy())
                _com(capture, 4, [ctypes.c_uint32], n)  # ReleaseBuffer
            if not chunks:
                continue
            pcm = np.concatenate(chunks).astype(np.float32) / 32768.0
            mono = pcm.reshape(-1, channels).mean(axis=1) if channels > 1 else pcm
            self._on_audio(resample(mono, rate))
