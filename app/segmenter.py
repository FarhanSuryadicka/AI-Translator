"""Memotong aliran audio menjadi potongan per kalimat berdasarkan jeda hening.

Pendekatan berbasis energi (RMS): cukup untuk audio digital dari loopback,
lalu Whisper (vad_filter=True) membuang sisa bagian yang bukan suara.
"""

import collections

import numpy as np


class SpeechSegmenter:
    def __init__(
        self,
        sr=16000,
        frame_ms=30,
        threshold_db=-48.0,
        silence_ms=650,
        min_speech_ms=400,
        max_segment_ms=9000,
        preroll_ms=300,
        adaptive=False,
    ):
        self.sr = sr
        self.frame_len = int(sr * frame_ms / 1000)
        self.threshold_db = threshold_db
        # Mikrofon punya noise latar; mode adaptif menaikkan ambang mengikuti noise tersebut.
        self.adaptive = adaptive
        self._noise_db = -70.0
        self.silence_frames = silence_ms // frame_ms
        self.min_frames = min_speech_ms // frame_ms
        self.max_frames = max_segment_ms // frame_ms
        self._preroll = collections.deque(maxlen=preroll_ms // frame_ms)
        self._leftover = np.zeros(0, dtype=np.float32)
        self._frames = []
        self._speech_frames = 0
        self._silent_run = 0

    @property
    def in_speech(self):
        return bool(self._frames)

    def push(self, samples):
        """Masukkan audio baru, kembalikan daftar potongan kalimat yang sudah selesai."""
        buf = np.concatenate([self._leftover, samples])
        n_full = len(buf) // self.frame_len
        self._leftover = buf[n_full * self.frame_len:]
        done = []
        for i in range(n_full):
            frame = buf[i * self.frame_len:(i + 1) * self.frame_len]
            seg = self._push_frame(frame)
            if seg is not None:
                done.append(seg)
        return done

    def _push_frame(self, frame):
        rms = float(np.sqrt(np.mean(frame * frame)) + 1e-10)
        db = 20 * np.log10(rms)
        threshold = self.threshold_db
        if self.adaptive:
            threshold = max(threshold, self._noise_db + 15.0)
        is_speech = db > threshold
        if self.adaptive and not is_speech and not self._frames:
            self._noise_db = 0.98 * self._noise_db + 0.02 * db

        if not self._frames:
            if is_speech:
                self._frames = list(self._preroll) + [frame]
                self._preroll.clear()
                self._speech_frames = 1
                self._silent_run = 0
            else:
                self._preroll.append(frame)
            return None

        self._frames.append(frame)
        if is_speech:
            self._speech_frames += 1
            self._silent_run = 0
        else:
            self._silent_run += 1

        if self._silent_run >= self.silence_frames or len(self._frames) >= self.max_frames:
            return self.flush()
        return None

    def flush(self):
        """Paksa keluarkan potongan yang sedang berjalan (mis. saat audio berhenti)."""
        frames, speech = self._frames, self._speech_frames
        self._frames = []
        self._speech_frames = 0
        self._silent_run = 0
        if speech < self.min_frames:
            return None
        return np.concatenate(frames)
