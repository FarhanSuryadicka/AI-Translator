"""Halaman-halaman jendela utama (Beranda, Dengar, Bicara, Subtitle, Riwayat, Pengaturan, Tentang)."""

import datetime
import os
import threading

from PySide6.QtCore import QFileInfo, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import (
    QAbstractButton, QComboBox, QFileDialog, QFileIconProvider, QFrame, QGridLayout, QHBoxLayout, QLabel,
    QLineEdit, QPushButton, QSlider, QSizePolicy, QVBoxLayout, QWidget,
)

from .. import gpu_check, history
from ..languages import LANGUAGES, language_label, sorted_codes
from ..tts import XTTS_LANGUAGES
from .theme import Palette, font
from .widgets import (
    AutoGrid, Banner, Card, DirCard, tag, Feed, IconLabel, MeterRow, ModelCard, MsgItem, Progress, RoundButton, Route,
    Segmented, SettingRows, SourceCard, Stage, StatusCircle, Switch, VramBar, Wave, button, hbox, label, separator,
    theme_bus, vbox, wrap,
)

SAMPLE_TEXT = (
    "\"Halo, nama saya … Saya sedang merekam suara saya untuk penerjemah otomatis. "
    "Hari ini cuacanya cerah, dan saya akan mengikuti rapat bersama tim.\""
)
RECORD_SECONDS = 15
WHISPER_MODELS = [
    ("tiny", "75 MB", 1, 5), ("base", "145 MB", 2, 4), ("small", "480 MB", 3, 4),
    ("medium", "1,5 GB", 4, 2), ("large-v3-turbo", "1,6 GB", 5, 3),
]
# Nama tampilan untuk aplikasi rapat/streaming yang umum.
KNOWN_APPS = {
    "zoom.exe": ("Zoom", "Zoom.exe"), "chrome.exe": ("Chrome", "Meet · YouTube"), "msedge.exe": ("Edge", "msedge.exe"),
    "ms-teams.exe": ("Teams", "ms-teams.exe"), "teams.exe": ("Teams", "Teams.exe"), "discord.exe": ("Discord", "Discord.exe"),
    "firefox.exe": ("Firefox", "firefox.exe"), "slack.exe": ("Slack", "slack.exe"), "webex.exe": ("Webex", "webex.exe"),
    "spotify.exe": ("Spotify", "Spotify.exe"), "vlc.exe": ("VLC", "vlc.exe"), "obs64.exe": ("OBS", "obs64.exe"),
}
GUIDES = {
    "zoom": ["Buka <b>Settings</b> → <b>Audio</b>.", "Di <b>Microphone</b>, pilih <span style='{kbd}'>{mic}</span>.",
             "Matikan <b>Automatically adjust microphone volume</b> agar suara terjemahan tidak dikecilkan."],
    "meet": ["Saat rapat, klik <b>⋮</b> → <b>Settings</b> → <b>Audio</b>.", "Di <b>Microphone</b>, pilih <span style='{kbd}'>{mic}</span>.",
             "Biarkan <b>Speaker</b> tetap headset Anda."],
    "teams": ["Klik <b>⋯</b> → <b>Settings</b> → <b>Devices</b>.", "Di <b>Microphone</b>, pilih <span style='{kbd}'>{mic}</span>.",
              "Set <b>Noise suppression</b> ke <b>Low</b> agar suara tidak terpotong."],
}


REMOTE_APPS = {"anydesk.exe": "AnyDesk", "rustdesk.exe": "RustDesk", "teamviewer.exe": "TeamViewer",
               "parsecd.exe": "Parsec", "remoting_host.exe": "Chrome Remote Desktop"}


def remote_desktop_apps():
    """Nama aplikasi remote desktop yang sedang berjalan di sesi pengguna ini."""
    import psutil

    found = []
    for p in psutil.process_iter(["name"]):
        name = REMOTE_APPS.get((p.info["name"] or "").lower())
        if name and name not in found:
            found.append(name)
    return found


def short_device(name):
    """'Headset Microphone (Realtek Audio)' -> 'Headset Microphone'."""
    return name.split(" (")[0] if name else name


class Page(QWidget):
    title = ""
    subtitle = ""

    def __init__(self, win):
        super().__init__()
        self.win = win
        self.cfg = win.cfg
        self.lay = QVBoxLayout(self)
        self.lay.setContentsMargins(0, 0, 0, 0)
        self.lay.setSpacing(16)

    def on_show(self):
        pass


def lang_combo(codes, auto=False, short=False):
    c = QComboBox()
    if auto:
        c.addItem("Otomatis" if short else "Deteksi otomatis", "auto")
    for code in sorted_codes(codes):
        text = language_label(code)
        c.addItem(text.replace("Bahasa ", "") if short else text, code)
    return c


def grid2(*widgets, cols=2, ratios=None):
    g = QGridLayout()
    g.setSpacing(16)
    for i, w in enumerate(widgets):
        g.addWidget(w, i // cols, i % cols)
    for i in range(cols):
        g.setColumnStretch(i, ratios[i] if ratios else 1)
    return g


def lang_pair(win, src_attr, tgt_attr, src_codes, tgt_codes, auto=True):
    src, tgt = lang_combo(src_codes, auto), lang_combo(tgt_codes)
    win.binder.combo(src_attr, src)
    win.binder.combo(tgt_attr, tgt)
    swap = button("⇄", "swap", tooltip="Tukar bahasa")
    swap.setFixedSize(34, 34)

    def do_swap():
        a, b = getattr(win.cfg, src_attr), getattr(win.cfg, tgt_attr)
        if a == "auto":
            win.toast("Pilih bahasa sumber dulu (bukan Deteksi otomatis)")
            return
        if a not in tgt_codes or b not in src_codes:
            win.toast("Bahasa ini tidak bisa ditukar")
            return
        win.binder.set(src_attr, b)
        win.binder.set(tgt_attr, a)

    swap.clicked.connect(do_swap)
    row = QHBoxLayout()
    row.setSpacing(8)
    row.addWidget(src, 1)
    row.addWidget(swap)
    row.addWidget(tgt, 1)
    return row


class DirIcon(QWidget):
    """Ikon arah 40px di dalam kotak berwarna lembut (.dir-ic)."""

    def __init__(self, icon_name, key):
        super().__init__()
        self.setFixedSize(40, 40)
        self.icon, self.key = icon_name, key

    def paintEvent(self, e):
        from . import icons

        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        c = QColor(Palette.c[self.key])
        c.setAlphaF(0.14)
        p.setPen(Qt.NoPen)
        p.setBrush(c)
        p.drawRoundedRect(QRectF(0, 0, 40, 40), 11, 11)
        p.drawPixmap(10, 10, icons.pixmap(self.icon, Palette.c[self.key], 20))


class CheckRow(QWidget):
    """Baris kesiapan sistem: (✓) Judul / keterangan [tombol]."""

    def __init__(self, title, sub="", button_widget=None):
        super().__init__()
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 11, 0, 11)
        lay.setSpacing(12)
        self.status = StatusCircle("ok")
        lay.addWidget(self.status)
        col = QVBoxLayout()
        col.setSpacing(1)
        self.title = label(title, "rowTitle", wrap=True)
        self.sub = label(sub, "rowSub", wrap=True)
        col.addWidget(self.title)
        col.addWidget(self.sub)
        lay.addLayout(col, 1)
        self.button = button_widget
        if button_widget is not None:
            lay.addWidget(button_widget)

    def set(self, state, title=None, sub=None):
        self.status.set_state(state)
        if title is not None:
            self.title.setText(title)
        if sub is not None:
            self.sub.setText(sub)


