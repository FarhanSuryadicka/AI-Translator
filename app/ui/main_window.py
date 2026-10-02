"""Jendela utama (desain: mockup/ui-mockup-v2.html)."""

import os
import shutil
import subprocess
import threading
import time

from PySide6.QtCore import QObject, QSize, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QIcon, QPixmap
from PySide6.QtWidgets import (
    QApplication, QFrame, QHBoxLayout, QLabel, QMainWindow, QMenu, QMessageBox, QScrollArea, QStackedWidget,
    QSystemTrayIcon, QVBoxLayout, QWidget,
)

from .. import audio_setup, autostart, gpu_check
from ..config import BUILTIN_MT_MODEL, DATA_DIR, MODELS_DIR
from ..pipeline import LISTEN, Session
from . import icons, theme
from .overlay import SubtitleOverlay
from .pages import AboutPage, HistoryPage, HomePage, ListenPage, SettingsPage, SpeakPage, SubtitlePage, short_device
from .theme import ASSETS, Palette
from .widgets import Banner, Dot, MsgItem, NavButton, Toast, VramBar, button, label, theme_bus, vbox
from .wizard import Wizard

LICENSE_TEXT = (
    "XTTS-v2 memakai lisensi Coqui Public Model License (CPML):\n"
    "hanya untuk penggunaan NON-KOMERSIAL.\n"
    "https://coqui.ai/cpml\n\n"
    "Apakah Anda setuju dengan lisensi tersebut?"
)
# Perkiraan porsi VRAM tiap model (GB) untuk membagi pemakaian total di bar VRAM.
VRAM_SHARE = {"whisper": 0.9, "gemma": 2.6, "xtts": 1.2}


class _Bridge(QObject):
    """Meneruskan callback dari thread pekerja ke thread UI dengan aman."""

    result = Signal(object)
    status = Signal(str)
    toast = Signal(str)
    call = Signal(object)
    gpu = Signal(object)
    vram = Signal(object)
    mic = Signal()


class Binder:
    """Menyamakan beberapa widget yang mewakili satu pengaturan (mis. bahasa di Beranda & di Dengar)."""

    def __init__(self, cfg):
        self.cfg = cfg
        self.widgets = {}
        self.hooks = {}

    def combo(self, attr, combo):
        self.widgets.setdefault(attr, []).append(combo)
        self._put(combo, getattr(self.cfg, attr))
        combo.currentIndexChanged.connect(lambda _=0: self.set(attr, combo.currentData()))

    def switch(self, attr, sw):
        self.widgets.setdefault(attr, []).append(sw)
        self._put(sw, getattr(self.cfg, attr))
        sw.toggled.connect(lambda v: self.set(attr, v))

    def on(self, attr, fn):
        self.hooks.setdefault(attr, []).append(fn)

    def set(self, attr, value):
        setattr(self.cfg, attr, value)
        for w in self.widgets.get(attr, []):
            self._put(w, value)
        for fn in self.hooks.get(attr, []):
            fn(value)

    @staticmethod
    def _put(w, value):
        w.blockSignals(True)
        if hasattr(w, "findData"):
            idx = w.findData(value)
            if idx >= 0:
                w.setCurrentIndex(idx)
        else:
            w.setChecked(bool(value))
            if hasattr(w, "set_knob"):
                w.set_knob(1.0 if value else 0.0)
        w.blockSignals(False)
        w.update()


