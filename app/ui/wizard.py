"""Panduan awal (muncul saat aplikasi pertama kali dibuka): selamat datang, cek sistem, rekam suara, lisensi."""

import os
import shutil
import threading

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QCheckBox, QFrame, QHBoxLayout, QLabel, QStackedWidget, QVBoxLayout, QWidget

from .. import gpu_check
from .theme import ASSETS, Palette
from .widgets import Progress, StatusCircle, StepBar, button, hbox, label, separator, vbox

SAMPLE_TEXT = (
    "\"Halo, nama saya … Saya sedang merekam suara saya untuk penerjemah otomatis. "
    "Hari ini cuacanya cerah, dan saya akan mengikuti rapat bersama tim.\""
)
LICENSE = (
    "XTTS-v2 hanya boleh dipakai untuk tujuan <b>non-komersial</b> (Coqui Public Model License, coqui.ai/cpml). "
    "Gunakan peniru suara hanya untuk suara Anda sendiri, atau suara orang yang sudah memberi izin. "
    "TranslateGemma tunduk pada Gemma Terms of Use. VB-CABLE adalah donationware dari VB-Audio Software."
)
N = 5


class _Check(QWidget):
    def __init__(self, title, sub, state="ok", text=None):
        super().__init__()
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 11, 0, 11)
        lay.setSpacing(12)
        self.status = StatusCircle(state, text)
        lay.addWidget(self.status)
        self.sub = label(sub, "rowSub", wrap=True)
        lay.addLayout(vbox(label(title, "rowTitle"), self.sub, spacing=1), 1)