def checks_card(rows):
    box = QWidget()
    lay = QVBoxLayout(box)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(0)
    for i, r in enumerate(rows):
        if i:
            lay.addWidget(separator())
        else:
            r.layout().setContentsMargins(0, 0, 0, 11)
        lay.addWidget(r)
    return box


# ===================================================================== Beranda
class HomePage(Page):
    title, subtitle = "Beranda", "Atur arah terjemahan, lalu mulai sesi."

    def __init__(self, win):
        super().__init__(win)
        cfg = self.cfg

        # --- dua arah ---
        self.listen_card = DirCard("listen")
        self.listen_switch = Switch(cfg.listen_enabled)
        win.binder.switch("listen_enabled", self.listen_switch)
        self.listen_card.body.addLayout(self._dir_head("ear", "listen", "Dengar", "Suara orang lain → subtitle", self.listen_switch))
        self.listen_route = Route(["Semua suara", "Whisper", "Gemma", "Subtitle"])
        self.listen_card.body.addWidget(self.listen_route)
        self.listen_card.body.addLayout(lang_pair(win, "source_language", "target_language", LANGUAGES, LANGUAGES))
        self.listen_meter = MeterRow("wave")
        self.listen_card.body.addWidget(self.listen_meter)

        self.speak_card = DirCard("speak")
        self.speak_switch = Switch(cfg.speak_enabled)
        win.binder.switch("speak_enabled", self.speak_switch)
        self.speak_card.body.addLayout(self._dir_head("mic", "speak", "Bicara", "Suara Anda → suara terjemahan di rapat", self.speak_switch))
        self.speak_route = Route(["Mic", "Gemma", "Suara Anda", "AI Translator Mic"])
        self.speak_card.body.addWidget(self.speak_route)
        self.speak_card.body.addLayout(lang_pair(win, "mic_language", "speak_target_language", LANGUAGES, XTTS_LANGUAGES))
        self.speak_meter = MeterRow("mic")
        self.speak_card.body.addWidget(self.speak_meter)
        self.lay.addLayout(grid2(self.listen_card, self.speak_card))

        # --- transkrip + kesiapan ---
        feed_card = Card()
        self.filter = Segmented([("all", "Semua"), ("in", "Dengar"), ("out", "Bicara")])
        feed_card.header("Transkrip langsung", None, self.filter)
        self.feed = Feed("Belum ada percakapan. Klik <b>Mulai sesi</b> untuk mulai menerjemahkan.", max_height=None)
        self.feed.setMinimumHeight(300)
        self.filter.changed.connect(self.feed.set_filter)
        feed_card.add(self.feed, 1)

        ready = Card()
        self.ready_hint = label("Semua siap", "hint")
        wiz_btn = button("Panduan awal", "btnGhost")
        wiz_btn.clicked.connect(win.open_wizard)
        row = ready.header("Kesiapan sistem")
        row.insertWidget(1, self.ready_hint)
        row.addWidget(wiz_btn)
        self.fix_btn = button("Rapikan", "btnWarn")
        self.fix_btn.clicked.connect(win.fix_virtual_mic)
        voice_btn = button("Ubah", "btnGhost")
        voice_btn.clicked.connect(lambda: win.go("speak"))
        self.c_gpu = CheckRow("GPU", "")
        self.c_mic = CheckRow("Virtual mic", "", self.fix_btn)
        self.c_voice = CheckRow("Sampel suara Anda", "", voice_btn)
        self.c_models = CheckRow("Model offline", "Whisper small · TranslateGemma 4B · XTTS-v2")
        ready.add(checks_card([self.c_gpu, self.c_mic, self.c_voice, self.c_models]))

        stats = Card()
        stats.header("Sesi ini")
        self.st_time, self.st_count, self.st_lat = label("00:00", "statVal"), label("0", "statVal"), label("—", "statVal")
        g = QGridLayout()
        g.setSpacing(10)
        for i, (v, t) in enumerate(((self.st_time, "Durasi"), (self.st_count, "Kalimat"), (self.st_lat, "Rata-rata jeda"))):
            g.addLayout(vbox(v, label(t, "small"), spacing=2), 0, i)
        stats.add(g)

        right = QVBoxLayout()
        right.setSpacing(16)
        right.addWidget(ready)
        right.addWidget(stats)
        right.addStretch(1)
        self.lay.addLayout(grid2(feed_card, wrap(right), ratios=[115, 100]))

        win.binder.on("listen_enabled", lambda v: self.listen_card.set_off(not v))
        win.binder.on("speak_enabled", lambda v: self.speak_card.set_off(not v))
        self.listen_card.set_off(not cfg.listen_enabled)
        self.speak_card.set_off(not cfg.speak_enabled)

    def _dir_head(self, icon_name, key, title, sub, switch):
        row = QHBoxLayout()
        row.setSpacing(12)
        row.addWidget(DirIcon(icon_name, key))
        row.addLayout(vbox(label(title, "dirTitle"), label(sub, "small"), spacing=0), 1)
        row.addWidget(switch, 0, Qt.AlignTop)
        return row

    def set_routes(self, source, mic, vmic):
        self.listen_route.chips[0].setText(source)
        self.speak_route.chips[0].setText(mic)
        self.speak_route.chips[3].setText(vmic)