class MainWindow(QMainWindow):
    VERSION = "1.1.0"

    def __init__(self, cfg, start_in_tray=False):
        super().__init__()
        self.cfg = cfg
        self.setWindowTitle("AI Translator")
        self.resize(1240, 820)
        self.setMinimumSize(1000, 680)

        theme.load_fonts()
        Palette.set(theme.resolve_dark(cfg.theme))
        QApplication.instance().setStyleSheet(theme.stylesheet())

        self.bridge = _Bridge()
        self.bridge.result.connect(self._on_result)
        self.bridge.status.connect(self._on_status)
        self.bridge.toast.connect(self.toast)
        self.bridge.call.connect(lambda fn: fn())
        self.bridge.gpu.connect(self._on_gpu)
        self.bridge.vram.connect(self._on_vram)
        self.bridge.mic.connect(self.refresh_status)
        self.session = Session(cfg, self.bridge.result.emit, self.bridge.status.emit, self._level_from_thread)
        self.overlay = SubtitleOverlay(cfg)
        self.binder = Binder(cfg)

        self.state = "idle"  # idle | loading | running
        self.gpu = None
        self.mic_state = "none"
        self.vram_base = None
        self.loaded = set()
        self._levels = {}
        self._count = 0
        self._lat = 0
        self._t0 = None
        self._speak_off = False
        self._live = {}  # seq kalimat langsung -> baris transkrip [Beranda, Dengar]
        self._last_tr = ""  # terjemahan terakhir yang ditampilkan di subtitle

        self._build()
        self.overlay.moved.connect(self.pages["subtitle"].overlay_moved)
        self.toaster = Toast(self.centralWidget())
        self.wizard = Wizard(self, self.centralWidget())
        self.wizard.finished.connect(self.refresh_status)

        self._clock = QTimer(self)
        self._clock.timeout.connect(self._tick)
        self._vram_timer = QTimer(self)
        self._vram_timer.timeout.connect(self._poll_vram)
        self._vram_timer.start(2500)
        self._level_timer = QTimer(self)
        self._level_timer.timeout.connect(self._show_levels)
        self._level_timer.start(120)

        self._tray()
        self.go("home")
        self.refresh_status()
        threading.Thread(target=lambda: self.bridge.gpu.emit(gpu_check.get()), daemon=True).start()
        self._poll_vram()
        if not start_in_tray:
            self.show()
            theme.set_titlebar_dark(self, Palette.dark)
            if not cfg.onboarding_done:
                QTimer.singleShot(300, self.open_wizard)

    # ================================================================ tata letak
    def _build(self):
        root = QWidget()
        root.setObjectName("root")
        h = QHBoxLayout(root)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(0)
        h.addWidget(self._sidebar())

        main = QWidget()
        mv = QVBoxLayout(main)
        mv.setContentsMargins(0, 0, 0, 0)
        mv.setSpacing(0)
        mv.addWidget(self._topbar())

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        content = QWidget()
        content.setObjectName("content")
        cv = QVBoxLayout(content)
        cv.setContentsMargins(24, 20, 24, 28)
        cv.setSpacing(16)
        self.gpu_banner = Banner("", "", "Unduh driver NVIDIA")
        self.gpu_banner.button.clicked.connect(self.open_driver_page)
        self.gpu_banner.hide()
        cv.addWidget(self.gpu_banner)
        self.stack = QStackedWidget()
        self.pages = {"home": None, "listen": None, "speak": None}
        # Urutan pembuatan: Bicara & Dengar dulu karena Beranda memakai data mereka (rute, mic).
        self.pages["speak"] = SpeakPage(self)
        self.pages["listen"] = ListenPage(self)
        self.pages["home"] = HomePage(self)
        self.pages["subtitle"] = SubtitlePage(self)
        self.pages["history"] = HistoryPage(self)
        self.pages["settings"] = SettingsPage(self)
        self.pages["about"] = AboutPage(self)
        for key in ("home", "listen", "speak", "subtitle", "history", "settings", "about"):
            self.stack.addWidget(self.pages[key])
        cv.addWidget(self.stack)
        cv.addStretch(1)
        scroll.setWidget(content)
        self.scroll = scroll
        mv.addWidget(scroll, 1)
        h.addWidget(main, 1)
        self.setCentralWidget(root)
        self.update_routes()

    def _sidebar(self):
        side = QFrame()
        side.setObjectName("side")
        side.setFixedWidth(236)
        v = QVBoxLayout(side)
        v.setContentsMargins(12, 14, 12, 14)
        v.setSpacing(2)

        logo = QLabel()
        pm = QPixmap(os.path.join(ASSETS, "icon.png"))
        pm.setDevicePixelRatio(pm.width() / 36)
        logo.setPixmap(pm)
        logo.setFixedSize(36, 36)
        brand = QHBoxLayout()
        brand.setContentsMargins(8, 4, 8, 14)
        brand.setSpacing(10)
        brand.addWidget(logo)
        brand.addLayout(vbox(label("AI Translator", "brandName"), label("Offline · v" + self.VERSION[:3], "brandSub"), spacing=0))
        brand.addStretch(1)
        v.addLayout(brand)

        self.nav = {}

        def nav(key, icon_name, text):
            b = NavButton(icon_name, text)
            b.clicked.connect(lambda: self.go(key))
            self.nav[key] = b
            v.addWidget(b)

        nav("home", "home", "Beranda")
        v.addWidget(label("TERJEMAHAN", "navLabel"))
        nav("listen", "ear", "Dengar")
        nav("speak", "mic", "Bicara")
        nav("subtitle", "cc", "Subtitle")
        nav("history", "hist", "Riwayat")
        v.addWidget(label("SISTEM", "navLabel"))
        nav("settings", "gear", "Pengaturan")
        nav("about", "info", "Tentang")
        v.addStretch(1)

        health = QFrame()
        health.setObjectName("health")
        hv = QVBoxLayout(health)
        hv.setContentsMargins(12, 12, 12, 12)
        hv.setSpacing(8)
        self.h_rows = {}
        for key, text in (("gpu", "GPU"), ("mic", "Virtual mic"), ("model", "Model")):
            dot = Dot("ok")
            val = label("", "healthVal")
            row = QHBoxLayout()
            row.setSpacing(4)
            row.addWidget(dot)
            row.addWidget(label(text))
            row.addStretch(1)
            row.addWidget(val)
            hv.addLayout(row)
            self.h_rows[key] = (dot, val)
        self.h_vram = label("—", "healthVal")
        vr = QHBoxLayout()
        vr.addWidget(label("VRAM"))
        vr.addStretch(1)
        vr.addWidget(self.h_vram)
        hv.addLayout(vr)
        self.h_bar = VramBar(6)
        hv.addWidget(self.h_bar)
        v.addWidget(health)
        return side

    def _topbar(self):
        top = QFrame()
        top.setObjectName("topbar")
        h = QHBoxLayout(top)
        h.setContentsMargins(24, 14, 24, 14)
        h.setSpacing(10)
        self.p_title = label("", "pageTitle")
        self.p_sub = label("", "pageSub")
        h.addLayout(vbox(self.p_title, self.p_sub, spacing=0), 1)

        pill = QFrame()
        pill.setObjectName("sessPill")
        pl = QHBoxLayout(pill)
        pl.setContentsMargins(8, 4, 12, 4)
        pl.setSpacing(4)
        self.sess_dot = Dot("none")
        self.sess_txt = label("Siap")
        pl.addWidget(self.sess_dot)
        pl.addWidget(self.sess_txt)
        self.sess_pill = pill
        h.addWidget(pill)

        self.start_btn = button("Mulai sesi", "btnPrimary", "play")
        self.start_btn.setMinimumHeight(36)
        self.start_btn.clicked.connect(self.toggle_session)
        h.addWidget(self.start_btn)

        self.theme_btn = button("", "iconBtn", "moon", tooltip="Ganti tema")
        self.theme_btn.setFixedSize(34, 34)
        self.theme_btn.setIconSize(QSize(16, 16))
        self.theme_btn.clicked.connect(lambda: self.set_theme("light" if Palette.dark else "dark"))
        h.addWidget(self.theme_btn)
        return top

    def _tray(self):
        self.tray = QSystemTrayIcon(QIcon(os.path.join(ASSETS, "icon.ico")), self)
        self.tray.setToolTip("AI Translator")
        menu = QMenu()
        menu.addAction("Buka AI Translator", self._show_from_tray)
        self.tray_toggle = menu.addAction("Mulai sesi", self.toggle_session)
        menu.addSeparator()
        menu.addAction("Keluar", self.close)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(lambda r: self._show_from_tray() if r == QSystemTrayIcon.Trigger else None)
        self.tray.show()

    def _show_from_tray(self):
        self.showNormal()
        self.raise_()
        self.activateWindow()
        theme.set_titlebar_dark(self, Palette.dark)
        if not self.cfg.onboarding_done:
            self.open_wizard()

    # ================================================================ navigasi & umum
    def go(self, key):
        page = self.pages[key]
        for k, b in self.nav.items():
            b.setChecked(k == key)
        self.stack.setCurrentWidget(page)
        self.p_title.setText(page.title)
        self.p_sub.setText(page.subtitle)
        self.scroll.verticalScrollBar().setValue(0)
        page.on_show()

    def toast(self, msg, ms=2400):
        self.toaster.show_message(msg, ms)

    def open_wizard(self, step=0):
        self.wizard.open(step)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if self.wizard.isVisible():
            self.wizard.setGeometry(self.centralWidget().rect())

    def set_theme(self, key):
        self.cfg.theme = key
        Palette.set(theme.resolve_dark(key))
        QApplication.instance().setStyleSheet(theme.stylesheet())
        theme_bus.changed.emit()
        theme.set_titlebar_dark(self, Palette.dark)
        self.pages["settings"].theme.set_value(key)
        for w in self.findChildren(QWidget):
            w.update()

    def set_autostart(self, on):
        try:
            autostart.set_enabled(on)
            self.cfg.autostart = on
            self.toast("AI Translator akan dibuka saat Windows mulai" if on else "Mulai bersama Windows dimatikan")
        except OSError as e:
            self.toast("Gagal mengubah autostart: {}".format(e))

    def open_driver_page(self):
        QDesktopServices.openUrl(QUrl(gpu_check.DRIVER_URL))
        self.toast("Membuka halaman driver NVIDIA")

    def open_log(self):
        path = os.path.join(DATA_DIR, "app.log")
        if os.path.exists(path):
            os.startfile(path)
        else:
            self.toast("Belum ada app.log")

    def recheck_gpu(self):
        gpu_check._cached = None
        self.toast("Memeriksa GPU…")
        threading.Thread(target=lambda: self.bridge.gpu.emit(gpu_check.get()), daemon=True).start()

    # ================================================================ status sistem
    def vmic_name(self):
        if self.mic_state == "ok":
            return audio_setup.MIC_NAME
        if self.mic_state == "raw":
            return "CABLE Output"
        return "—"

    def _models_installed(self):
        whisper = os.path.isfile(os.path.join(MODELS_DIR, "whisper", "faster-whisper-" + self.cfg.whisper_model, "model.bin"))
        tts = os.path.isdir(os.path.join(MODELS_DIR, "tts"))
        return [os.path.exists(BUILTIN_MT_MODEL), whisper, tts]

    def refresh_status(self):
        try:
            if not audio_setup.is_installed():
                self.mic_state = "none"
            else:
                self.mic_state = "ok" if audio_setup.is_configured() else "raw"
        except OSError:
            self.mic_state = "none"
        home, speak = self.pages["home"], self.pages["speak"]

        text = {"ok": audio_setup.mic_name() or audio_setup.MIC_NAME,
                "raw": "CABLE Output (VB-Audio Virtual Cable) — belum dirapikan",
                "none": "Belum terpasang — fitur Bicara tidak bisa dipakai"}[self.mic_state]
        st = {"ok": "ok", "raw": "warn", "none": "bad"}[self.mic_state]
        home.c_mic.set(st, sub=text)
        home.fix_btn.setVisible(self.mic_state != "ok")
        home.fix_btn.setText("Pasang" if self.mic_state == "none" else "Rapikan")
        dot, val = self.h_rows["mic"]
        dot.set_state(st)
        val.setText({"ok": "Siap", "raw": "Rapikan", "none": "Tidak ada"}[self.mic_state])
        if self.mic_state == "ok":
            speak.banner.hide()
        else:
            speak.banner.show()
            if self.mic_state == "none":
                speak.banner.set("Virtual mic belum terpasang",
                                 "Pasang VB-CABLE (sekali, butuh restart) agar suara terjemahan bisa masuk ke Zoom/Meet.",
                                 "Pasang VB-CABLE")
            else:
                speak.banner.set("Virtual mic belum dirapikan",
                                 "Masih bernama \"CABLE Output\" dan ada perangkat \"CABLE In 16ch\" yang tidak dipakai.",
                                 "Rapikan (izin admin)")
        self.nav["speak"].set_badge("" if self.mic_state == "ok" else "1", warn=True)

        if speak.voice_ok:
            home.c_voice.set("ok", sub=speak.voice_info.text())
        else:
            home.c_voice.set("warn", sub="Belum ada — rekam 15 detik untuk fitur Bicara")

        have = self._models_installed()
        dot, val = self.h_rows["model"]
        dot.set_state("ok" if all(have) else "warn")
        val.setText("{}/3 terpasang".format(sum(have)))
        home.c_models.set("ok" if all(have) else "warn",
                          sub="Whisper {} · TranslateGemma 4B · XTTS-v2".format(self.cfg.whisper_model))

        self.nav["history"].set_badge(self.pages["history"].count() or "")
        self.update_routes()
        speak.refresh_guide()
        self._ready_hint()

    def _ready_hint(self):
        issues = int(self.gpu is not None and self.gpu.status != "ok") + int(self.mic_state != "ok")
        self.pages["home"].ready_hint.setText("{} perlu perhatian".format(issues) if issues else "Semua siap")

    def _on_gpu(self, info):
        self.gpu = info
        home, settings = self.pages["home"], self.pages["settings"]
        settings.set_gpu(info)
        dot, val = self.h_rows["gpu"]
        if info.status == "ok":
            home.c_gpu.set("ok", "GPU " + info.name, "{:.0f} GB · driver {} · CUDA siap".format(info.vram_mb / 1024, info.driver)
                           if info.vram_mb else "driver {}".format(info.driver))
            dot.set_state("ok")
            val.setText(info.name.replace("NVIDIA GeForce ", "").replace("NVIDIA ", ""))
            self.gpu_banner.hide()
        else:
            titles = {"old": "Driver NVIDIA terlalu lama ({})".format(info.driver),
                      "missing": "Driver NVIDIA belum terpasang", "none": "Tidak ada GPU NVIDIA"}
            texts = {"old": "Disarankan {}.{} atau lebih baru. Tanpa pembaruan, aplikasi bisa jalan di CPU dan lambat.".format(*gpu_check.MIN_DRIVER),
                     "missing": "{} terdeteksi. Pasang drivernya agar model berjalan di GPU.".format(info.name or "GPU NVIDIA"),
                     "none": "Aplikasi jalan di CPU: subtitle tertunda ±5 detik, fitur Bicara tidak disarankan."}
            self.gpu_banner.set(titles[info.status], texts[info.status],
                                "Unduh driver NVIDIA" if info.status in ("old", "missing") else None)
            self.gpu_banner.show()
            home.c_gpu.set("bad" if info.status == "none" else "warn",
                           "Tanpa GPU NVIDIA" if info.status == "none" else "GPU " + info.name, texts[info.status])
            dot.set_state("bad" if info.status == "none" else "warn")
            val.setText({"old": "Driver lama", "missing": "Tanpa driver", "none": "CPU"}[info.status])
        self.nav["settings"].set_badge("" if info.status == "ok" else "!", warn=True)
        self._ready_hint()

    def update_routes(self):
        if any(self.pages.get(k) is None for k in ("home", "listen", "speak")):
            return
        speak = self.pages["speak"]
        self.pages["home"].set_routes(self.pages["listen"].source_title(), speak.mic_title(), self.vmic_name())
        speak.stages[0].sub.setText(short_device(self.cfg.mic_device) or "Mic default")
        speak.stages[4].sub.setText(self.vmic_name())

    def fix_virtual_mic(self):
        if self.mic_state == "none":
            QDesktopServices.openUrl(QUrl("https://vb-audio.com/Cable/"))
            self.toast("Pasang VB-CABLE, restart PC, lalu buka aplikasi ini lagi", 5000)
            return
        self.toast("Meminta izin admin untuk merapikan VB-CABLE…")

        def work():
            if audio_setup.is_admin():
                audio_setup.configure()
                ok = True
            else:
                ok = audio_setup.configure_elevated()
            self.bridge.mic.emit()
            done = ok and audio_setup.is_configured()
            self.bridge.toast.emit("Perangkat dirapikan: " + audio_setup.MIC_NAME if done
                                   else "Izin admin ditolak atau gagal — lihat app.log")

        threading.Thread(target=work, daemon=True).start()

    # ================================================================ VRAM
    def _poll_vram(self):
        def work():
            exe = shutil.which("nvidia-smi") or os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "nvidia-smi.exe")
            if not os.path.exists(exe):
                return
            try:
                out = subprocess.run([exe, "--query-gpu=memory.used,memory.total", "--format=csv,noheader,nounits"],
                                     capture_output=True, text=True, timeout=5,
                                     creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout.split(",")
                self.bridge.vram.emit((float(out[0]) / 1024, float(out[1]) / 1024))
            except (OSError, ValueError, IndexError, subprocess.SubprocessError):
                pass

        threading.Thread(target=work, daemon=True).start()

    def _on_vram(self, data):
        used, total = data
        if self.state == "idle" or self.vram_base is None:
            self.vram_base = used
        base = min(self.vram_base, used)
        extra = max(used - base, 0)
        names = [n for n in ("whisper", "gemma", "xtts") if n in self.loaded]
        weight = sum(VRAM_SHARE[n] for n in names)
        parts = [base] + [extra * VRAM_SHARE[n] / weight if n in names and weight else 0 for n in ("whisper", "gemma", "xtts")]
        self.h_bar.set_parts(parts, total)
        self.h_vram.setText("{} / {} GB".format("{:.1f}".format(used).replace(".", ","), "{:.1f}".format(total).replace(".", ",")))
        self.pages["settings"].set_vram(parts, total)

    # ================================================================ sesi
    def toggle_session(self):
        if self.state != "idle":
            self.start_btn.setEnabled(False)
            self.sess_txt.setText("Menghentikan…")
            self.session.stop()
            return
        cfg = self.cfg
        if not cfg.listen_enabled and not cfg.speak_enabled:
            self.toast("Aktifkan minimal satu arah: Dengar atau Bicara")
            return
        self._speak_off = False
        if cfg.speak_enabled:
            if self.mic_state == "none":
                if not cfg.listen_enabled:
                    self.toast("Virtual mic belum terpasang — fitur Bicara tidak bisa dipakai", 4000)
                    return
                self.toast("Virtual mic belum terpasang — fitur Bicara dimatikan untuk sesi ini", 4000)
                self._speak_off = True
            elif not self.pages["speak"].voice_ok:
                self.toast("Rekam sampel suara dulu untuk fitur Bicara", 4000)
                self.go("speak")
                return
            elif not self._ensure_license():
                return
        cfg.save()
        self.loaded = set()
        self._count, self._lat = 0, 0
        home = self.pages["home"]
        home.st_count.setText("0")
        home.st_lat.setText("—")
        home.st_time.setText("00:00")
        home.feed.clear()
        self.pages["listen"].feed.clear()
        self._live = {}
        self._set_state("loading")
        self.sess_txt.setText("Memuat model…")
        # Bicara dimatikan sementara: Session membaca cfg saat _setup() di thread-nya sendiri.
        self.session.cfg = cfg if not self._speak_off else _without_speak(cfg)
        self.session.start()

    def _ensure_license(self):
        if self.cfg.xtts_license_agreed:
            return True
        if QMessageBox.question(self, "Lisensi XTTS-v2", LICENSE_TEXT) == QMessageBox.Yes:
            self.cfg.xtts_license_agreed = True
            return True
        return False

    def _set_state(self, state):
        self.state = state
        self.start_btn.setEnabled(True)
        running = state != "idle"
        self.start_btn.setObjectName("btnStop" if running else "btnPrimary")
        self.start_btn.setText("Berhenti" if running else "Mulai sesi")
        self.start_btn.icon_name = "stop" if running else "play"
        self.start_btn.setIcon(icons.icon(self.start_btn.icon_name, "#ffffff", 15))
        self.tray_toggle.setText("Berhenti" if running else "Mulai sesi")
        self.sess_pill.setProperty("running", "true" if state == "running" else "false")
        # objectName/properti berubah -> QSS harus diterapkan ulang.
        for w in (self.start_btn, self.sess_pill, self.sess_txt):
            w.style().unpolish(w)
            w.style().polish(w)
        if state == "loading":
            self.sess_dot.set_state("warn", pulse=True)
        elif state == "running":
            self.sess_dot.set_state("ok", pulse=True)
            self._t0 = time.monotonic()
            self._tick()
            self._clock.start(500)
        else:
            self.sess_dot.set_state("none")
            self._clock.stop()
            for key in ("listen", "speak"):
                self.nav[key].set_live(False)
            for m in self._meters():
                m.set_db(None)
            self._levels = {}
            self.loaded = set()
        self.sync_playing()

    def _meters(self):
        home = self.pages["home"]
        return [home.listen_meter, home.speak_meter, self.pages["listen"].meter, self.pages["speak"].meter]

    def sync_playing(self):
        self.pages["listen"].set_playing(self.state == "running" and self.cfg.listen_enabled)

    def _tick(self):
        if self._t0 is None:
            return
        s = int(time.monotonic() - self._t0)
        t = "{:02d}:{:02d}".format(s // 60, s % 60)
        self.sess_txt.setText("Berjalan · " + t)
        self.pages["home"].st_time.setText(t)

    def _on_status(self, msg):
        if msg == "STOPPED":
            was = self.state
            self._set_state("idle")
            if self.sess_txt.text() != "Error":
                self.sess_txt.setText("Berhenti")
            self.session.cfg = self.cfg
            if was != "idle":
                self.pages["history"].reload()
                self.nav["history"].set_badge(self.pages["history"].count() or "")
            return
        if msg.startswith("ERROR"):
            self.sess_txt.setText("Error")
            QMessageBox.warning(self, "AI Translator", msg[len("ERROR: "):])
            return
        if msg == "RUNNING":
            speak_on = self.cfg.speak_enabled and not self._speak_off
            self._set_state("running")
            self.nav["listen"].set_live(self.cfg.listen_enabled)
            self.nav["speak"].set_live(speak_on)
            self.loaded.update(["whisper", "gemma"] + (["xtts"] if speak_on else []))
            if self.cfg.listen_enabled and self.cfg.overlay_enabled:
                self.overlay.show()
            return
        if self.state == "loading":
            for key, word in (("gemma", "TranslateGemma"), ("whisper", "Whisper"), ("xtts", "XTTS")):
                if word in msg:
                    self.loaded.add(key)
            self.sess_txt.setText(msg.split(" (")[0].strip())
        elif self.state == "running" and not msg.startswith(("Dengar:", "Bicara:")):
            self.toast(msg, 4000)

    def _level_from_thread(self, direction, db):
        self._levels[direction] = db  # dibaca timer UI (_show_levels); tidak menyentuh widget dari thread lain

    def _show_levels(self):
        if self.state != "running":
            return
        home = self.pages["home"]
        for direction, meters in ((LISTEN, (home.listen_meter, self.pages["listen"].meter)),
                                  ("speak", (home.speak_meter, self.pages["speak"].meter))):
            db = self._levels.get(direction)
            for m in meters:
                m.set_db(db)

    def _on_result(self, r):
        direction = "in" if r.direction == LISTEN else "out"
        if direction == "in" and (r.partial or r.seq in self._live):
            self._on_live(r)
            if r.partial:
                return
        meta = ("<span style='color:{m}; font-weight:600'>{lang}</span>&nbsp;&nbsp;"
                "<span style='color:{f}'>suara→teks {a} ms · terjemah {b} ms</span>").format(
            m=Palette.c["muted"], f=Palette.c["faint"], lang=r.language.upper(), a=r.asr_ms, b=r.mt_ms)
        stamp = time.strftime("%H:%M:%S")
        home = self.pages["home"]
        if direction == "in" and r.seq in self._live:
            # Kalimat langsung selesai: baris sementara menjadi final.
            for item in self._live.pop(r.seq):
                item.update_text(r.original, r.translation, meta)
        elif direction == "in":
            home.feed.add(MsgItem(direction, r.original, r.translation, stamp, meta))
            self.pages["listen"].feed.add(MsgItem(direction, r.original, r.translation, stamp, meta))
        else:
            home.feed.add(MsgItem(direction, r.original, r.translation, stamp, meta))
        if direction == "in":
            self._last_tr = r.translation
            if not self._live:  # kalimat berikutnya belum mulai -> tampilkan versi final
                self.overlay.set_text(r.original, r.translation)
                self.pages["subtitle"].preview.set_text(r.original, r.translation)
        else:
            self.pages["speak"].set_timings(r.asr_ms, r.mt_ms)
            self.pages["speak"].animate()
        self._count += 1
        self._lat += r.asr_ms + r.mt_ms
        home.st_count.setText(str(self._count))
        home.st_lat.setText("{} dtk".format("{:.1f}".format(self._lat / self._count / 1000).replace(".", ",")))

    def _on_live(self, r):
        """Teks sementara: perbarui baris transkrip yang sama + subtitle, tanpa menambah statistik."""
        items = self._live.get(r.seq)
        if items is None:
            stamp = time.strftime("%H:%M:%S")
            live_meta = "<span style='color:{}; font-weight:600'>● LANGSUNG</span>".format(Palette.c["ok"])
            items = [MsgItem("in", r.original, r.translation or "…", stamp, live_meta) for _ in range(2)]
            self.pages["home"].feed.add(items[0])
            self.pages["listen"].feed.add(items[1])
            self._live[r.seq] = items
        elif r.partial:
            for item in items:
                item.update_text(r.original, r.translation)
            for feed in (self.pages["home"].feed, self.pages["listen"].feed):
                feed.scroll_to_end()
        if r.partial:
            if r.translation:
                self._last_tr = r.translation
            # Terjemahan kalimat baru belum ada: tetap tampilkan terjemahan terakhir, jangan hanya "…".
            shown = r.translation or self._last_tr or "…"
            self.overlay.set_text(r.original, shown)
            self.pages["subtitle"].preview.set_text(r.original, shown)

    # ================================================================ tutup
    def closeEvent(self, event):
        self.session.stop()
        if self.cfg.overlay_position == "custom":
            self.overlay.save_geometry()
        self.cfg.save()
        self.overlay.close()
        self.tray.hide()
        super().closeEvent(event)
        QApplication.instance().quit()


def _without_speak(cfg):
    """Salinan pengaturan dengan Bicara dimatikan (untuk satu sesi), tanpa mengubah pilihan pengguna."""
    import copy

    c = copy.copy(cfg)
    c.speak_enabled = False
    return c
