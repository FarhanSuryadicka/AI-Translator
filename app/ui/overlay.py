"""Jendela subtitle transparan yang selalu di atas semua aplikasi."""

import ctypes
import sys

from PySide6.QtCore import QPropertyAnimation, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QLabel, QSizeGrip, QVBoxLayout, QWidget

WDA_NONE = 0x0
WDA_EXCLUDEFROMCAPTURE = 0x11  # Windows 10 2004+: jendela tidak ikut terekam saat share screen


class SubtitleOverlay(QWidget):
    # Digeser manual -> posisi jadi "custom" (UI memperbarui pilihan Atas/Bawah).
    moved = Signal()

    def __init__(self, cfg):
        super().__init__(
            None,
            Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool,
        )
        self.cfg = cfg
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setMinimumSize(300, 80)
        self._drag_offset = None

        self.original = QLabel()
        self.translation = QLabel("Subtitle akan muncul di sini. Geser untuk memindahkan.")
        for label in (self.original, self.translation):
            label.setWordWrap(True)
            label.setAlignment(Qt.AlignCenter)
            label.setAttribute(Qt.WA_TransparentForMouseEvents)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 10, 18, 4)
        layout.addWidget(self.original)
        layout.addWidget(self.translation, 1)
        layout.addWidget(QSizeGrip(self), 0, Qt.AlignRight | Qt.AlignBottom)

        self._fade = QPropertyAnimation(self, b"windowOpacity", self)
        self._fade.setDuration(400)
        self._fade.finished.connect(self._fade_done)
        self._idle = QTimer(self)
        self._idle.setSingleShot(True)
        self._idle.timeout.connect(self._fade_out)

        self.apply_style()
        if cfg.overlay_position == "custom" and len(cfg.overlay_geometry) == 4:
            self.setGeometry(*cfg.overlay_geometry)
        else:
            self.apply_position()

    def apply_position(self):
        """Taruh subtitle di tengah bawah / atas layar (posisi "custom" tidak diubah)."""
        if self.cfg.overlay_position == "custom" and len(self.cfg.overlay_geometry) == 4:
            return
        screen = self.screen().availableGeometry()
        w = self.width() if len(self.cfg.overlay_geometry) == 4 else int(screen.width() * 0.6)
        h = self.height() if len(self.cfg.overlay_geometry) == 4 else 150
        x = screen.x() + (screen.width() - w) // 2
        y = screen.y() + 40 if self.cfg.overlay_position == "top" else screen.bottom() - h - 40
        self.setGeometry(x, y, w, h)

    def apply_style(self):
        size = self.cfg.font_size
        self.original.setStyleSheet("color: #c8c8c8; font-size: {}px;".format(max(11, int(size * 0.6))))
        self.translation.setStyleSheet("color: white; font-size: {}px; font-weight: 600;".format(size))
        self.original.setVisible(self.cfg.show_original)
        self.update()

    def set_text(self, original, translation):
        self.original.setText(original)
        self.translation.setText(translation)
        if not self.cfg.overlay_enabled:
            return
        self._fade.stop()
        self.setWindowOpacity(1.0)
        if not self.isVisible():
            self.show()
        if self.cfg.overlay_autohide_sec > 0:
            self._idle.start(self.cfg.overlay_autohide_sec * 1000)

    def _fade_out(self):
        self._fade.stop()
        self._fade.setStartValue(self.windowOpacity())
        self._fade.setEndValue(0.0)
        self._fade.start()

    def _fade_done(self):
        if self.windowOpacity() < 0.05:
            self.original.setText("")
            self.translation.setText("")
            self.setWindowOpacity(1.0)
            self.hide()

    def showEvent(self, event):
        super().showEvent(event)
        self.apply_capture_exclusion()

    def apply_capture_exclusion(self):
        if sys.platform != "win32":
            return
        affinity = WDA_EXCLUDEFROMCAPTURE if self.cfg.hide_from_capture else WDA_NONE
        ctypes.windll.user32.SetWindowDisplayAffinity(int(self.winId()), affinity)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(0, 0, 0, int(255 * self.cfg.overlay_opacity)))
        p.drawRoundedRect(self.rect(), 12, 12)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._drag_offset = event.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, event):
        if self._drag_offset is not None and event.buttons() & Qt.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_offset)

    def mouseReleaseEvent(self, event):
        if self._drag_offset is not None:
            self.cfg.overlay_position = "custom"
            self.save_geometry()
            self.moved.emit()
        self._drag_offset = None

    def save_geometry(self):
        g = self.geometry()
        self.cfg.overlay_geometry = [g.x(), g.y(), g.width(), g.height()]
