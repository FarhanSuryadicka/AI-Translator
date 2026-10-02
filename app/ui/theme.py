"""Palet warna, font, dan stylesheet (QSS) — nilai diambil dari token CSS mockup/ui-mockup-v2.html."""

import ctypes
import os
import sys
import tempfile

from PySide6.QtGui import QColor, QFont, QFontDatabase

ASSETS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets")

LIGHT = {
    "bg": "#e9edf3", "win": "#f6f8fb", "side": "#ffffff", "card": "#ffffff", "sunken": "#f1f4f8",
    "line": "#e3e8ef", "line_strong": "#cfd7e3",
    "text": "#0f172a", "muted": "#64748b", "faint": "#94a3b8",
    "accent": "#2563eb", "accent2": "#0d9488", "accent_soft": "#e0e9ff", "accent_text": "#1d4ed8",
    "ok": "#16a34a", "ok_soft": "#dcfce7", "warn": "#d97706", "warn_soft": "#fef3c7",
    "danger": "#dc2626", "danger_soft": "#fee2e2",
    "listen": "#2563eb", "speak": "#0d9488",
}
DARK = {
    "bg": "#04060b", "win": "#0a0f1c", "side": "#0d1322", "card": "#111a2d", "sunken": "#0c1424",
    "line": "#1c2740", "line_strong": "#2a3756",
    "text": "#e5ebf5", "muted": "#8b9ab5", "faint": "#5d6b86",
    "accent": "#3b82f6", "accent2": "#14b8a6", "accent_soft": "#15234a", "accent_text": "#93b4ff",
    "ok": "#22c55e", "ok_soft": "#0f2a1b", "warn": "#f59e0b", "warn_soft": "#2d2109",
    "danger": "#f87171", "danger_soft": "#2f1215",
    "listen": "#3b82f6", "speak": "#14b8a6",
}
# Warna segmen bar VRAM: Windows, Whisper, TranslateGemma, XTTS.
VRAM_COLORS = ["#94a3b8", "#3b82f6", "#14b8a6", "#a855f7"]

FONT_FAMILY = "Segoe UI"


class Palette:
    """Palet aktif; widget membaca warna dari sini saat menggambar (paintEvent)."""

    dark = False
    c = dict(LIGHT)

    @classmethod
    def set(cls, dark):
        cls.dark = dark
        cls.c = dict(DARK if dark else LIGHT)

    @classmethod
    def q(cls, key, alpha=None):
        color = QColor(cls.c[key])
        if alpha is not None:
            color.setAlphaF(alpha)
        return color


def mix(a, b, t):
    """Campur dua warna hex (t = porsi b), seperti color-mix() di CSS."""
    ca, cb = QColor(a), QColor(b)
    return QColor(
        round(ca.red() + (cb.red() - ca.red()) * t),
        round(ca.green() + (cb.green() - ca.green()) * t),
        round(ca.blue() + (cb.blue() - ca.blue()) * t),
    ).name()


def load_fonts():
    """Daftarkan Inter (dibundel); jatuh ke Segoe UI kalau gagal."""
    global FONT_FAMILY
    folder = os.path.join(ASSETS, "fonts")
    families = set()
    for name in ("Inter-Regular.ttf", "Inter-Medium.ttf", "Inter-SemiBold.ttf", "Inter-Bold.ttf"):
        fid = QFontDatabase.addApplicationFont(os.path.join(folder, name))
        if fid >= 0:
            families.update(QFontDatabase.applicationFontFamilies(fid))
    if "Inter" in families:
        FONT_FAMILY = "Inter"
    return FONT_FAMILY


def font(px=14, weight=QFont.Normal):
    f = QFont(FONT_FAMILY)
    f.setPixelSize(px)
    f.setWeight(weight)
    f.setHintingPreference(QFont.PreferNoHinting)
    return f


def windows_prefers_dark():
    if sys.platform != "win32":
        return False
    try:
        import winreg

        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize")
        value, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
        return value == 0
    except OSError:
        return False


def resolve_dark(theme):
    return theme == "dark" or (theme == "auto" and windows_prefers_dark())


def set_titlebar_dark(widget, dark):
    """Title bar bawaan Windows ikut gelap/terang (DWMWA_USE_IMMERSIVE_DARK_MODE)."""
    if sys.platform != "win32":
        return
    value = ctypes.c_int(1 if dark else 0)
    try:
        ctypes.windll.dwmapi.DwmSetWindowAttribute(int(widget.winId()), 20, ctypes.byref(value), ctypes.sizeof(value))
    except OSError:
        pass


def _chevron(color):
    """File SVG panah kecil untuk QComboBox (QSS butuh path file)."""
    path = os.path.join(tempfile.gettempdir(), "ait_chevron_{}.svg".format(color.strip("#")))
    if not os.path.exists(path):
        with open(path, "w", encoding="utf-8") as f:
            f.write(
                '<svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" '
                'stroke="{}" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">'
                '<path d="M6 9l6 6 6-6"/></svg>'.format(color)
            )
    return path.replace("\\", "/")


