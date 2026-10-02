"""Atur VB-CABLE otomatis supaya pengguna tidak perlu memilih-milih perangkat.

- "CABLE Output" (mic)      -> diganti nama "AI Translator Mic"  (dipilih di Zoom/Meet)
- "CABLE Input"  (speaker)  -> diganti nama "AI Translator Speaker" (aplikasi memutar suara terjemahan ke sini)
- "CABLE In 16ch" (speaker) -> dinonaktifkan (tidak dipakai, hanya membuat daftar perangkat ramai)

Deskripsi driver "VB-Audio Virtual Cable" tetap terlihat, sesuai syarat donationware VB-Audio.
Ganti nama & nonaktifkan butuh hak admin: dijalankan installer (`AI Translator.exe --setup-audio`)
atau dari aplikasi lewat UAC.

Murni ctypes (Core Audio: IMMDeviceEnumerator / IPropertyStore).
"""

import ctypes
import subprocess
import sys
from ctypes import wintypes

from .process_loopback import GUID, _com, _release

MIC_NAME = "AI Translator Mic"
SPEAKER_NAME = "AI Translator Speaker"
CABLE_DESC = "VB-Audio Virtual Cable"
ORIG_INPUT, ORIG_16CH, ORIG_OUTPUT = "CABLE Input", "CABLE In 16ch", "CABLE Output"

_ole32 = ctypes.WinDLL("ole32")
CLSCTX_ALL = 23
eRender, eCapture = 0, 1
DEVICE_STATE_ACTIVE, DEVICE_STATE_DISABLED = 0x1, 0x2
STGM_READ, STGM_READWRITE = 0, 2
VT_LPWSTR = 31

CLSID_MMDeviceEnumerator = GUID.parse("BCDE0395-E52F-467C-8E3D-C4579291692E")
IID_IMMDeviceEnumerator = GUID.parse("A95664D2-9614-4F35-A746-DE8DB63617E6")


class PROPERTYKEY(ctypes.Structure):
    _fields_ = [("fmtid", GUID), ("pid", wintypes.DWORD)]


class PROPVARIANT(ctypes.Structure):
    _fields_ = [("vt", wintypes.WORD), ("r1", wintypes.WORD), ("r2", wintypes.WORD), ("r3", wintypes.WORD),
                ("ptr", ctypes.c_void_p), ("pad", ctypes.c_void_p)]


_DEV = GUID.parse("A45C254E-DF1C-4EFD-8020-67D146A850E0")
PKEY_Device_DeviceDesc = PROPERTYKEY(_DEV, 2)  # nama endpoint: "CABLE Output"
PKEY_Device_FriendlyName = PROPERTYKEY(_DEV, 14)  # "CABLE Output (VB-Audio Virtual Cable)"
PKEY_DeviceInterface_FriendlyName = PROPERTYKEY(GUID.parse("026E516E-B814-414B-83CD-856D6FEF4822"), 2)  # "VB-Audio Virtual Cable"


def _get_string(store, key):
    pv = PROPVARIANT()
    _com(store, 5, [ctypes.POINTER(PROPERTYKEY), ctypes.POINTER(PROPVARIANT)], ctypes.byref(key), ctypes.byref(pv))
    try:
        return ctypes.wstring_at(pv.ptr) if pv.vt == VT_LPWSTR and pv.ptr else ""
    finally:
        _ole32.PropVariantClear(ctypes.byref(pv))


def _set_string(store, key, value):
    buf = ctypes.create_unicode_buffer(value)
    pv = PROPVARIANT(vt=VT_LPWSTR, ptr=ctypes.addressof(buf))
    _com(store, 6, [ctypes.POINTER(PROPERTYKEY), ctypes.POINTER(PROPVARIANT)], ctypes.byref(key), ctypes.byref(pv))
    _com(store, 7, [])  # Commit


class Endpoint:
    def __init__(self, flow, dev_id, name, desc, state):
        self.flow, self.id, self.name, self.desc, self.state = flow, dev_id, name, desc, state

    @property
    def full_name(self):
        return "{} ({})".format(self.name, self.desc)

    def __repr__(self):
        return "<{} {!r} state={}>".format("mic" if self.flow == eCapture else "speaker", self.full_name, self.state)


def _enumerator():
    _ole32.CoInitializeEx(None, 0)
    enum = ctypes.c_void_p()
    hr = _ole32.CoCreateInstance(ctypes.byref(CLSID_MMDeviceEnumerator), None, CLSCTX_ALL,
                                 ctypes.byref(IID_IMMDeviceEnumerator), ctypes.byref(enum))
    if hr < 0:
        raise OSError(hr, "CoCreateInstance(MMDeviceEnumerator) gagal")
    return enum.value


def _devices(enum, flow):
    """(IMMDevice*, Endpoint) untuk semua endpoint aktif/nonaktif pada arah `flow`."""
    coll = ctypes.c_void_p()
    _com(enum, 3, [ctypes.c_int, wintypes.DWORD, ctypes.POINTER(ctypes.c_void_p)],
         flow, DEVICE_STATE_ACTIVE | DEVICE_STATE_DISABLED, ctypes.byref(coll))
    try:
        count = wintypes.UINT()
        _com(coll.value, 3, [ctypes.POINTER(wintypes.UINT)], ctypes.byref(count))
        for i in range(count.value):
            dev = ctypes.c_void_p()
            _com(coll.value, 4, [wintypes.UINT, ctypes.POINTER(ctypes.c_void_p)], i, ctypes.byref(dev))
            dev_id = ctypes.c_wchar_p()
            _com(dev.value, 5, [ctypes.POINTER(ctypes.c_wchar_p)], ctypes.byref(dev_id))
            state = wintypes.DWORD()
            _com(dev.value, 6, [ctypes.POINTER(wintypes.DWORD)], ctypes.byref(state))
            store = ctypes.c_void_p()
            _com(dev.value, 4, [wintypes.DWORD, ctypes.POINTER(ctypes.c_void_p)], STGM_READ, ctypes.byref(store))
            try:
                ep = Endpoint(flow, dev_id.value, _get_string(store.value, PKEY_Device_DeviceDesc),
                              _get_string(store.value, PKEY_DeviceInterface_FriendlyName), state.value)
            finally:
                _release(store.value)
                _ole32.CoTaskMemFree(dev_id)
            yield dev.value, ep
    finally:
        _release(coll.value)


