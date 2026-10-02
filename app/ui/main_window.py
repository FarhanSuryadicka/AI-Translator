"""Jendela pengaturan & kontrol."""

import os
import threading

from PySide6.QtCore import QObject, Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSlider,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from .. import gpu_check
from ..audio_capture import list_input_devices, list_loopback_devices, list_output_devices, record_sample
from ..config import TRANSCRIPT_DIR
from ..languages import LANGUAGES, language_name
from ..pipeline import LISTEN, Session
from ..process_loopback import list_audio_apps
from ..tts import XTTS_LANGUAGES
from .overlay import SubtitleOverlay

WHISPER_MODELS = ["tiny", "base", "small", "medium", "large-v3-turbo"]
MAX_LOG_ITEMS = 200
RECORD_SECONDS = 15
SAMPLE_TEXT = (
    "Halo, nama saya ... Saya sedang merekam suara saya untuk penerjemah otomatis. "
    "Hari ini cuacanya cerah, dan saya akan mengikuti rapat bersama tim. "
    "Saya berbicara dengan tempo normal dan suara yang jelas."
)
LICENSE_TEXT = (
    "XTTS-v2 memakai lisensi Coqui Public Model License (CPML):\n"
    "hanya untuk penggunaan NON-KOMERSIAL.\n"
    "https://coqui.ai/cpml\n\n"
    "Apakah Anda setuju dengan lisensi tersebut?"
)


class _Bridge(QObject):
    """Meneruskan callback dari thread pekerja ke thread UI dengan aman."""

    result = Signal(object)
    status = Signal(str)
    recorded = Signal(str)
    gpu = Signal(object)