# ===================================================================== Dengar
class ListenPage(Page):
    title, subtitle = "Dengar", "Terjemahkan suara dari aplikasi rapat menjadi subtitle."

    def __init__(self, win):
        super().__init__(win)
        src = Card()
        refresh = button("↻ Muat ulang", "btnGhost")
        refresh.clicked.connect(lambda: (self.refresh_sources(), win.toast("Daftar aplikasi dimuat ulang")))
        src.header("Tangkap suara dari", "Hanya suara aplikasi yang dipilih yang diterjemahkan; notifikasi & musik diabaikan.", refresh)
        self.grid = AutoGrid(132, 92, 10)
        src.add(self.grid)
        self.lay.addWidget(src)

        lang = Card()
        lang.header("Bahasa")
        lang.add(lang_pair(win, "source_language", "target_language", LANGUAGES, LANGUAGES))
        lang.add(label("Deteksi otomatis mengenali bahasa secara otomatis. Pilih bahasa tetap kalau pembicara hanya "
                       "satu bahasa (sedikit lebih cepat & akurat).", "small", wrap=True))
        lang.body.addStretch(1)

        vad = Card()
        vad.header("Deteksi kalimat")
        self.meter = MeterRow()
        vad.add(self.meter)
        self.pause_label = label("", "fieldLabel")
        self.pause = QSlider(Qt.Horizontal)
        self.pause.setRange(3, 15)
        self.pause.setValue(round(self.cfg.listen_pause_ms / 100))
        self.pause.valueChanged.connect(self._pause_changed)
        self._pause_changed(self.pause.value())
        vad.add(vbox(self.pause_label, self.pause, spacing=6))
        vad.add(label("Lebih pendek = kalimat lebih cepat final, tapi bisa terpotong.", "small", wrap=True))
        live = Switch(self.cfg.live_captions)
        win.binder.switch("live_captions", live)
        live_rows = SettingRows()
        live_rows.add("Subtitle langsung (per kata)",
                      "Teks muncul selagi orang bicara, ±1 detik, seperti caption Google Meet. Butuh GPU NVIDIA.", live)
        vad.add(separator())
        vad.add(live_rows)
        self.lay.addLayout(grid2(lang, vad))

        inc = Card()
        to_sub = button("Atur subtitle →", "btnGhost")
        to_sub.clicked.connect(lambda: win.go("subtitle"))
        inc.header("Terjemahan masuk", None, to_sub)
        self.feed = Feed("Belum ada suara yang diterjemahkan.", max_height=340, empty_icon=False)
        inc.add(self.feed)
        self.lay.addWidget(inc)
        self.lay.addStretch(1)
        self.cards = {}
        self.refresh_sources()

    def _pause_changed(self, v):
        self.cfg.listen_pause_ms = v * 100
        self.pause_label.setText("Jeda akhir kalimat: {} dtk".format("{:.1f}".format(v / 10).replace(".", ",")))

    def refresh_sources(self):
        from ..process_loopback import list_audio_apps_with_paths

        try:
            apps = list_audio_apps_with_paths()
        except Exception:
            apps = []
        current = self.cfg.loopback_app
        if current and current not in [a for a, _ in apps]:
            apps.append((current, ""))
        provider = QFileIconProvider()
        self.grid.clear()
        self.cards = {}
        cards = [SourceCard("", "Semua suara", "Speaker default", letter="∑", color="#64748b")]
        for name, path in apps:
            title, sub = KNOWN_APPS.get(name.lower(), (os.path.splitext(name)[0], name))
            if not path:
                sub = "belum dibuka"
            pm = provider.icon(QFileInfo(path)).pixmap(QSize(60, 60)) if path else None
            cards.append(SourceCard(name, title, sub, pixmap=pm))
        for c in cards:
            c.setChecked(c.key == current)
            c.clicked.connect(lambda _=False, card=c: self._pick(card))
            self.grid.add(c)
            self.cards[c.key] = c
        if current not in self.cards:
            self.cards[""].setChecked(True)
        self.win.update_routes()

    def _pick(self, card):
        for c in self.cards.values():
            c.setChecked(c is card)
        self.cfg.loopback_app = card.key
        self.win.update_routes()
        self.win.sync_playing()
        self.win.toast("Menangkap: " + card.title)

    def source_title(self):
        c = self.cards.get(self.cfg.loopback_app)
        return c.title if c else "Semua suara"

    def set_playing(self, on):
        for c in self.cards.values():
            c.set_playing(on and c.isChecked())


