"""Input/output audio via WASAPI.

- Loopback: suara yang keluar ke speaker/headset (Zoom, Teams, Chrome/Meet, YouTube, dll).
- Mic: mikrofon Anda sendiri.
- AudioPlayer: memutar suara hasil TTS ke perangkat output (mis. VB-Audio "CABLE Input"),
  yang kemudian dipakai Zoom/Meet sebagai mikrofon lewat "CABLE Output".
"""

import time
import wave

import numpy as np
import pyaudiowpatch as pyaudio

TARGET_SR = 16000


def _wasapi_devices(pa):
    wasapi = pa.get_host_api_info_by_type(pyaudio.paWASAPI)["index"]
    for i in range(pa.get_device_count()):
        dev = pa.get_device_info_by_index(i)
        if dev["hostApi"] == wasapi:
            yield dev


def _list(predicate):
    pa = pyaudio.PyAudio()
    try:
        return [d["name"] for d in _wasapi_devices(pa) if predicate(d)]
    finally:
        pa.terminate()


def list_loopback_devices():
    return _list(lambda d: d.get("isLoopbackDevice"))


def list_input_devices():
    return _list(lambda d: d["maxInputChannels"] > 0 and not d.get("isLoopbackDevice"))


def list_output_devices():
    return _list(lambda d: d["maxOutputChannels"] > 0)


def resample(x, sr, target=TARGET_SR):
    if sr == target or len(x) == 0:
        return x
    n = int(round(len(x) * target / sr))
    pos = np.linspace(0, len(x) - 1, n)
    return np.interp(pos, np.arange(len(x)), x).astype(np.float32)


def _find(pa, name, predicate, default):
    if name:
        for dev in _wasapi_devices(pa):
            if dev["name"] == name and predicate(dev):
                return dev
        raise RuntimeError("Perangkat audio tidak ditemukan: {}".format(name))
    return default()


class InputCapture:
    """Memanggil on_audio(np.ndarray float32 mono 16 kHz) untuk setiap blok audio.

    Catatan: WASAPI loopback tidak mengirim data sama sekali saat tidak ada
    suara yang diputar, jadi penerima harus menangani jeda tanpa callback.
    """

    def __init__(self, on_audio, device_name="", loopback=True):
        self._on_audio = on_audio
        self._device_name = device_name
        self._loopback = loopback
        self._pa = None
        self._stream = None
        self.device_label = ""

    def _find_device(self):
        if self._loopback:
            return _find(
                self._pa, self._device_name, lambda d: d.get("isLoopbackDevice"), self._pa.get_default_wasapi_loopback
            )
        return _find(
            self._pa,
            self._device_name,
            lambda d: d["maxInputChannels"] > 0 and not d.get("isLoopbackDevice"),
            lambda: self._pa.get_device_info_by_index(
                self._pa.get_host_api_info_by_type(pyaudio.paWASAPI)["defaultInputDevice"]
            ),
        )

    def start(self):
        self._pa = pyaudio.PyAudio()
        dev = self._find_device()
        if not self._loopback and "VB-Audio" in dev["name"]:
            self._pa.terminate()
            self._pa = None
            raise RuntimeError(
                "Mikrofon yang terpilih adalah '{}' (virtual cable), bukan mic asli. "
                "Colokkan/aktifkan mikrofon atau headset Anda, lalu pilih di tab 'Bicara'.".format(dev["name"])
            )
        self.device_label = dev["name"]
        self._channels = int(dev["maxInputChannels"])
        self._rate = int(dev["defaultSampleRate"])
        self._stream = self._pa.open(
            format=pyaudio.paInt16,
            channels=self._channels,
            rate=self._rate,
            input=True,
            input_device_index=dev["index"],
            frames_per_buffer=int(self._rate * 0.05),
            stream_callback=self._callback,
        )
        self._stream.start_stream()

    def _callback(self, in_data, frame_count, time_info, status):
        data = np.frombuffer(in_data, dtype=np.int16).astype(np.float32) / 32768.0
        mono = data.reshape(-1, self._channels).mean(axis=1)
        self._on_audio(resample(mono, self._rate))
        return (None, pyaudio.paContinue)

    def stop(self):
        if self._stream is not None:
            try:
                self._stream.stop_stream()
                self._stream.close()
            except OSError:
                pass
            self._stream = None
        if self._pa is not None:
            self._pa.terminate()
            self._pa = None


class AudioPlayer:
    """Memutar audio mono float32 ke perangkat output tertentu (blocking)."""

    def __init__(self, device_name):
        self._pa = pyaudio.PyAudio()
        try:
            dev = _find(self._pa, device_name, lambda d: d["maxOutputChannels"] > 0, self._default_output)
        except Exception:
            self._pa.terminate()
            raise
        self.device_label = dev["name"]
        self._channels = int(dev["maxOutputChannels"])
        self._rate = int(dev["defaultSampleRate"])
        self._stream = self._pa.open(
            format=pyaudio.paInt16,
            channels=self._channels,
            rate=self._rate,
            output=True,
            output_device_index=dev["index"],
        )

    def _default_output(self):
        index = self._pa.get_host_api_info_by_type(pyaudio.paWASAPI)["defaultOutputDevice"]
        return self._pa.get_device_info_by_index(index)

    def play(self, samples, sr):
        x = resample(np.asarray(samples, dtype=np.float32), sr, self._rate)
        x = np.clip(x, -1.0, 1.0)
        pcm = (np.repeat(x[:, None], self._channels, axis=1) * 32767).astype(np.int16)
        self._stream.write(pcm.tobytes())

    def close(self):
        try:
            self._stream.stop_stream()
            self._stream.close()
        except OSError:
            pass
        self._pa.terminate()


def record_sample(device_name, seconds, path):
    """Rekam mikrofon selama `seconds` detik ke file WAV mono 16 kHz (untuk sampel suara XTTS)."""
    chunks = []
    cap = InputCapture(chunks.append, device_name, loopback=False)
    cap.start()
    try:
        time.sleep(seconds)
    finally:
        cap.stop()
    audio = np.concatenate(chunks) if chunks else np.zeros(0, dtype=np.float32)
    peak = float(np.max(np.abs(audio))) if len(audio) else 0.0
    if peak < 0.01:
        raise RuntimeError("Rekaman hampir hening. Periksa mikrofon yang dipilih.")
    audio = audio / peak * 0.9
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(TARGET_SR)
        w.writeframes((audio * 32767).astype(np.int16).tobytes())
    return len(audio) / TARGET_SR


def read_wav(path):
    """WAV mono/stereo 16-bit -> (float32 mono, sample rate)."""
    with wave.open(path, "rb") as w:
        sr, ch = w.getframerate(), w.getnchannels()
        data = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768.0
    if ch > 1:
        data = data.reshape(-1, ch).mean(axis=1)
    return data, sr


def play_wav(path):
    """Putar file WAV ke speaker default (blocking)."""
    audio, sr = read_wav(path)
    player = AudioPlayer("")
    try:
        player.play(audio, sr)
    finally:
        player.close()