def stylesheet():
    c = dict(Palette.c)
    c["font"] = FONT_FAMILY
    c["chev"] = _chevron(c["muted"])
    c["sel_bg"] = mix(c["card"], c["accent"], 0.12)
    c["hover_border"] = mix(c["line"], c["accent"], 0.45)
    return """
* {{ font-family: "{font}", "Segoe UI"; font-size: 14px; color: {text}; }}
QMainWindow, #root {{ background: {win}; }}
QToolTip {{ background: {text}; color: {win}; border: 0; padding: 6px 8px; border-radius: 6px; }}

/* ---------- sidebar ---------- */
#side {{ background: {side}; border-right: 1px solid {line}; }}
#brandName {{ font-size: 15px; font-weight: 700; }}
#brandSub {{ font-size: 11px; color: {muted}; }}
#navLabel {{ font-size: 11px; font-weight: 600; color: {faint}; letter-spacing: 0.6px; padding: 12px 10px 4px 10px; }}
NavButton {{ border: 0; border-radius: 8px; background: transparent; text-align: left; padding: 0; }}
NavButton:hover {{ background: {sunken}; }}
NavButton:checked {{ background: {accent_soft}; }}
NavButton QLabel#navText {{ color: {muted}; font-weight: 500; }}
NavButton:hover QLabel#navText {{ color: {text}; }}
NavButton:checked QLabel#navText {{ color: {accent_text}; }}
#badge {{ font-size: 11px; font-weight: 600; color: {muted}; background: {sunken}; border-radius: 9px; padding: 1px 7px; }}
#badgeWarn {{ font-size: 11px; font-weight: 600; color: {warn}; background: {warn_soft}; border-radius: 9px; padding: 1px 7px; }}
#health {{ background: {card}; border: 1px solid {line}; border-radius: 12px; }}
#health QLabel {{ font-size: 12px; color: {muted}; }}
#health QLabel#healthVal {{ color: {text}; font-weight: 600; }}

/* ---------- topbar ---------- */
#topbar {{ background: {win}; border-bottom: 1px solid {line}; }}
#pageTitle {{ font-size: 18px; font-weight: 700; }}
#pageSub, .muted {{ font-size: 13px; color: {muted}; }}
#sessPill {{ background: {sunken}; border-radius: 15px; }}
#sessPill QLabel {{ font-size: 13px; color: {muted}; }}
#sessPill[running="true"] QLabel {{ color: {text}; }}

/* ---------- content ---------- */
#content, #content > QWidget {{ background: {win}; }}
QScrollArea {{ border: 0; background: {win}; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {line_strong}; border-radius: 4px; min-height: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
QScrollBar:horizontal {{ height: 0; }}

#card {{ background: {card}; border: 1px solid {line}; border-radius: 14px; }}
#cardTitle {{ font-size: 14px; font-weight: 600; }}
#hint {{ font-size: 12px; color: {muted}; }}
#small {{ font-size: 12px; color: {muted}; }}
#rowTitle {{ font-weight: 500; }}
#rowSub {{ font-size: 12px; color: {muted}; }}
#statVal {{ font-size: 22px; font-weight: 700; }}
#fieldLabel {{ font-size: 12px; font-weight: 500; color: {muted}; }}
#sep {{ background: {line}; max-height: 1px; min-height: 1px; border: 0; }}
#dirTitle {{ font-size: 15px; font-weight: 600; }}
#route {{ background: {sunken}; border-radius: 10px; }}
#chip {{ background: {card}; border: 1px solid {line}; border-radius: 6px; padding: 3px 9px; font-size: 13px; font-weight: 500; }}
#arrow {{ color: {faint}; font-size: 13px; }}
#kbd {{ font-size: 12px; font-weight: 600; border: 1px solid {line_strong}; background: {sunken}; border-radius: 5px; padding: 1px 6px; }}
#quote {{ background: {sunken}; border-left: 3px solid {speak}; border-top-right-radius: 8px; border-bottom-right-radius: 8px; padding: 10px 12px; font-size: 14px; }}
#licBox {{ background: {sunken}; border-radius: 10px; padding: 12px; font-size: 12px; color: {muted}; }}
#tag {{ font-size: 11px; font-weight: 500; color: {muted}; background: {sunken}; border-radius: 5px; padding: 1px 7px; }}
#tagNc {{ font-size: 11px; font-weight: 500; color: {warn}; background: {warn_soft}; border-radius: 5px; padding: 1px 7px; }}
#guideNum {{ background: {accent_soft}; color: {accent_text}; border-radius: 12px; font-size: 12px; font-weight: 600; }}
#countdown {{ font-size: 26px; font-weight: 700; color: {danger}; }}

#bannerWarn {{ background: {warn_soft}; border: 1px solid {warn}; border-radius: 12px; }}
#bannerWarn QLabel {{ font-size: 13px; }}
#bannerWarn QLabel#bannerTitle {{ font-weight: 700; }}
#bannerWarn QLabel#bannerIcon {{ color: {warn}; font-size: 18px; }}

/* ---------- inputs ---------- */
QComboBox, QLineEdit {{ background: {win}; border: 1px solid {line_strong}; border-radius: 9px; padding: 8px 11px; min-height: 18px; }}
QComboBox:hover, QLineEdit:hover {{ border-color: {hover_border}; }}
QComboBox:focus, QLineEdit:focus {{ border-color: {accent}; }}
QComboBox:disabled, QLineEdit:disabled {{ color: {faint}; }}
QComboBox::drop-down {{ border: 0; width: 26px; }}
QComboBox::down-arrow {{ image: url({chev}); width: 12px; height: 12px; }}
QComboBox QAbstractItemView {{ background: {card}; border: 1px solid {line_strong}; border-radius: 8px; padding: 4px; outline: 0;
    selection-background-color: {accent_soft}; selection-color: {accent_text}; }}
QSlider::groove:horizontal {{ height: 6px; background: {line_strong}; border-radius: 3px; }}
QSlider::sub-page:horizontal {{ background: {accent}; border-radius: 3px; }}
QSlider::handle:horizontal {{ background: {accent}; border: 3px solid {card}; width: 12px; height: 12px; margin: -6px 0; border-radius: 9px; }}
QCheckBox {{ spacing: 10px; font-size: 13px; }}
QCheckBox::indicator {{ width: 16px; height: 16px; border: 1px solid {line_strong}; border-radius: 4px; background: {win}; }}
QCheckBox::indicator:checked {{ background: {accent}; border-color: {accent}; }}

/* ---------- buttons ---------- */
QPushButton#btn {{ background: {card}; border: 1px solid {line_strong}; border-radius: 9px; padding: 7px 14px; font-size: 13px; font-weight: 500; }}
QPushButton#btn:hover {{ border-color: {accent}; }}
QPushButton#btn:disabled {{ color: {faint}; }}
QPushButton#btnGhost {{ background: transparent; border: 1px solid transparent; border-radius: 9px; padding: 7px 12px; font-size: 13px; font-weight: 500; color: {muted}; }}
QPushButton#btnGhost:hover {{ background: {sunken}; color: {text}; }}
QPushButton#btnWarn {{ background: {card}; border: 1px solid {warn}; border-radius: 9px; padding: 7px 14px; font-size: 13px; font-weight: 500; color: {warn}; }}
QPushButton#btnDanger {{ background: {card}; border: 1px solid {danger}; border-radius: 9px; padding: 7px 14px; font-size: 13px; font-weight: 500; color: {danger}; }}
QPushButton#btnPrimary {{ border: 0; border-radius: 9px; padding: 8px 16px; font-size: 13px; font-weight: 600; color: white;
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 {accent}, stop:1 {accent2}); }}
QPushButton#btnPrimary:disabled {{ background: {line_strong}; }}
QPushButton#btnStop {{ border: 0; border-radius: 9px; padding: 8px 16px; font-size: 13px; font-weight: 600; color: white; background: {danger}; }}
QPushButton#iconBtn {{ background: transparent; border: 0; border-radius: 9px; }}
QPushButton#iconBtn:hover {{ background: {sunken}; }}
QPushButton#swap {{ background: {win}; border: 1px solid {line_strong}; border-radius: 17px; font-size: 14px; }}
QPushButton#swap:hover {{ border-color: {accent}; }}

/* segmented */
#seg {{ background: {sunken}; border-radius: 9px; }}
#seg QPushButton {{ background: transparent; border: 0; border-radius: 7px; padding: 6px 12px; font-size: 13px; font-weight: 500; color: {muted}; }}
#seg QPushButton:checked {{ background: {card}; color: {text}; }}

/* history */
#histList {{ border-right: 1px solid {line}; }}
HistItem {{ border: 0; border-bottom: 1px solid {line}; background: transparent; text-align: left; }}
HistItem:hover {{ background: {sunken}; }}
HistItem:checked {{ background: {accent_soft}; }}
#histHead {{ border-bottom: 1px solid {line}; }}
#histTitle {{ font-size: 15px; font-weight: 600; }}

/* wizard */
#modal {{ background: {card}; border: 1px solid {line}; border-radius: 18px; }}
#modalTitle {{ font-size: 19px; font-weight: 700; }}
#modalLead {{ color: {muted}; }}
#modalFoot {{ border-top: 1px solid {line}; }}

QFrame#msg {{ border-radius: 10px; }}
QFrame#msg:hover {{ background: {sunken}; }}
#msgO {{ color: {muted}; font-size: 13px; }}
#msgT {{ font-weight: 500; }}
#msgTime {{ color: {faint}; font-size: 11px; }}
#msgMeta {{ font-size: 11px; }}
#feedInner {{ background: transparent; }}
QScrollArea#feed {{ background: transparent; }}

#toast {{ background: {text}; border-radius: 10px; }}
#toast QLabel {{ color: {win}; font-size: 13px; }}
""".format(**c)