# ===================================================================== Bicara
class SpeakPage(Page):
    title, subtitle = "Bicara", "Ucapan Anda diterjemahkan dan diucapkan dengan suara Anda."
    recorded = Signal(str, bool)

    def __init__(self, win):
        super().__init__(win)
        cfg = self.cfg
        self.banner = Banner("Virtual mic belum dirapikan", "", "Rapikan (izin admin)")
        self.banner.button.clicked.connect(win.fix_virtual_mic)
        self.banner.hide()
        self.lay.addWidget(self.banner)

        flow = Card()
        flow.header("Alur suara", "Tahap yang sedang bekerja menyala saat sesi berjalan.")
        fl = QHBoxLayout()
        fl.setSpacing(8)
        self.stages = [
            Stage("mic", "Mic Anda", "Headset Mic"), Stage("text", "Teks", "Whisper · 0,3 dtk"),
            Stage("globe", "Terjemah", "Gemma · 0,7 dtk"), Stage("wave", "Suara Anda", "XTTS · 0,5 dtk"),
            Stage("plug", "Ke rapat", "AI Translator Mic"),
        ]
        for s in self.stages:
            fl.addWidget(s, 1)
        flow.add(fl)
        self.lay.addWidget(flow)

        # --- input & bahasa ---
        inp = Card()
        inp.header("Input & bahasa")
        rows = SettingRows()
        self.mic_combo = QComboBox()
        self.mic_combo.setFixedWidth(230)
        self.mic_combo.currentIndexChanged.connect(self._mic_changed)
        rows.add("Mikrofon", "Gunakan headset agar suara peserta lain tidak ikut tertangkap.", self.mic_combo)
        self.meter = MeterRow()
        self.meter.setFixedWidth(230)
        rows.add("Level mic", None, self.meter)
        src, tgt = lang_combo(LANGUAGES, auto=True, short=True), lang_combo(XTTS_LANGUAGES, short=True)
        for c in (src, tgt):
            c.setFixedWidth(124)
        win.binder.combo("mic_language", src)
        win.binder.combo("speak_target_language", tgt)
        rows.add("Bahasa Anda → bahasa suara", "Bahasa suara mengikuti yang didukung XTTS-v2 (17 bahasa).",
                 hbox(src, label("→", "arrow"), tgt, spacing=6))
        mon = Switch(cfg.speak_monitor)
        win.binder.switch("speak_monitor", mon)
        rows.add("Dengar suara terjemahan sendiri", "Ikut diputar pelan di headset untuk memantau.", mon)
        inp.add(rows)
        inp.body.addStretch(1)

        # --- sampel suara ---
        voice = Card()
        voice.header("Sampel suara Anda", "Dipakai untuk meniru suara Anda.")
        vrow = QFrame()
        vrow.setObjectName("route")
        vl = QHBoxLayout(vrow)
        vl.setContentsMargins(12, 12, 12, 12)
        vl.setSpacing(12)
        self.play_btn = RoundButton("play", "speak")
        self.play_btn.clicked.connect(self._play)
        self.wave = Wave()
        self.dur = label("0:00", "small")
        vl.addWidget(self.play_btn)
        vl.addWidget(self.wave, 1)
        vl.addWidget(self.dur)
        voice.add(vrow)
        self.voice_name = label("my_voice.wav", "rowTitle")
        self.voice_info = label("", "rowSub", wrap=True)
        self.rec_btn = button("● Rekam ulang", "btn")
        self.rec_btn.clicked.connect(self._start_record)
        pick = button("Pilih file…", "btnGhost")
        pick.clicked.connect(self._pick_file)
        voice.add(hbox(vbox(self.voice_name, self.voice_info, spacing=1), "stretch", self.rec_btn, pick))
        self.rec_box = QFrame()
        self.rec_box.setObjectName("card")
        self.rec_box.setStyleSheet("#card { border-style: dashed; }")
        rb = QVBoxLayout(self.rec_box)
        rb.setContentsMargins(14, 14, 14, 14)
        rb.setSpacing(10)
        rb.addWidget(label("Bacakan teks ini dengan suara dan tempo normal:", wrap=True))
        rb.addWidget(label(SAMPLE_TEXT, "quote", wrap=True))
        self.count = label(str(RECORD_SECONDS), "countdown")
        self.count.setFixedWidth(46)
        self.prog = Progress("danger")
        cancel = button("Batal", "btnDanger")
        cancel.clicked.connect(self._cancel_record)
        rb.addLayout(hbox(self.count, self.prog, cancel, spacing=12))
        self.rec_box.hide()
        voice.add(self.rec_box)
        voice.body.addStretch(1)
        self.lay.addLayout(grid2(inp, voice, ratios=[115, 100]))

        # --- panduan aplikasi rapat ---
        guide = Card()
        self.guide_seg = Segmented([("zoom", "Zoom"), ("meet", "Google Meet"), ("teams", "Teams")])
        self.guide_seg.changed.connect(self._guide)
        guide.header("Pakai di aplikasi rapat", None, self.guide_seg)
        self.guide_box = QVBoxLayout()
        self.guide_box.setSpacing(0)
        guide.add(self.guide_box)
        self.lay.addWidget(guide)
        self.lay.addStretch(1)

        self._rec_timer = QTimer(self)
        self._rec_timer.timeout.connect(self._rec_tick)
        self._rec_left = 0
        self._rec_cancel = False
        self.recorded.connect(self._recorded)
        self._guide("zoom")
        self.refresh_devices()
        self.refresh_voice()
        theme_bus.changed.connect(lambda: self._guide(self.guide_seg.value()))

    # ---- perangkat & panduan
    def refresh_devices(self):
        from ..audio_capture import list_input_devices

        try:
            mics = [m for m in list_input_devices() if "VB-Audio" not in m]
        except Exception:
            mics = []
        self.mic_combo.blockSignals(True)
        self.mic_combo.clear()
        self.mic_combo.addItem("Mic default Windows", "")
        for m in mics:
            self.mic_combo.addItem(m, m)
        idx = self.mic_combo.findData(self.cfg.mic_device)
        self.mic_combo.setCurrentIndex(max(idx, 0))
        self.mic_combo.blockSignals(False)
        self.has_mic = bool(mics)

    def _mic_changed(self):
        self.cfg.mic_device = self.mic_combo.currentData() or ""
        self.win.update_routes()

    def mic_title(self):
        return short_device(self.cfg.mic_device) or "Mic default"

    def _guide(self, key):
        while self.guide_box.count():
            it = self.guide_box.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
        kbd = "font-weight:600; border:1px solid {}; background:{}; border-radius:5px; padding:1px 6px;".format(
            Palette.c["line_strong"], Palette.c["sunken"])
        for i, text in enumerate(GUIDES[key]):
            num = label(str(i + 1), "guideNum")
            num.setFixedSize(24, 24)
            num.setAlignment(Qt.AlignCenter)
            t = label(text.format(kbd=kbd, mic=self.win.vmic_name()), wrap=True, rich=True)
            t.setStyleSheet("font-size: 13px;")
            row = QWidget()
            rl = QHBoxLayout(row)
            rl.setContentsMargins(0, 8, 0, 8)
            rl.setSpacing(10)
            rl.addWidget(num, 0, Qt.AlignTop)
            rl.addWidget(t, 1)
            self.guide_box.addWidget(row)

    def refresh_guide(self):
        self._guide(self.guide_seg.value())

    # ---- sampel suara
    def refresh_voice(self):
        from ..audio_capture import read_wav

        path = self.cfg.voice_sample
        self.voice_name.setText(os.path.basename(path) or "—")
        if not os.path.exists(path):
            self.voice_info.setText("Belum ada sampel. Klik Rekam untuk membuat (15 detik).")
            self.rec_btn.setText("● Rekam")
            self.dur.setText("0:00")
            self.voice_ok = False
            return
        try:
            audio, sr = read_wav(path)
        except Exception:
            audio, sr = None, 16000
        secs = len(audio) / sr if audio is not None else 0
        self.wave.set_audio(audio)
        self.dur.setText("{}:{:02d}".format(int(secs // 60), int(secs % 60)))
        when = datetime.datetime.fromtimestamp(os.path.getmtime(path))
        months = ["Jan", "Feb", "Mar", "Apr", "Mei", "Jun", "Jul", "Agu", "Sep", "Okt", "Nov", "Des"]
        quality = "kualitas baik" if secs >= 8 else "terlalu pendek, rekam minimal 10 detik"
        self.voice_info.setText("Direkam {} {} {} · {}".format(when.day, months[when.month - 1], when.year, quality))
        self.rec_btn.setText("● Rekam ulang")
        self.voice_ok = True
        self.voice_secs = secs

    def _play(self):
        from ..audio_capture import play_wav

        if not os.path.exists(self.cfg.voice_sample):
            self.win.toast("Belum ada sampel suara")
            return
        self.play_btn.set_icon("stop")
        self.win.toast("Memutar sampel suara…")

        def work():
            try:
                play_wav(self.cfg.voice_sample)
            except Exception as e:
                self.win.bridge.toast.emit("Gagal memutar: {}".format(e))
            self.win.bridge.call.emit(lambda: self.play_btn.set_icon("play"))

        threading.Thread(target=work, daemon=True).start()

    def _pick_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "Pilih sampel suara", "", "Audio WAV (*.wav)")
        if path:
            self.cfg.voice_sample = path
            self.refresh_voice()
            self.win.refresh_status()

    def _start_record(self):
        from ..audio_capture import record_sample

        if not self.has_mic:
            self.win.toast("Tidak ada mikrofon terdeteksi. Colokkan headset ber-mic dulu.")
            return
        path = self.cfg.voice_sample
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        self.rec_box.show()
        self.rec_btn.setEnabled(False)
        self._rec_left = RECORD_SECONDS
        self._rec_cancel = False
        self.count.setText(str(RECORD_SECONDS))
        self.prog.set_value(0)
        self._rec_timer.start(1000)
        device = self.cfg.mic_device

        def work():
            try:
                record_sample(device, RECORD_SECONDS, path + ".tmp.wav")
                if self._rec_cancel:
                    os.remove(path + ".tmp.wav")
                    return
                os.replace(path + ".tmp.wav", path)
                self.recorded.emit("Sampel suara tersimpan ({} dtk)".format(RECORD_SECONDS), True)
            except Exception as e:
                self.recorded.emit("Gagal merekam: {}".format(e), False)

        threading.Thread(target=work, daemon=True).start()

    def _rec_tick(self):
        self._rec_left -= 1
        self.count.setText(str(max(self._rec_left, 0)))
        self.prog.set_value((RECORD_SECONDS - self._rec_left) / RECORD_SECONDS)
        if self._rec_left <= 0:
            self._rec_timer.stop()

    def _cancel_record(self):
        self._rec_cancel = True
        self._rec_timer.stop()
        self.rec_box.hide()
        self.rec_btn.setEnabled(True)

    def _recorded(self, msg, ok):
        self._rec_timer.stop()
        self.rec_box.hide()
        self.rec_btn.setEnabled(True)
        if not self._rec_cancel:
            self.win.toast(msg)
        self.refresh_voice()
        self.win.refresh_status()

    # ---- alur
    def animate(self):
        for i, s in enumerate(self.stages):
            QTimer.singleShot(i * 260, lambda s=s: ([x.set_active(False) for x in self.stages], s.set_active(True)))
        QTimer.singleShot(1500, lambda: [x.set_active(False) for x in self.stages])

    def set_timings(self, asr_ms, mt_ms):
        self.stages[1].sub.setText("Whisper · {} dtk".format("{:.1f}".format(asr_ms / 1000).replace(".", ",")))
        self.stages[2].sub.setText("Gemma · {} dtk".format("{:.1f}".format(mt_ms / 1000).replace(".", ",")))


# ===================================================================== Subtitle
class SubtitlePreview(QWidget):
    """Tampilan rapat tiruan + subtitle yang bisa digeser (posisi ikut ke subtitle asli)."""

    dragged = Signal(float)  # posisi atas subtitle relatif 0..1

    def __init__(self, cfg):
        super().__init__()
        self.cfg = cfg
        self.original = "Let's go over the budget for next quarter."
        self.translation = "Mari kita bahas anggaran untuk kuartal berikutnya."
        self.custom_y = None
        self._drag = None
        self.setMinimumHeight(240)
        self.setCursor(Qt.OpenHandCursor)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, w):
        return int(w * 8.5 / 16)

    def sizeHint(self):
        return QSize(560, 298)

    def set_text(self, o, t):
        self.original, self.translation = o, t
        self.update()

    def _box(self):
        fs = self.cfg.font_size
        w = self.width() * 0.78
        p_o = max(10, int(fs * 0.58))
        p_t = max(11, int(fs * 0.74))
        f_t = font(p_t, QFont.DemiBold)
        from PySide6.QtGui import QFontMetrics

        lines = max(1, QFontMetrics(f_t).boundingRect(0, 0, int(w - 32), 999, Qt.TextWordWrap, self.translation).height())
        h = 16 + lines + ((p_o * 1.5) if self.cfg.show_original else 0)
        x = (self.width() - w) / 2
        if self.custom_y is not None:
            y = self.custom_y * self.height()
        elif self.cfg.overlay_position == "top":
            y = 14
        else:
            y = self.height() - 52 - h
        y = max(6, min(y, self.height() - h - 6))
        return QRectF(x, y, w, h), p_o, f_t

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        W, H = self.width(), self.height()
        p.setPen(Qt.NoPen)
        p.setBrush(QColor("#0b1220"))
        p.drawRoundedRect(QRectF(0, 0, W, H), 12, 12)
        # 3x2 peserta
        gx, gy, gap = 10, 10, 6
        cw, ch = (W - 2 * gx - 2 * gap) / 3, (H - gy - 46 - gap) / 2
        for r in range(2):
            for c in range(3):
                tile = QRectF(gx + c * (cw + gap), gy + r * (ch + gap), cw, ch)
                p.setBrush(QColor("#273449"))
                p.drawRoundedRect(tile, 8, 8)
                d = min(cw, ch) * 0.36
                p.setBrush(QColor("#475569"))
                p.drawEllipse(QRectF(tile.center().x() - d / 2, tile.y() + ch * 0.42 - d / 2, d, d))
        p.setBrush(QColor("#0f172a"))
        p.drawRect(QRectF(0, H - 38, W, 38))
        cx = W / 2
        for i, (dx, wd, col) in enumerate(((-75, 26, "#334155"), (-39, 26, "#334155"), (-3, 44, "#dc2626"), (51, 26, "#334155"))):
            p.setBrush(QColor(col))
            p.drawRoundedRect(QRectF(cx + dx - 13 + (0 if wd == 26 else 0), H - 32, wd, 26), 13, 13)
        if not self.cfg.overlay_enabled:
            return
        box, p_o, f_t = self._box()
        p.setBrush(QColor(0, 0, 0, int(255 * self.cfg.overlay_opacity)))
        p.drawRoundedRect(box, 10, 10)
        tag = QRectF(box.right() - 58, box.top() - 9, 48, 16)
        p.setBrush(Palette.q("accent"))
        p.drawRoundedRect(tag, 4, 4)
        p.setPen(QColor("#ffffff"))
        p.setFont(font(10, QFont.DemiBold))
        p.drawText(tag, Qt.AlignCenter, "Overlay")
        inner = box.adjusted(16, 8, -16, -8)
        if self.cfg.show_original:
            p.setPen(QColor("#cbd5e1"))
            p.setFont(font(p_o))
            p.drawText(QRectF(inner.x(), inner.y(), inner.width(), p_o * 1.5), Qt.AlignHCenter | Qt.AlignVCenter, self.original)
            inner.setTop(inner.top() + p_o * 1.5)
        p.setPen(QColor("#ffffff"))
        p.setFont(f_t)
        p.drawText(inner, Qt.AlignHCenter | Qt.AlignTop | Qt.TextWordWrap, self.translation)

    def mousePressEvent(self, e):
        box, _, _ = self._box()
        if box.contains(e.position()):
            self._drag = e.position().y() - box.y()
            self.setCursor(Qt.ClosedHandCursor)

    def mouseMoveEvent(self, e):
        if self._drag is not None:
            self.custom_y = max(0.0, min(1.0, (e.position().y() - self._drag) / self.height()))
            self.update()

    def mouseReleaseEvent(self, e):
        if self._drag is not None:
            self._drag = None
            self.setCursor(Qt.OpenHandCursor)
            self.dragged.emit(self.custom_y)


class SubtitlePage(Page):
    title, subtitle = "Subtitle", "Atur tampilan subtitle melayang."

    def __init__(self, win):
        super().__init__(win)
        cfg = self.cfg
        prev = Card()
        on = Switch(cfg.overlay_enabled)
        on.setToolTip("Tampilkan overlay")
        on.toggled.connect(self._enabled)
        prev.header("Pratinjau", "Seret subtitle untuk memindahkan.", on)
        self.preview = SubtitlePreview(cfg)
        self.preview.dragged.connect(self._dragged)
        prev.add(self.preview)
        prev.body.addStretch(1)

        look = Card()
        look.header("Tampilan")
        rows = SettingRows()
        self.pos = Segmented([("bottom", "Bawah"), ("top", "Atas")], cfg.overlay_position)
        self.pos.changed.connect(self._position)
        rows.add("Posisi", None, self.pos)
        self.fs_label = label("", "fieldLabel")
        fs = QSlider(Qt.Horizontal)
        fs.setRange(14, 40)
        fs.setValue(min(max(cfg.font_size, 14), 40))
        fs.valueChanged.connect(self._font)
        rows.add(None, block=wrap(vbox(self.fs_label, fs, spacing=6)))
        self.op_label = label("", "fieldLabel")
        op = QSlider(Qt.Horizontal)
        op.setRange(0, 100)
        op.setValue(round(cfg.overlay_opacity * 100))
        op.valueChanged.connect(self._opacity)
        rows.add(None, block=wrap(vbox(self.op_label, op, spacing=6)))
        show_o = Switch(cfg.show_original)
        show_o.toggled.connect(lambda v: self._set("show_original", v))
        rows.add("Tampilkan teks asli", "Di atas terjemahan, lebih kecil.", show_o)
        self.cap = Switch(cfg.hide_from_capture)
        self.cap.toggled.connect(self._capture)
        rows.add("Sembunyikan saat share screen",
                 "Peserta lain tidak melihat subtitle Anda. Subtitle juga tidak terlihat di screenshot dan "
                 "remote desktop (AnyDesk, RustDesk, TeamViewer).", self.cap)
        hide = QComboBox()
        hide.setFixedWidth(120)
        for secs, text in ((8, "8 detik"), (4, "4 detik"), (0, "Tidak")):
            hide.addItem(text, secs)
        hide.setCurrentIndex(max(hide.findData(cfg.overlay_autohide_sec), 0))
        hide.currentIndexChanged.connect(lambda: setattr(cfg, "overlay_autohide_sec", hide.currentData()))
        rows.add("Hilang otomatis", "Subtitle memudar setelah diam.", hide)
        look.add(rows)
        look.body.addStretch(1)
        self.remote = Banner("Memakai remote desktop?", "", "Tampilkan di remote desktop")
        self.remote.button.clicked.connect(lambda: self.cap.setChecked(False))
        self.remote.hide()
        self.lay.addWidget(self.remote)
        self.lay.addLayout(grid2(prev, look, ratios=[115, 100]))
        self.lay.addStretch(1)
        self._font(fs.value())
        self._opacity(op.value())

    def on_show(self):
        self._check_remote()

    def _check_remote(self):
        apps = remote_desktop_apps() if self.cfg.hide_from_capture else []
        if apps:
            self.remote.set("Memakai remote desktop?",
                            "{} sedang berjalan. Selama \"Sembunyikan saat share screen\" aktif, subtitle tidak "
                            "terlihat dari layar remote (hanya di monitor PC ini).".format(" & ".join(apps)),
                            "Tampilkan di remote desktop")
        self.remote.setVisible(bool(apps))

    def _capture(self, v):
        self._set("hide_from_capture", v)
        self._check_remote()

    def _apply(self):
        self.preview.update()
        self.win.overlay.apply_style()
        self.win.overlay.apply_capture_exclusion()

    def _set(self, attr, v):
        setattr(self.cfg, attr, v)
        self._apply()

    def _enabled(self, v):
        self.cfg.overlay_enabled = v
        self.preview.update()
        if not v:
            self.win.overlay.hide()
        elif self.win.session.running:
            self.win.overlay.show()

    def _font(self, v):
        self.cfg.font_size = v
        self.fs_label.setText("Ukuran teks: {} px".format(v))
        self._apply()

    def _opacity(self, v):
        self.cfg.overlay_opacity = v / 100
        self.op_label.setText("Gelap latar: {}%".format(v))
        self._apply()

    def _position(self, key):
        self.cfg.overlay_position = key
        self.preview.custom_y = None
        self.preview.update()
        self.win.overlay.apply_position()

    def _dragged(self, rel_y):
        # Geser subtitle asli ke posisi relatif yang sama di layar.
        ov = self.win.overlay
        screen = ov.screen().availableGeometry()
        y = screen.y() + int(rel_y * screen.height())
        ov.move(ov.x(), min(y, screen.bottom() - ov.height()))
        self.cfg.overlay_position = "custom"
        ov.save_geometry()
        self.pos.set_value("custom")

    def overlay_moved(self):
        self.pos.set_value(self.cfg.overlay_position)
        g = self.cfg.overlay_geometry
        if len(g) == 4:
            screen = self.win.overlay.screen().availableGeometry()
            self.preview.custom_y = (g[1] - screen.y()) / max(screen.height(), 1)
            self.preview.update()


# ===================================================================== Riwayat
class HistItem(QPushButton):
    def __init__(self, sess):
        super().__init__()
        self.sess = sess
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 12, 14, 12)
        lay.setSpacing(2)
        t = label(sess.title)
        t.setStyleSheet("font-size: 13px; font-weight: 600; background: transparent;")
        dur = sess.duration_min
        sub = label("{} · {}".format(history.relative_day(sess.started), "{} mnt".format(dur) if dur else "< 1 mnt"), "small")
        sub.setStyleSheet("background: transparent;")
        tags = QHBoxLayout()
        tags.setSpacing(6)
        for text in (sess.pair, "{} kalimat".format(len(sess.lines))):
            tags.addWidget(tag(text))
        tags.addStretch(1)
        lay.addWidget(t)
        lay.addWidget(sub)
        lay.addSpacing(4)
        lay.addLayout(tags)
        for w in self.findChildren(QLabel):
            w.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setFixedHeight(lay.sizeHint().height())