class _Done(QWidget):
    def __init__(self):
        super().__init__()
        self.setFixedSize(64, 64)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        p.setBrush(Palette.q("ok_soft"))
        p.drawEllipse(QRectF(2, 2, 60, 60))
        pen = QPen(Palette.q("ok"), 5, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
        p.setPen(pen)
        p.drawPolyline([QPointF(x, y) for x, y in ((20, 33), (28, 41), (44, 24))])


class Wizard(QWidget):
    """Lapisan gelap di atas jendela + kartu modal di tengah."""

    finished = Signal()
    recorded = Signal(bool, str)

    def __init__(self, win, parent=None):
        super().__init__(parent or win)
        self.win = win
        self.step = 0
        self.hide()

        self.modal = QFrame(self)
        self.modal.setObjectName("modal")
        self.modal.setFixedWidth(620)
        ml = QVBoxLayout(self.modal)
        ml.setContentsMargins(0, 0, 0, 0)
        ml.setSpacing(0)
        self.bar = StepBar(N)
        ml.addLayout(hbox(self.bar, margins=(22, 18, 22, 0)))
        self.pages = QStackedWidget()
        self.pages.setMinimumHeight(300)
        ml.addWidget(self.pages)
        foot = QFrame()
        foot.setObjectName("modalFoot")
        fl = QHBoxLayout(foot)
        fl.setContentsMargins(22, 14, 22, 18)
        self.back = button("Kembali", "btnGhost")
        self.back.clicked.connect(lambda: self._go(self.step - 1))
        self.count = label("", "small")
        self.skip = button("Lewati", "btnGhost")
        self.skip.clicked.connect(lambda: self._go(self.step + 1))
        self.next = button("Lanjut", "btnPrimary")
        self.next.clicked.connect(self._next)
        fl.addWidget(self.back)
        fl.addWidget(self.count, 1)
        fl.addWidget(self.skip)
        fl.addWidget(self.next)
        ml.addWidget(foot)

        self._build_welcome()
        self._build_checks()
        self._build_record()
        self._build_license()
        self._build_done()
        self.recorded.connect(self._recorded)

    # ---------- halaman
    def _page(self, *items):
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(22, 20, 22, 8)
        lay.setSpacing(0)
        for it in items:
            if isinstance(it, int):
                lay.addSpacing(it)
            elif isinstance(it, QWidget):
                lay.addWidget(it)
            else:
                lay.addLayout(it)
        lay.addStretch(1)
        self.pages.addWidget(w)
        return lay

    def _title(self, text, lead):
        t = label(text, "modalTitle", wrap=True)
        l = label(lead, "modalLead", wrap=True, rich=True)
        return t, 6, l, 16

    def _build_welcome(self):
        logo = QLabel()
        pm = QPixmap(os.path.join(ASSETS, "icon.png"))
        pm.setDevicePixelRatio(pm.width() / 64)
        logo.setPixmap(pm)
        logo.setFixedSize(64, 64)
        rows = QWidget()
        rl = QVBoxLayout(rows)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(0)
        for i, (t, s) in enumerate((("Cek sistem", "GPU, driver, dan virtual mic"), ("Rekam suara Anda", "15 detik, untuk fitur Bicara"),
                                    ("Setujui lisensi suara", "XTTS-v2 non-komersial"))):
            if i:
                rl.addWidget(separator())
            c = _Check(t, s, "ok", str(i + 1))
            if i == 0:
                c.layout().setContentsMargins(0, 0, 0, 11)
            rl.addWidget(c)
        self._page(logo, 14, *self._title(
            "Selamat datang di AI Translator",
            "Terjemahkan rapat secara langsung — dengar orang lain lewat subtitle, dan bicara dalam bahasa lain dengan "
            "suara Anda sendiri. Semua offline di PC ini."), rows)

    def _build_checks(self):
        self.check_box = QVBoxLayout()
        self.check_box.setSpacing(0)
        self._page(*self._title("Cek sistem", "Memastikan PC siap menjalankan model offline."), self.check_box)

    def _build_record(self):
        q = label(SAMPLE_TEXT, "quote", wrap=True)
        self.rec_count = label("15", "countdown")
        self.rec_count.setFixedWidth(46)
        self.rec_prog = Progress("danger")
        self.rec_btn = button("● Mulai rekam", "btnDanger")
        self.rec_btn.clicked.connect(self._record)
        self._page(*self._title("Rekam suara Anda",
                                "Dipakai untuk meniru suara Anda saat fitur Bicara. Bisa dilewati dan dilakukan nanti."),
                   q, 14, hbox(self.rec_count, self.rec_prog, self.rec_btn, spacing=12))
        self._rec_timer = QTimer(self)
        self._rec_timer.timeout.connect(self._rec_tick)

    def _build_license(self):
        box = label(LICENSE, "licBox", wrap=True, rich=True)
        self.agree = QCheckBox("Saya setuju dan akan memakai peniru suara secara bertanggung jawab.")
        self.agree.setChecked(self.win.cfg.xtts_license_agreed)
        self.agree.toggled.connect(self._sync)
        self._page(*self._title("Lisensi suara XTTS-v2", "Model peniru suara memakai Coqui Public Model License."),
                   box, 12, self.agree)

    def _build_done(self):
        self.done_lead = label("", "modalLead", wrap=True, rich=True)
        self._page(_Done(), 14, label("Siap dipakai!", "modalTitle"), 6, self.done_lead)

    # ---------- alur
    def open(self, step=0):
        self.setGeometry(self.parentWidget().rect())
        self.show()
        self.raise_()
        self._go(step)

    def resizeEvent(self, e):
        self.modal.adjustSize()
        self.modal.move((self.width() - self.modal.width()) // 2, max(16, (self.height() - self.modal.height()) // 2))

    def paintEvent(self, e):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(2, 6, 23, 140))

    def mousePressEvent(self, e):
        if not self.modal.geometry().contains(e.position().toPoint()):
            self._close()

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Escape:
            self._close()

    def _go(self, i):
        self.step = max(0, min(N - 1, i))
        self.pages.setCurrentIndex(self.step)
        self.bar.set_step(self.step)
        self.count.setText("Langkah {} dari {}".format(self.step + 1, N))
        self.back.setVisible(self.step > 0)
        self.skip.setVisible(self.step == 2)
        self.next.setText("Mulai pakai" if self.step == N - 1 else "Lanjut")
        if self.step == 1:
            self._run_checks()
        if self.step == N - 1:
            self.done_lead.setText("Di Zoom/Meet/Teams pilih mikrofon <b>\"{}\"</b>. Lalu klik <b>Mulai sesi</b> di "
                                   "aplikasi ini.".format(self.win.vmic_name()))
        self._sync()
        self.resizeEvent(None)
        self.setFocus()

    def _sync(self, *_):
        self.next.setEnabled(not (self.step == 3 and not self.agree.isChecked()))

    def _next(self):
        if self.step == 3:
            self.win.cfg.xtts_license_agreed = True
        if self.step == N - 1:
            self._close(done=True)
            return
        self._go(self.step + 1)

    def _close(self, done=False):
        self._rec_timer.stop()
        self.win.cfg.onboarding_done = True
        self.win.cfg.save()
        self.hide()
        if done:
            self.win.toast("Siap! Klik Mulai sesi kapan saja")
        self.finished.emit()

    # ---------- cek sistem (nyata)
    def _run_checks(self):
        while self.check_box.count():
            it = self.check_box.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
        rows = []
        for i, t in enumerate(("GPU NVIDIA", "Virtual mic", "Model offline", "Ruang disk")):
            if i:
                self.check_box.addWidget(separator())
            c = _Check(t, "Memeriksa…", "wait")
            if i == 0:
                c.layout().setContentsMargins(0, 0, 0, 11)
            self.check_box.addWidget(c)
            rows.append(c)
        results = self._results()
        for i, (state, text) in enumerate(results):
            QTimer.singleShot(400 + i * 350, lambda c=rows[i], s=state, t=text: (c.status.set_state(s), c.sub.setText(t)))

    def _results(self):
        from ..config import APP_DIR, BUILTIN_MT_MODEL, MODELS_DIR

        g = gpu_check.get()
        if g.status == "ok":
            gpu = ("ok", "{} · {:.0f} GB · driver {}".format(g.name.replace("NVIDIA GeForce ", ""), g.vram_mb / 1024, g.driver)
                   if g.vram_mb else g.name)
        elif g.status == "old":
            gpu = ("warn", "Driver {} perlu diperbarui".format(g.driver))
        elif g.status == "missing":
            gpu = ("warn", "Driver NVIDIA belum terpasang")
        else:
            gpu = ("bad", "Tidak ada — aplikasi jalan di CPU")
        mic = {"ok": ("ok", self.win.vmic_name()), "raw": ("warn", "Perlu dirapikan (tombol Rapikan di Beranda)"),
               "none": ("bad", "Belum terpasang — fitur Bicara tidak bisa dipakai")}[self.win.mic_state]
        have = [os.path.exists(BUILTIN_MT_MODEL), os.path.isdir(os.path.join(MODELS_DIR, "whisper")),
                os.path.isdir(os.path.join(MODELS_DIR, "tts"))]
        models = ("ok", "Whisper · TranslateGemma · XTTS-v2") if all(have) else ("warn", "{}/3 terpasang".format(sum(have)))
        free = shutil.disk_usage(APP_DIR).free / 1024 ** 3
        disk = ("ok" if free > 2 else "warn", "{:.0f} GB kosong".format(free))
        return [gpu, mic, models, disk]

    # ---------- rekam
    def _record(self):
        from ..audio_capture import record_sample

        path = self.win.cfg.voice_sample
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        self.rec_btn.setEnabled(False)
        self._left = 15
        self.rec_count.setText("15")
        self.rec_prog.set_value(0)
        self._rec_timer.start(1000)
        device = self.win.cfg.mic_device

        def work():
            try:
                record_sample(device, 15, path)
                self.recorded.emit(True, "Sampel suara tersimpan")
            except Exception as e:
                self.recorded.emit(False, "Gagal merekam: {}".format(e))

        threading.Thread(target=work, daemon=True).start()

    def _rec_tick(self):
        self._left -= 1
        self.rec_count.setText(str(max(self._left, 0)))
        self.rec_prog.set_value((15 - self._left) / 15)
        if self._left <= 0:
            self._rec_timer.stop()

    def _recorded(self, ok, msg):
        self._rec_timer.stop()
        self.rec_btn.setEnabled(True)
        self.win.toast(msg, 4000)
        self.win.pages["speak"].refresh_voice()
        self.win.refresh_status()
        if ok:
            self._go(self.step + 1)
