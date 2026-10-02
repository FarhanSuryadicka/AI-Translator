"""Subtitle langsung (per kata), seperti live caption Google Meet.

Arah "Dengar" saat mode langsung aktif:
  audio -> buffer kalimat berjalan
        -> tiap STEP detik: Silero VAD (suara manusia vs musik/hening) + Whisper atas buffer
        -> teks sementara langsung ke UI (partial); terjemahannya diperbarui di thread terpisah
        -> kalimat pertama sudah sama pada 2 bacaan berturut-turut (LocalAgreement) -> kalimat itu final,
           dibuang dari buffer (buffer tetap pendek = Whisper tetap cepat walau orang bicara tanpa jeda)
        -> jeda bicara >= pause_ms, atau buffer > MAX_SEC: sisa buffer final

Teks sementara boleh berubah (Whisper merevisi kata terakhir); versi final menggantikannya.
"""

import collections
import queue
import threading
import time

import numpy as np

from .audio_capture import TARGET_SR

STEP_SEC = 0.4          # seberapa sering Whisper membaca ulang kalimat yang sedang berjalan
MIN_SEC = 0.5           # audio minimum sebelum transkripsi pertama
MAX_SEC = 12.0          # buffer tanpa jeda & tanpa kalimat stabil dipotong paksa di sini
COMMIT_GAP_SEC = 0.6    # kalimat dianggap selesai bila berakhir sejauh ini sebelum ujung buffer
MT_INTERVAL_SEC = 0.5   # jarak minimum antar terjemahan sementara
VAD_FRAME = 512         # 32 ms @ 16 kHz (ukuran jendela Silero)
SPEECH_PROB = 0.5
PREROLL_FRAMES = 10     # ~0,3 dtk sebelum suara pertama ikut ditranskripsi
LEVEL_INTERVAL_SEC = 0.1

_vad = None
_vad_lock = threading.Lock()


def _vad_model():
    global _vad
    with _vad_lock:
        if _vad is None:
            from faster_whisper.vad import get_vad_model

            _vad = get_vad_model()
        return _vad


def speech_probs(audio):
    """Probabilitas suara manusia per 32 ms (Silero VAD, CPU)."""
    n = len(audio) // VAD_FRAME * VAD_FRAME
    if n == 0:
        return np.zeros(0, dtype=np.float32)
    return np.asarray(_vad_model()(audio[:n].astype(np.float32)), dtype=np.float32).reshape(-1)


def _norm(text):
    return "".join(ch for ch in text.lower() if ch.isalnum())


class _Translator(threading.Thread):
    """Terjemahan di latar belakang.

    - final  : antrean berurutan, semua dikerjakan (masuk transkrip)
    - partial: hanya permintaan terbaru (teks sementara cepat basi)
    """

    def __init__(self, session, source_lang, target_lang, on_partial, on_final):
        super().__init__(daemon=True)
        self.session = session
        self.source_lang = source_lang
        self.target = target_lang
        self.on_partial, self.on_final = on_partial, on_final
        self._cond = threading.Condition()
        self._finals = collections.deque()
        self._partial = None

    def partial(self, seq, text, src):
        with self._cond:
            self._partial = (seq, text, src)
            self._cond.notify()

    def final(self, seq, audio, fallback_text, src):
        """Kalimat selesai: dibaca ulang dengan model utama (lebih akurat), lalu diterjemahkan."""
        with self._cond:
            self._finals.append((seq, audio, fallback_text, src))
            self._cond.notify()

    def _final_asr(self, audio, fallback_text, src):
        s = self.session
        if s.asr_fast is None or audio is None or len(audio) < 0.3 * TARGET_SR:
            return fallback_text, src, 0
        t0 = time.perf_counter()
        with s.asr_lock:
            segs, lang = s.asr.transcribe_segments(audio, language=self.source_lang)
        text = " ".join(t for _, _, t in segs)
        return (text or fallback_text), (self.source_lang or lang or src), int((time.perf_counter() - t0) * 1000)

    def _translate(self, text, src):
        if src == self.target:
            return text
        return self.session.translator.translate(text, src, self.target)

    def run(self):
        stop = self.session.stop_event
        while not stop.is_set():
            with self._cond:
                if not self._finals and self._partial is None:
                    self._cond.wait(0.2)
                if self._finals:
                    kind, data = "final", self._finals.popleft()
                else:
                    kind, data, self._partial = "partial", self._partial, None
            if data is None:
                continue
            try:
                if kind == "final":
                    seq, audio, fallback, src = data
                    text, src, asr_ms = self._final_asr(audio, fallback, src)
                    t0 = time.perf_counter()
                    tr = self._translate(text, src)
                    self.on_final(seq, text, tr, src, asr_ms, int((time.perf_counter() - t0) * 1000))
                else:
                    seq, text, src = data
                    self.on_partial(seq, text, self._translate(text, src))
            except Exception as e:
                if kind == "final":
                    self.session.status("Gagal menerjemahkan: {}".format(e))