class HistoryPage(Page):
    title, subtitle = "Riwayat", "Transkrip semua sesi tersimpan di PC ini."

    def __init__(self, win):
        super().__init__(win)
        card = QFrame()
        card.setObjectName("card")
        card.setMinimumHeight(520)
        h = QHBoxLayout(card)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(0)

        left = QFrame()
        left.setObjectName("histList")
        left.setFixedWidth(300)
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        ll.setSpacing(0)
        sb = QWidget()
        sl = QVBoxLayout(sb)
        sl.setContentsMargins(12, 12, 12, 12)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Cari di semua transkrip…")
        self.search.textChanged.connect(self.render_list)
        sl.addWidget(self.search)
        ll.addWidget(sb)
        ll.addWidget(separator())
        self.list_box = QVBoxLayout()
        self.list_box.setSpacing(0)
        ll.addLayout(self.list_box)
        ll.addStretch(1)
        h.addWidget(left)

        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(0)
        head = QFrame()
        head.setObjectName("histHead")
        hl = QHBoxLayout(head)
        hl.setContentsMargins(18, 14, 18, 14)
        self.v_title = label("", "histTitle")
        self.v_meta = label("", "small")
        hl.addLayout(vbox(self.v_title, self.v_meta, spacing=0), 1)
        copy = button("Salin", "btn", "copy")
        copy.clicked.connect(self._copy)
        export = button("Ekspor", "btn", "down")
        export.clicked.connect(self._export)
        folder = button("", "btnGhost", "folder", tooltip="Buka folder transkrip")
        folder.clicked.connect(self._open_folder)
        for b in (copy, export, folder):
            hl.addWidget(b)
        rl.addWidget(head)
        self.view = Feed("Belum ada sesi tersimpan. Transkrip muncul di sini setelah sesi pertama.", max_height=None,
                         margins=(10, 8, 14, 8))
        rl.addWidget(self.view, 1)
        h.addWidget(right, 1)
        self.lay.addWidget(card)
        self.lay.addStretch(1)
        self.sessions = []
        self.selected = None
        self.items = []

    def on_show(self):
        self.reload()

    def reload(self):
        self.sessions = history.sessions()
        if self.selected not in self.sessions:
            self.selected = self.sessions[0] if self.sessions else None
        self.render_list()

    def count(self):
        try:
            return len(history.sessions())
        except Exception:
            return 0

    def render_list(self, *_):
        q = self.search.text().strip().lower()
        for it in self.items:
            it.setParent(None)
            it.deleteLater()
        self.items = []
        for s in self.sessions:
            if q and q not in " ".join(l.original + " " + l.translation for l in s.lines).lower():
                continue
            it = HistItem(s)
            it.setChecked(s is self.selected)
            it.clicked.connect(lambda _=False, sess=s: self._select(sess))
            self.list_box.addWidget(it)
            self.items.append(it)
        self._render_view()

    def _select(self, sess):
        self.selected = sess
        for it in self.items:
            it.setChecked(it.sess is sess)
        self._render_view()

    def _render_view(self):
        self.view.clear()
        s = self.selected
        if s is None:
            self.v_title.setText("Belum ada sesi")
            self.v_meta.setText("")
            return
        dur = s.duration_min
        self.v_title.setText(s.title)
        self.v_meta.setText("{} · {} · {}".format(history.relative_day(s.started), "{} mnt".format(dur) if dur else "< 1 mnt", s.pair))
        for l in s.lines:
            self.view.add(MsgItem(l.direction, l.original, l.translation, l.time), scroll=False)

    def _copy(self):
        from PySide6.QtWidgets import QApplication

        if self.selected:
            QApplication.clipboard().setText(self.selected.text())
            self.win.toast("Transkrip disalin")

    def _export(self):
        if not self.selected:
            return
        default = os.path.splitext(self.selected.path)[0] + ".srt"
        path, _ = QFileDialog.getSaveFileName(self, "Ekspor subtitle", default, "Subtitle (*.srt);;Teks (*.txt)")
        if not path:
            return
        with open(path, "w", encoding="utf-8") as f:
            f.write(history.to_srt(self.selected) if path.lower().endswith(".srt") else self.selected.text())
        self.win.toast("Disimpan: " + os.path.basename(path))

    def _open_folder(self):
        from ..config import TRANSCRIPT_DIR

        os.makedirs(TRANSCRIPT_DIR, exist_ok=True)
        os.startfile(TRANSCRIPT_DIR)


