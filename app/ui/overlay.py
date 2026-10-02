"""Jendela subtitle transparan yang selalu di atas semua aplikasi."""

import ctypes
import sys

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QLabel, QSizeGrip, QVBoxLayout, QWidget

WDA_NONE = 0x0
WDA_EXCLUDEFROMCAPTURE = 0x11  # Windows 10 2004+: jendela tidak ikut terekam saat share screen


class SubtitleOverlay(QWidget):
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

        self.apply_style()
        if len(cfg.overlay_geometry) == 4:
            self.setGeometry(*cfg.overlay_geometry)
        else:
            self._place_default()

    def _place_default(self):
        screen = self.screen().availableGeometry()
        w, h = int(screen.width() * 0.6), 150
        self.setGeometry(screen.x() + (screen.width() - w) // 2, screen.bottom() - h - 40, w, h)

    def apply_style(self):
        size = self.cfg.font_size
        self.original.setStyleSheet("color: #c8c8c8; font-size: {}px;".format(max(11, int(size * 0.6))))
        self.translation.setStyleSheet("color: white; font-size: {}px; font-weight: 600;".format(size))
        self.original.setVisible(self.cfg.show_original)
        self.update()

    def set_text(self, original, translation):
        self.original.setText(original)
        self.translation.setText(translation)

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
        self._drag_offset = None

    def save_geometry(self):
        g = self.geometry()
        self.cfg.overlay_geometry = [g.x(), g.y(), g.width(), g.height()]