class MainWindow(QMainWindow):
    def __init__(self, cfg):
        super().__init__()
        self.cfg = cfg
        self.setWindowTitle("AI Translator - TranslateGemma")
        self.resize(600, 720)

        self.bridge = _Bridge()
        self.bridge.result.connect(self._on_result)
        self.bridge.status.connect(self._on_status)
        self.bridge.recorded.connect(self._on_recorded)
        self.bridge.gpu.connect(self._on_gpu)
        self.session = Session(cfg, self.bridge.result.emit, self.bridge.status.emit)
        self.overlay = SubtitleOverlay(cfg)

        self._build_ui()
        self.overlay.setVisible(cfg.listen_enabled)
        threading.Thread(target=lambda: self.bridge.gpu.emit(gpu_check.get()), daemon=True).start()

    # ---------- UI ----------
    def _build_ui(self):
        root = QWidget()
        layout = QVBoxLayout(root)

        top = QHBoxLayout()
        self.start_btn = QPushButton("▶  Mulai")
        self.start_btn.setMinimumHeight(40)
        self.start_btn.clicked.connect(self._toggle)
        self.overlay_btn = QPushButton("Tampilkan/Sembunyikan Subtitle")
        self.overlay_btn.clicked.connect(lambda: self.overlay.setVisible(not self.overlay.isVisible()))
        top.addWidget(self.start_btn, 2)
        top.addWidget(self.overlay_btn, 1)
        layout.addLayout(top)

        self.status_label = QLabel("Siap.")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        self.gpu_banner = QFrame()
        self.gpu_banner.setStyleSheet(
            "QFrame { background: #fff4e5; border: 1px solid #f5c27a; border-radius: 6px; } "
            "QLabel { color: #7a4a00; border: none; }"
        )
        banner = QHBoxLayout(self.gpu_banner)
        self.gpu_banner_label = QLabel()
        self.gpu_banner_label.setWordWrap(True)
        self.driver_btn = QPushButton("Unduh driver NVIDIA")
        self.driver_btn.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(gpu_check.DRIVER_URL)))
        banner.addWidget(self.gpu_banner_label, 1)
        banner.addWidget(self.driver_btn)
        self.gpu_banner.hide()
        layout.addWidget(self.gpu_banner)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_listen_tab(), "Dengar → subtitle")
        self.tabs.addTab(self._build_speak_tab(), "Bicara → virtual mic")
        self.tabs.addTab(self._build_engine_tab(), "Engine")
        layout.addWidget(self.tabs)

        hist_row = QHBoxLayout()
        hist_row.addWidget(QLabel("Riwayat:"))
        hist_row.addStretch()
        open_btn = QPushButton("Buka folder transkrip")
        open_btn.clicked.connect(self._open_transcripts)
        hist_row.addWidget(open_btn)
        layout.addLayout(hist_row)

        self.log_list = QListWidget()
        self.log_list.setWordWrap(True)
        layout.addWidget(self.log_list, 1)

        self.setCentralWidget(root)

    def _device_combo(self, names, default_label, current):
        combo = QComboBox()
        combo.addItem(default_label, "")
        for name in names:
            combo.addItem(name, name)
        self._select(combo, current)
        return combo

    def _lang_combo(self, codes, current, auto=False):
        combo = QComboBox()
        if auto:
            combo.addItem("Deteksi otomatis", "auto")
        for code in sorted(codes, key=language_name):
            combo.addItem("{} ({})".format(language_name(code), code), code)
        self._select(combo, current)
        return combo

    def _safe_devices(self, fn):
        try:
            return fn()
        except Exception as e:
            self.status_label.setText("Gagal membaca perangkat audio: {}".format(e))
            return []

    def _build_listen_tab(self):
        tab = QWidget()
        v = QVBoxLayout(tab)

        self.listen_box = QGroupBox("Terjemahkan suara dari speaker/headset (Zoom, Meet, Teams, YouTube...)")
        self.listen_box.setCheckable(True)
        self.listen_box.setChecked(self.cfg.listen_enabled)
        form = QFormLayout(self.listen_box)
        self.loopback_combo = self._device_combo(
            self._safe_devices(list_loopback_devices), "Output default Windows", self.cfg.loopback_device
        )
        form.addRow("Perangkat output:", self.loopback_combo)
        app_row = QHBoxLayout()
        self.app_combo = QComboBox()
        self.app_combo.currentIndexChanged.connect(self._on_app_changed)
        refresh_btn = QPushButton("↻")
        refresh_btn.setToolTip("Muat ulang daftar aplikasi yang sedang terbuka")
        refresh_btn.setFixedWidth(32)
        refresh_btn.clicked.connect(self._refresh_apps)
        app_row.addWidget(self.app_combo, 1)
        app_row.addWidget(refresh_btn)
        form.addRow("Tangkap dari:", app_row)
        self._refresh_apps()
        self.src_combo = self._lang_combo(LANGUAGES, self.cfg.source_language, auto=True)
        self.tgt_combo = self._lang_combo(LANGUAGES, self.cfg.target_language)
        form.addRow("Bahasa sumber:", self.src_combo)
        form.addRow("Terjemahkan ke:", self.tgt_combo)
        v.addWidget(self.listen_box)

        view_box = QGroupBox("Tampilan subtitle (bisa diubah kapan saja)")
        vform = QFormLayout(view_box)
        self.font_spin = QSpinBox()
        self.font_spin.setRange(12, 72)
        self.font_spin.setValue(self.cfg.font_size)
        self.font_spin.valueChanged.connect(self._on_view_changed)
        vform.addRow("Ukuran font:", self.font_spin)
        self.opacity_slider = QSlider(Qt.Horizontal)
        self.opacity_slider.setRange(0, 100)
        self.opacity_slider.setValue(int(self.cfg.overlay_opacity * 100))
        self.opacity_slider.valueChanged.connect(self._on_view_changed)
        vform.addRow("Gelap latar:", self.opacity_slider)
        self.original_chk = QCheckBox("Tampilkan teks asli di atas terjemahan")
        self.original_chk.setChecked(self.cfg.show_original)
        self.original_chk.toggled.connect(self._on_view_changed)
        vform.addRow(self.original_chk)
        self.capture_chk = QCheckBox("Sembunyikan subtitle saat share screen")
        self.capture_chk.setChecked(self.cfg.hide_from_capture)
        self.capture_chk.toggled.connect(self._on_view_changed)
        vform.addRow(self.capture_chk)
        v.addWidget(view_box)
        v.addStretch()
        return tab

    def _refresh_apps(self):
        current = self.app_combo.currentData() if self.app_combo.count() else self.cfg.loopback_app
        self.app_combo.blockSignals(True)
        self.app_combo.clear()
        self.app_combo.addItem("Semua suara di perangkat output", "")
        apps = self._safe_devices(list_audio_apps)
        if current and current not in apps:
            apps.append(current)  # tetap tampil walau aplikasinya belum dibuka
        for name in sorted(apps, key=str.lower):
            self.app_combo.addItem("Hanya aplikasi: " + name, name)
        self._select(self.app_combo, current)
        self.app_combo.blockSignals(False)
        self._on_app_changed()

    def _on_app_changed(self, *_):
        # Process loopback tidak terikat perangkat output; suara aplikasi ditangkap di mana pun diputar.
        self.loopback_combo.setEnabled(not self.app_combo.currentData())

    def _build_speak_tab(self):
        tab = QWidget()
        v = QVBoxLayout(tab)

        self.speak_box = QGroupBox("Terjemahkan suara Anda dan kirim ke virtual mic, memakai suara tiruan Anda")
        self.speak_box.setCheckable(True)
        self.speak_box.setChecked(self.cfg.speak_enabled)
        self.speak_box.toggled.connect(self._on_speak_toggled)
        form = QFormLayout(self.speak_box)

        self.mic_combo = self._device_combo(
            self._safe_devices(list_input_devices), "Mic default Windows", self.cfg.mic_device
        )
        form.addRow("Mikrofon Anda:", self.mic_combo)
        self.mic_lang_combo = self._lang_combo(LANGUAGES, self.cfg.mic_language, auto=True)
        form.addRow("Anda berbicara:", self.mic_lang_combo)
        self.speak_tgt_combo = self._lang_combo(XTTS_LANGUAGES, self.cfg.speak_target_language)
        form.addRow("Terjemahkan ke:", self.speak_tgt_combo)

        self.vmic_combo = QComboBox()
        outputs = self._safe_devices(list_output_devices)
        for name in outputs:
            self.vmic_combo.addItem(name, name)
        self._select(self.vmic_combo, self.cfg.virtual_mic_device)
        form.addRow("Kirim ke (virtual mic):", self.vmic_combo)
        if not any("VB-Audio" in name for name in outputs):
            warn = QLabel(
                "⚠ VB-Audio Virtual Cable belum terinstal. Unduh gratis di "
                '<a href="https://vb-audio.com/Cable/">vb-audio.com/Cable</a>, '
                "instal (klik kanan → Run as administrator), restart PC, lalu buka aplikasi ini lagi."
            )
            warn.setOpenExternalLinks(True)
            warn.setWordWrap(True)
            warn.setStyleSheet("color: #d9822b;")
            form.addRow(warn)

        voice_row = QHBoxLayout()
        self.voice_edit = QLineEdit(self.cfg.voice_sample)
        browse_btn = QPushButton("Pilih file...")
        browse_btn.clicked.connect(self._browse_voice)
        self.record_btn = QPushButton("● Rekam {} dtk".format(RECORD_SECONDS))
        self.record_btn.clicked.connect(self._record_voice)
        voice_row.addWidget(self.voice_edit, 1)
        voice_row.addWidget(browse_btn)
        voice_row.addWidget(self.record_btn)
        form.addRow("Sampel suara Anda:", voice_row)

        self.tts_device_combo = QComboBox()
        self.tts_device_combo.addItem("GPU (cepat)", "cuda")
        self.tts_device_combo.addItem("CPU (lambat, hemat VRAM)", "cpu")
        self._select(self.tts_device_combo, self.cfg.tts_device)
        form.addRow("XTTS jalan di:", self.tts_device_combo)
        v.addWidget(self.speak_box)

        help_label = QLabel(
            "Cara pakai di Zoom/Meet/Teams: pilih mikrofon <b>\"CABLE Output (VB-Audio Virtual Cable)\"</b>.<br>"
            "Gunakan <b>headset</b> agar suara peserta lain tidak ikut tertangkap mic Anda.<br>"
            "Model suara: XTTS-v2 (lisensi non-komersial)."
        )
        help_label.setWordWrap(True)
        v.addWidget(help_label)
        v.addStretch()
        return tab

    def _build_engine_tab(self):
        tab = QWidget()
        form = QFormLayout(tab)
        self.gpu_label = QLabel("Memeriksa GPU...")
        self.gpu_label.setWordWrap(True)
        form.addRow("GPU:", self.gpu_label)
        self.whisper_combo = QComboBox()
        self.whisper_combo.addItems(WHISPER_MODELS)
        self.whisper_combo.setCurrentText(self.cfg.whisper_model)
        form.addRow("Model Whisper:", self.whisper_combo)
        self.backend_combo = QComboBox()
        self.backend_combo.addItem("Bawaan aplikasi (llama.cpp, offline)", "builtin")
        self.backend_combo.addItem("Server Ollama (lokal / VPS)", "ollama")
        self._select(self.backend_combo, self.cfg.translator_backend)
        self.backend_combo.currentIndexChanged.connect(self._on_backend_changed)
        form.addRow("Mesin terjemahan:", self.backend_combo)
        self.url_edit = QLineEdit(self.cfg.ollama_url)
        self.model_edit = QLineEdit(self.cfg.ollama_model)
        form.addRow("Server Ollama:", self.url_edit)
        form.addRow("Model terjemahan:", self.model_edit)
        self.transcript_chk = QCheckBox("Simpan transkrip ke folder transcripts/")
        self.transcript_chk.setChecked(self.cfg.save_transcript)
        form.addRow(self.transcript_chk)
        self._on_backend_changed()
        return tab

    def _on_backend_changed(self, *_):
        ollama = self.backend_combo.currentData() == "ollama"
        self.url_edit.setEnabled(ollama)
        self.model_edit.setEnabled(ollama)

    @staticmethod
    def _select(combo, value):
        idx = combo.findData(value)
        if idx >= 0:
            combo.setCurrentIndex(idx)

    # ---------- Aksi ----------
    def _read_settings(self):
        c = self.cfg
        c.listen_enabled = self.listen_box.isChecked()
        c.loopback_device = self.loopback_combo.currentData()
        c.loopback_app = self.app_combo.currentData() or ""
        c.source_language = self.src_combo.currentData()
        c.target_language = self.tgt_combo.currentData()

        c.speak_enabled = self.speak_box.isChecked()
        c.mic_device = self.mic_combo.currentData()
        c.mic_language = self.mic_lang_combo.currentData()
        c.speak_target_language = self.speak_tgt_combo.currentData()
        c.virtual_mic_device = self.vmic_combo.currentData() or ""
        c.voice_sample = self.voice_edit.text().strip()
        c.tts_device = self.tts_device_combo.currentData()

        c.whisper_model = self.whisper_combo.currentText()
        c.translator_backend = self.backend_combo.currentData()
        c.ollama_url = self.url_edit.text().strip() or "http://localhost:11434"
        c.ollama_model = self.model_edit.text().strip() or "translategemma:4b"
        c.save_transcript = self.transcript_chk.isChecked()

    def _set_editable(self, editable):
        for i in range(self.tabs.count()):
            self.tabs.widget(i).setEnabled(editable)
        # Tampilan subtitle tetap bisa diubah saat berjalan.
        self.tabs.widget(0).setEnabled(True)
        self.listen_box.setEnabled(editable)

    def _toggle(self):
        if self.session.running:
            self.start_btn.setEnabled(False)
            self.status_label.setText("Menghentikan...")
            self.session.stop()
            return
        self._read_settings()
        if self.cfg.speak_enabled and not self._ensure_license():
            return
        self.cfg.save()
        self._set_editable(False)
        self.start_btn.setText("■  Berhenti")
        if self.cfg.listen_enabled:
            self.overlay.show()
        self.session.start()

    def _ensure_license(self):
        if self.cfg.xtts_license_agreed:
            return True
        answer = QMessageBox.question(self, "Lisensi XTTS-v2", LICENSE_TEXT)
        if answer == QMessageBox.Yes:
            self.cfg.xtts_license_agreed = True
            return True
        return False

    def _on_speak_toggled(self, checked):
        if checked and not self._ensure_license():
            self.speak_box.setChecked(False)

    def _browse_voice(self):
        path, _ = QFileDialog.getOpenFileName(self, "Pilih sampel suara", "", "Audio WAV (*.wav)")
        if path:
            self.voice_edit.setText(path)

    def _record_voice(self):
        path = self.voice_edit.text().strip() or self.cfg.voice_sample
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        answer = QMessageBox.information(
            self,
            "Rekam sampel suara",
            "Setelah klik OK, bacakan teks berikut dengan suara normal selama {} detik:\n\n\"{}\"".format(
                RECORD_SECONDS, SAMPLE_TEXT
            ),
            QMessageBox.Ok | QMessageBox.Cancel,
        )
        if answer != QMessageBox.Ok:
            return
        self.record_btn.setEnabled(False)
        self.record_btn.setText("Merekam...")
        device = self.mic_combo.currentData()

        def work():
            try:
                secs = record_sample(device, RECORD_SECONDS, path)
                self.bridge.recorded.emit("Sampel suara tersimpan ({:.0f} dtk): {}".format(secs, path))
            except Exception as e:
                self.bridge.recorded.emit("Gagal merekam: {}".format(e))

        threading.Thread(target=work, daemon=True).start()

    def _on_recorded(self, msg):
        self.record_btn.setEnabled(True)
        self.record_btn.setText("● Rekam {} dtk".format(RECORD_SECONDS))
        self.status_label.setText(msg)

    def _on_gpu(self, info):
        self.gpu_label.setText(info.message())
        if info.status == "ok" and not (info.vram_mb and info.vram_mb < gpu_check.MIN_VRAM_MB):
            return
        self.gpu_banner_label.setText("⚠ " + info.message())
        self.driver_btn.setVisible(info.status in ("old", "missing"))
        self.gpu_banner.show()

    def _on_view_changed(self, *_):
        c = self.cfg
        c.font_size = self.font_spin.value()
        c.overlay_opacity = self.opacity_slider.value() / 100.0
        c.show_original = self.original_chk.isChecked()
        c.hide_from_capture = self.capture_chk.isChecked()
        self.overlay.apply_style()
        self.overlay.apply_capture_exclusion()

    def _open_transcripts(self):
        os.makedirs(TRANSCRIPT_DIR, exist_ok=True)
        os.startfile(TRANSCRIPT_DIR)

    # ---------- Callback session ----------
    def _on_result(self, r):
        if r.direction == LISTEN:
            self.overlay.set_text(r.original, r.translation)
            tag = "🔊"
        else:
            tag = "🎤"
        self.log_list.addItem(
            "{} [{}] {}\n→ {}   (ASR {} ms, terjemah {} ms)".format(
                tag, r.language, r.original, r.translation, r.asr_ms, r.mt_ms
            )
        )
        while self.log_list.count() > MAX_LOG_ITEMS:
            self.log_list.takeItem(0)
        self.log_list.scrollToBottom()

    def _on_status(self, msg):
        if msg == "STOPPED":
            self._set_editable(True)
            self.start_btn.setEnabled(True)
            self.start_btn.setText("▶  Mulai")
            if not self.status_label.text().startswith("ERROR"):
                self.status_label.setText("Berhenti.")
            return
        self.status_label.setText(msg)

    def closeEvent(self, event):
        self.session.stop()
        self.overlay.save_geometry()
        self._on_view_changed()
        self._read_settings()
        self.cfg.save()
        self.overlay.close()
        super().closeEvent(event)