# ===================================================================== Pengaturan
class GpuChip(QWidget):
    def __init__(self):
        super().__init__()
        self.setFixedSize(48, 48)
        self.text = "NV"
        self.ok = True

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        c = QColor("#76b900" if self.ok else Palette.c["faint"])
        bg = QColor(c)
        bg.setAlphaF(0.18)
        p.setPen(Qt.NoPen)
        p.setBrush(bg)
        p.drawRoundedRect(QRectF(0, 0, 48, 48), 12, 12)
        p.setPen(QColor("#5c9100") if self.ok else Palette.q("muted"))
        p.setFont(font(13, QFont.Black))
        p.drawText(QRectF(0, 0, 48, 48), Qt.AlignCenter, self.text)


class SettingsPage(Page):
    title, subtitle = "Pengaturan", "GPU, model, dan mesin terjemahan."
    ollama_result = Signal(bool, str)

    def __init__(self, win):
        super().__init__(win)
        cfg = self.cfg
        hw = Card()
        recheck = button("Periksa ulang", "btnGhost")
        recheck.clicked.connect(win.recheck_gpu)
        hw.header("Perangkat keras", None, recheck)
        self.chip = GpuChip()
        self.gpu_name = label("Memeriksa GPU…")
        self.gpu_name.setStyleSheet("font-weight: 600;")
        self.gpu_detail = label("", "small")
        self.driver_btn = button("Unduh driver NVIDIA", "btnWarn")
        self.driver_btn.clicked.connect(win.open_driver_page)
        self.driver_btn.hide()
        hw.add(hbox(self.chip, vbox(self.gpu_name, self.gpu_detail, spacing=2), "stretch", self.driver_btn, spacing=14))
        self.vram_txt = label("—", "small")
        self.vram = VramBar(10)
        legend = QHBoxLayout()
        legend.setSpacing(12)
        from .theme import VRAM_COLORS

        for color, text in zip(VRAM_COLORS, ("Windows", "Whisper", "TranslateGemma", "XTTS")):
            sw = QLabel()
            sw.setFixedSize(8, 8)
            sw.setStyleSheet("background: {}; border-radius: 2px;".format(color))
            legend.addWidget(sw)
            legend.addWidget(label(text, "small"))
            legend.addSpacing(4)
        legend.addStretch(1)
        hw.add(vbox(hbox(label("Pemakaian VRAM", "small"), "stretch", self.vram_txt), self.vram, legend, spacing=8))
        self.lay.addWidget(hw)

        wh = Card()
        wh.header("Pengenalan suara (Whisper)", "Model lebih besar lebih akurat, tapi lebih lambat & butuh VRAM.")
        mg = QHBoxLayout()
        mg.setSpacing(8)
        self.models = {}
        for name, size, acc, spd in WHISPER_MODELS:
            note = "disarankan" if name == "small" else ""
            if not self._model_installed(name):
                note = "unduh saat dipakai" if name != "small" else note
            card = ModelCard(name, size, acc, spd, note)
            card.setChecked(name == cfg.whisper_model)
            card.clicked.connect(lambda _=False, n=name: self._pick_model(n))
            mg.addWidget(card, 1)
            self.models[name] = card
        wh.add(mg)
        self.lay.addWidget(wh)

        eng = Card()
        eng.header("Mesin terjemahan")
        self.eng = Segmented([("builtin", "Bawaan (offline)"), ("ollama", "Ollama / VPS")], cfg.translator_backend)
        self.eng.changed.connect(self._engine)
        eng.add(hbox(self.eng, "stretch"))
        self.eng_local = label("TranslateGemma 4B (Q4_K_M) berjalan di PC ini lewat llama.cpp. Tidak ada data yang keluar "
                               "dari komputer.", "small", wrap=True)
        eng.add(self.eng_local)
        self.eng_ollama = QWidget()
        ol = QVBoxLayout(self.eng_ollama)
        ol.setContentsMargins(0, 0, 0, 0)
        ol.setSpacing(6)
        self.url = QLineEdit(cfg.ollama_url)
        self.url.textChanged.connect(lambda t: setattr(cfg, "ollama_url", t.strip() or "http://localhost:11434"))
        self.model = QLineEdit(cfg.ollama_model)
        self.model.textChanged.connect(lambda t: setattr(cfg, "ollama_model", t.strip() or "translategemma:4b"))
        test = button("Tes koneksi", "btn")
        test.clicked.connect(self._test_ollama)
        ol.addWidget(label("Alamat server", "fieldLabel"))
        ol.addWidget(self.url)
        ol.addSpacing(4)
        ol.addWidget(label("Model", "fieldLabel"))
        ol.addWidget(self.model)
        ol.addSpacing(4)
        ol.addLayout(hbox(test, "stretch"))
        eng.add(self.eng_ollama)
        eng.body.addStretch(1)
        self._engine(cfg.translator_backend)
        self.ollama_result.connect(lambda ok, msg: win.toast(msg))

        gen = Card()
        gen.header("Umum")
        rows = SettingRows()
        xtts = Switch(cfg.tts_device == "cuda")
        xtts.toggled.connect(lambda v: setattr(cfg, "tts_device", "cuda" if v else "cpu"))
        rows.add("XTTS di GPU", "Matikan untuk hemat VRAM (suara 4× lebih lambat).", xtts)
        tr = Switch(cfg.save_transcript)
        tr.toggled.connect(lambda v: setattr(cfg, "save_transcript", v))
        rows.add("Simpan transkrip", "%APPDATA%\\AI Translator\\transcripts", tr)
        auto = Switch(cfg.autostart)
        auto.toggled.connect(win.set_autostart)
        rows.add("Mulai bersama Windows", "Diminimalkan ke system tray.", auto)
        self.theme = Segmented([("light", "Terang"), ("auto", "Otomatis"), ("dark", "Gelap")], cfg.theme)
        self.theme.changed.connect(win.set_theme)
        rows.add("Tema", None, self.theme)
        gen.add(rows)
        gen.body.addStretch(1)
        self.lay.addLayout(grid2(eng, gen))
        self.lay.addStretch(1)

    @staticmethod
    def _model_installed(name):
        from ..config import MODELS_DIR

        return os.path.isfile(os.path.join(MODELS_DIR, "whisper", "faster-whisper-" + name, "model.bin"))

    def _pick_model(self, name):
        for n, c in self.models.items():
            c.setChecked(n == name)
        self.cfg.whisper_model = name
        extra = "" if self._model_installed(name) else " (diunduh saat sesi dimulai, perlu internet)"
        self.win.toast("Whisper {} dipakai di sesi berikutnya{}".format(name, extra))

    def _engine(self, key):
        self.cfg.translator_backend = key
        self.eng_local.setVisible(key == "builtin")
        self.eng_ollama.setVisible(key == "ollama")

    def _test_ollama(self):
        from ..translator import OllamaTranslator

        url, model = self.cfg.ollama_url, self.cfg.ollama_model
        self.win.toast("Menghubungi {}…".format(url))

        def work():
            try:
                OllamaTranslator(url, model).check()
                self.ollama_result.emit(True, "Terhubung · {} tersedia".format(model))
            except Exception as e:
                self.ollama_result.emit(False, str(e))

        threading.Thread(target=work, daemon=True).start()

    def set_gpu(self, info):
        state = info.status
        self.chip.ok = state in ("ok", "old")
        self.chip.text = "NV" if state != "none" else "CPU"
        self.chip.update()
        self.gpu_name.setText(info.name if state != "none" else "Tanpa GPU NVIDIA")
        if state == "ok":
            d = "{:.0f} GB VRAM · driver {} · CUDA 12.4 siap".format(info.vram_mb / 1024, info.driver) if info.vram_mb else "driver {}".format(info.driver)
        elif state == "old":
            d = "driver {} · perlu diperbarui (minimum {}.{})".format(info.driver, *gpu_check.MIN_DRIVER)
        elif state == "missing":
            d = "driver NVIDIA belum terpasang · mode CPU"
        else:
            d = "Mode CPU · subtitle tertunda ±5 detik"
        self.gpu_detail.setText(d)
        self.driver_btn.setVisible(state in ("old", "missing"))

    def set_vram(self, parts, total):
        self.vram.set_parts(parts, total)
        self.vram_txt.setText("{} / {} GB".format("{:.1f}".format(sum(parts)).replace(".", ","),
                                                  "{:.1f}".format(total).replace(".", ",")))