def cable_endpoints():
    """Semua endpoint VB-CABLE (mic & speaker), termasuk yang dinonaktifkan."""
    enum = _enumerator()
    out = []
    try:
        for flow in (eRender, eCapture):
            for dev, ep in _devices(enum, flow):
                _release(dev)
                if ep.desc == CABLE_DESC:
                    out.append(ep)
    finally:
        _release(enum)
    return out


def is_installed():
    return any(ep.flow == eCapture for ep in cable_endpoints())


def is_configured():
    eps = cable_endpoints()
    names = {ep.name for ep in eps if ep.state == DEVICE_STATE_ACTIVE}
    return MIC_NAME in names and SPEAKER_NAME in names and ORIG_16CH not in names


def speaker_name():
    """Nama perangkat output (format pyaudio/WASAPI) tempat suara terjemahan diputar, atau ''."""
    for ep in cable_endpoints():
        if ep.flow == eRender and ep.state == DEVICE_STATE_ACTIVE and ep.name in (SPEAKER_NAME, ORIG_INPUT):
            return ep.full_name
    return ""


def mic_name():
    for ep in cable_endpoints():
        if ep.flow == eCapture and ep.state == DEVICE_STATE_ACTIVE:
            return ep.full_name
    return ""


def _disable_endpoint(dev_id):
    # Endpoint audio juga perangkat PnP (kelas AudioEndpoint); InstanceId = SWD\MMDEVAPI\<id>.
    cmd = "Disable-PnpDevice -InstanceId 'SWD\\MMDEVAPI\\{}' -Confirm:$false -ErrorAction Stop".format(dev_id)
    subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", cmd], check=True,
                   capture_output=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))


def configure(log=print):
    """Ganti nama mic/speaker VB-CABLE & nonaktifkan 'CABLE In 16ch'. Butuh admin. Return True jika berhasil."""
    enum = _enumerator()
    done = True
    try:
        for flow in (eRender, eCapture):
            for dev, ep in _devices(enum, flow):
                try:
                    if ep.desc != CABLE_DESC:
                        continue
                    if ep.name == ORIG_16CH:
                        if ep.state == DEVICE_STATE_ACTIVE:
                            _disable_endpoint(ep.id)
                            log("Dinonaktifkan: " + ep.full_name)
                        continue
                    new = MIC_NAME if flow == eCapture else SPEAKER_NAME if ep.name == ORIG_INPUT else None
                    if new and ep.name != new:
                        store = ctypes.c_void_p()
                        _com(dev, 4, [wintypes.DWORD, ctypes.POINTER(ctypes.c_void_p)], STGM_READWRITE, ctypes.byref(store))
                        try:
                            _set_string(store.value, PKEY_Device_DeviceDesc, new)
                        finally:
                            _release(store.value)
                        log("Diganti nama: {} -> {}".format(ep.name, new))
                except (OSError, subprocess.CalledProcessError) as e:
                    log("Gagal mengatur {}: {}".format(ep.full_name, e))
                    done = False
                finally:
                    _release(dev)
    finally:
        _release(enum)
    return done


def is_admin():
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except OSError:
        return False


def configure_elevated():
    """Jalankan `--setup-audio` dengan UAC (dipanggil dari UI). Return True jika proses berhasil dimulai."""
    if getattr(sys, "frozen", False):
        exe, params = sys.executable, "--setup-audio"
    else:
        import os

        main = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "main.py")
        exe, params = sys.executable, '"{}" --setup-audio'.format(main)
    SEE_MASK_NOCLOSEPROCESS = 0x40

    class SHELLEXECUTEINFOW(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.DWORD), ("fMask", ctypes.c_ulong), ("hwnd", wintypes.HWND),
                    ("lpVerb", wintypes.LPCWSTR), ("lpFile", wintypes.LPCWSTR), ("lpParameters", wintypes.LPCWSTR),
                    ("lpDirectory", wintypes.LPCWSTR), ("nShow", ctypes.c_int), ("hInstApp", wintypes.HINSTANCE),
                    ("lpIDList", ctypes.c_void_p), ("lpClass", wintypes.LPCWSTR), ("hkeyClass", wintypes.HKEY),
                    ("dwHotKey", wintypes.DWORD), ("hIcon", wintypes.HANDLE), ("hProcess", wintypes.HANDLE)]

    info = SHELLEXECUTEINFOW(cbSize=ctypes.sizeof(SHELLEXECUTEINFOW), fMask=SEE_MASK_NOCLOSEPROCESS,
                             lpVerb="runas", lpFile=exe, lpParameters=params, nShow=0)
    if not ctypes.windll.shell32.ShellExecuteExW(ctypes.byref(info)):
        return False  # pengguna menolak UAC
    ctypes.windll.kernel32.WaitForSingleObject(info.hProcess, 30000)
    ctypes.windll.kernel32.CloseHandle(info.hProcess)
    return True