class LiveDirection:
    """Pengganti pipeline._Direction untuk arah Dengar dengan subtitle langsung."""

    def __init__(self, session, name, capture_factory, source_lang, target_lang, pause_ms):
        self.session = session
        self.name = name
        self.source_lang = None if source_lang == "auto" else source_lang
        self.target_lang = target_lang
        self.pause_frames = max(4, int(pause_ms / 32))
        self.queue = queue.Queue()
        self.capture = capture_factory(self.queue.put)
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.mt = _Translator(session, self.source_lang, target_lang, self._partial_translated, self._final_translated)
        self._buf = np.zeros(0, dtype=np.float32)
        self._seq = 0              # nomor kalimat berjalan
        self._text = ""            # teks sementara kalimat berjalan
        self._lang = None          # bahasa terkunci (deteksi otomatis sekali per kalimat)
        self._translation = ""     # terjemahan sementara kalimat berjalan
        self._last_mt = 0.0
        self._prev_first = ""      # kalimat pertama pada bacaan sebelumnya (LocalAgreement)
        self._done = set()         # seq yang terjemahan finalnya sudah dikirim

    def start(self):
        self.capture.start()
        self.mt.start()
        self.thread.start()

    def stop(self):
        self.capture.stop()

    def _run(self):
        try:
            self._loop()
        except Exception as e:
            self.session.fail("{}: {}".format(self.name, e))

    # ------------------------------------------------------------------ loop utama
    def _drain(self, first):
        """Ambil SEMUA audio yang sudah menunggu (jangan sampai tertinggal dari waktu nyata)."""
        chunks = [first]
        while True:
            try:
                chunks.append(self.queue.get_nowait())
            except queue.Empty:
                return np.concatenate(chunks)

    def _loop(self):
        stop = self.session.stop_event
        last_level = 0.0
        last_audio = time.monotonic()
        next_step = time.monotonic() + STEP_SEC
        while not stop.is_set():
            try:
                audio = self._drain(self.queue.get(timeout=max(0.02, next_step - time.monotonic())))
                self._buf = np.concatenate([self._buf, audio])
                last_audio = now = time.monotonic()
                if now - last_level >= LEVEL_INTERVAL_SEC and len(audio):
                    self.session.level(self.name, 20 * np.log10(float(np.sqrt(np.mean(audio * audio))) + 1e-9))
                    last_level = now
            except queue.Empty:
                now = time.monotonic()
                if now - last_audio > STEP_SEC:
                    # Loopback diam total (tidak ada audio diputar) = hening.
                    self._buf = np.concatenate([self._buf, np.zeros(int((now - last_audio) * TARGET_SR), dtype=np.float32)])
                    last_audio = now
                    self.session.level(self.name, -90.0)
            if now < next_step:
                continue
            next_step = now + STEP_SEC
            self._step()

    def _step(self):
        buf = self._buf
        if len(buf) < MIN_SEC * TARGET_SR:
            return
        probs = speech_probs(buf)
        speech = np.flatnonzero(probs > SPEECH_PROB)
        if len(speech) == 0:
            if self._text:
                self._finish_rest(buf)
            self._buf = buf[-PREROLL_FRAMES * VAD_FRAME:]
            return
        if speech[0] > PREROLL_FRAMES:
            # Buang hening/musik di depan agar Whisper hanya membaca bagian yang ada suaranya.
            cut = (speech[0] - PREROLL_FRAMES) * VAD_FRAME
            buf = self._buf = buf[cut:]
            speech = speech - (speech[0] - PREROLL_FRAMES)
        trailing = len(probs) - 1 - speech[-1]
        if self._text and trailing >= self.pause_frames:
            end = (speech[-1] + 1) * VAD_FRAME
            self._finish_rest(buf[: end + 4 * VAD_FRAME])
            self._buf = buf[end:]
            return
        if len(buf) >= MAX_SEC * TARGET_SR:
            self._finish_rest(buf)
            self._buf = buf[-PREROLL_FRAMES * VAD_FRAME:]
            return
        self._partial(buf)

    # ------------------------------------------------------------------ sementara & final
    def _transcribe(self, audio):
        """Bacaan cepat untuk teks sementara (Whisper base bila ada, selain itu model utama)."""
        s = self.session
        asr, lock = (s.asr_fast, s.asr_fast_lock) if s.asr_fast is not None else (s.asr, s.asr_lock)
        t0 = time.perf_counter()
        with lock:
            segs, lang = asr.transcribe_segments(audio, language=self.source_lang or self._lang)
        return segs, lang, int((time.perf_counter() - t0) * 1000)

    def _partial(self, buf):
        segs, lang, asr_ms = self._transcribe(buf)
        if not segs:
            return
        self._lang = self._lang or lang
        dur = len(buf) / TARGET_SR
        # LocalAgreement: kalimat pertama sama pada 2 bacaan berturut-turut & sudah lewat -> final.
        if len(segs) >= 2 and segs[0][1] <= dur - COMMIT_GAP_SEC and _norm(segs[0][2]) == _norm(self._prev_first):
            _, end, text = segs[0]
            cut = int(end * TARGET_SR)
            self._commit(buf[:cut], text)
            self._buf = buf[cut:]
            segs = segs[1:]
        self._prev_first = segs[0][2]
        text = " ".join(t for _, _, t in segs)
        if text == self._text:
            return
        self._text = text
        self._emit(text, self._translation, asr_ms, 0, partial=True)
        now = time.monotonic()
        first = not self._translation and len(text) >= 6  # terjemahan pertama secepatnya
        if first or (now - self._last_mt >= MT_INTERVAL_SEC and len(text.split()) >= 2):
            self._last_mt = now
            self.mt.partial(self._seq, text, self._lang)

    def _commit(self, audio, text):
        """Kalimat selesai: kirim ke thread final (baca ulang model utama + terjemah), mulai kalimat baru."""
        self.mt.final(self._seq, audio, text, self._lang)
        self._seq += 1
        self._text, self._translation, self._prev_first = "", "", ""

    def _finish_rest(self, audio):
        text = self._text
        if not text:
            segs, lang, _ = self._transcribe(audio)
            text = " ".join(t for _, _, t in segs)
            self._lang = self._lang or lang
        if text:
            self._commit(audio, text)
        self._lang = None

    def _partial_translated(self, seq, text, translation):
        if seq == self._seq:
            self._translation = translation
            self._emit(self._text or text, translation, 0, 0, partial=True)
        elif seq == self._seq - 1 and seq not in self._done:
            # Kalimat barusan sudah selesai tapi terjemahan finalnya belum ada: tetap tampilkan yang terbaru.
            self._emit(text, translation, 0, 0, partial=True, seq=seq)

    def _final_translated(self, seq, text, translation, lang, asr_ms, mt_ms):
        self._done.add(seq)
        self._emit(text, translation, asr_ms, mt_ms, partial=False, seq=seq, lang=lang)

    def _emit(self, original, translation, asr_ms, mt_ms, partial, seq=None, lang=None):
        from .pipeline import Result

        self.session.emit(Result(self.name, original, translation, lang or self._lang or "", asr_ms, mt_ms,
                                 partial=partial, seq=self._seq if seq is None else seq))