# ===================================================================== Tentang
class LicRow(QWidget):
    def __init__(self, name, desc, tag_text, nc=False):
        super().__init__()
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 12, 0, 12)
        lay.addLayout(vbox(label(name, "rowTitle"), label(desc, "rowSub", wrap=True), spacing=1), 1)
        lay.addWidget(tag(tag_text, nc), 0, Qt.AlignVCenter)


class AboutPage(Page):
    title, subtitle = "Tentang", "Versi, lisensi, dan komponen."
    selftest_done = Signal(str)

    def __init__(self, win):
        super().__init__(win)
        from PySide6.QtGui import QPixmap

        from .theme import ASSETS

        app = Card()
        logo = QLabel()
        pm = QPixmap(os.path.join(ASSETS, "icon.png"))
        pm.setDevicePixelRatio(pm.width() / 56)
        logo.setPixmap(pm)
        logo.setFixedSize(56, 56)
        name = label("AI Translator")
        name.setStyleSheet("font-size: 17px; font-weight: 700;")
        app.add(hbox(logo, vbox(name, label("Versi {} · offline · Windows 10/11".format(win.VERSION), "small"), spacing=2), "stretch", spacing=14))
        app.add(label("Penerjemah suara real-time dua arah. Semua proses berjalan di PC Anda; audio tidak dikirim ke internet.",
                      "small", wrap=True))
        log = button("Buka log", "btn")
        log.clicked.connect(win.open_log)
        self.selftest = button("Jalankan selftest", "btn")
        self.selftest.clicked.connect(self._selftest)
        wiz = button("Panduan awal", "btnGhost")
        wiz.clicked.connect(win.open_wizard)
        app.add(hbox(log, self.selftest, wiz, "stretch"))
        app.body.addStretch(1)

        vb = Card()
        vb.header("VB-CABLE")
        vb.add(label("Virtual mic disediakan oleh <b>VB-CABLE</b> buatan VB-Audio Software (V. Burel). VB-CABLE adalah "
                     "<i>donationware</i> — jika bermanfaat, dukung pembuatnya.", "small", wrap=True, rich=True))
        donate = button("♥ Dukung VB-Audio", "btn")
        donate.clicked.connect(lambda: __import__("webbrowser").open("https://vb-audio.com/Cable/"))
        vb.add(hbox(donate, "stretch"))
        vb.body.addStretch(1)
        self.lay.addLayout(grid2(app, vb))

        lic = Card(spacing=0)
        lic.header("Komponen & lisensi")
        lic.body.addSpacing(14)
        rows = [
            ("TranslateGemma 4B", "Google DeepMind · model terjemahan", "Gemma Terms", False),
            ("XTTS-v2", "Coqui · peniru suara — hanya untuk penggunaan non-komersial", "CPML · non-komersial", True),
            ("Whisper small (faster-whisper)", "OpenAI · SYSTRAN · pengenal suara", "MIT", False),
            ("llama.cpp", "ggml-org · mesin inferensi", "MIT", False),
            ("VB-CABLE", "VB-Audio Software · virtual audio", "Donationware", False),
            ("PySide6 · PyTorch · CUDA · Inter", "Qt · Meta · NVIDIA · Rasmus Andersson", "LGPL · BSD · EULA · OFL", False),
        ]
        for i, r in enumerate(rows):
            if i:
                lic.add(separator())
            w = LicRow(*r)
            if i == 0:
                w.layout().setContentsMargins(0, 0, 0, 12)
            lic.add(w)
        self.lay.addWidget(lic)
        self.lay.addStretch(1)
        self.selftest_done.connect(self._selftest_done)

    def _selftest(self):
        import subprocess
        import sys

        if self.win.session.running:
            self.win.toast("Hentikan sesi dulu sebelum menjalankan selftest")
            return
        self.selftest.setEnabled(False)
        self.selftest.setText("Selftest berjalan…")
        if getattr(sys, "frozen", False):
            cmd = [sys.executable, "--selftest"]
        else:
            main = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "main.py")
            cmd = [sys.executable, main, "--selftest"]
        from ..config import DATA_DIR

        log = os.path.join(DATA_DIR, "app.log")
        start = os.path.getsize(log) if os.path.exists(log) else 0

        def work():
            try:
                subprocess.run(cmd, timeout=600, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                with open(log, encoding="utf-8", errors="replace") as f:
                    f.seek(start)
                    out = f.read()
                ok = "[selftest] SELESAI" in out
                self.selftest_done.emit("Selftest: semua model OK" if ok else "Selftest gagal — lihat app.log")
            except Exception as e:
                self.selftest_done.emit("Selftest gagal: {}".format(e))

        threading.Thread(target=work, daemon=True).start()

    def _selftest_done(self, msg):
        self.selftest.setEnabled(True)
        self.selftest.setText("Jalankan selftest")
        self.win.toast(msg, 4000)
