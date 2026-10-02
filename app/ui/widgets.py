"""Komponen UI kustom (digambar sendiri) agar tampilan sama dengan mockup v2."""

from PySide6.QtCore import (
    Property, QEasingCurve, QObject, QPointF, QPropertyAnimation, QRectF, QSize, Qt, QTimer, Signal,
)
from PySide6.QtGui import QColor, QFont, QLinearGradient, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QAbstractButton, QButtonGroup, QFrame, QGraphicsOpacityEffect, QHBoxLayout, QLabel, QPushButton,
    QScrollArea, QSizePolicy, QVBoxLayout, QWidget,
)

from . import icons
from .theme import Palette, VRAM_COLORS, font, mix


class _ThemeBus(QObject):
    changed = Signal()


theme_bus = _ThemeBus()


# ---------------------------------------------------------------- dasar
def label(text="", name=None, wrap=False, rich=False):
    w = QLabel(text)
    if name:
        w.setObjectName(name)
    if wrap:
        w.setWordWrap(True)
    if rich:
        w.setTextFormat(Qt.RichText)
        w.setOpenExternalLinks(True)
    return w


def button(text, kind="btn", icon_name=None, tooltip=None):
    b = QPushButton(text)
    b.setObjectName(kind)
    b.setCursor(Qt.PointingHandCursor)
    if tooltip:
        b.setToolTip(tooltip)
    if icon_name:
        b.icon_name = icon_name  # bisa diganti (mis. play -> stop); dipakai lagi saat tema berganti

        def refresh():
            color = "#ffffff" if b.objectName() in ("btnPrimary", "btnStop") else Palette.c["warn" if kind == "btnWarn" else "text"]
            b.setIcon(icons.icon(b.icon_name, color, 15))
        refresh()
        theme_bus.changed.connect(refresh)
        b.setIconSize(QSize(15, 15))
    return b


def separator():
    s = QFrame()
    s.setObjectName("sep")
    s.setFrameShape(QFrame.NoFrame)
    return s


def hbox(*items, spacing=8, margins=(0, 0, 0, 0)):
    lay = QHBoxLayout()
    lay.setSpacing(spacing)
    lay.setContentsMargins(*margins)
    for it in items:
        if it == "stretch":
            lay.addStretch(1)
        elif isinstance(it, int):
            lay.addSpacing(it)
        elif isinstance(it, QWidget):
            lay.addWidget(it)
        else:
            lay.addLayout(it)
    return lay


def vbox(*items, spacing=8, margins=(0, 0, 0, 0)):
    lay = QVBoxLayout()
    lay.setSpacing(spacing)
    lay.setContentsMargins(*margins)
    for it in items:
        if it == "stretch":
            lay.addStretch(1)
        elif isinstance(it, int):
            lay.addSpacing(it)
        elif isinstance(it, QWidget):
            lay.addWidget(it)
        else:
            lay.addLayout(it)
    return lay


def wrap(layout):
    w = QWidget()
    w.setLayout(layout)
    return w


class IconLabel(QLabel):
    """Ikon SVG yang otomatis diwarnai ulang saat tema berganti."""

    def __init__(self, name, color_key="muted", size=18):
        super().__init__()
        self._name, self._key, self._size = name, color_key, size
        self.setFixedSize(size, size)
        self.refresh()
        theme_bus.changed.connect(self.refresh)

    def set_color(self, key):
        self._key = key
        self.refresh()

    def set_name(self, name):
        self._name = name
        self.refresh()

    def refresh(self):
        color = self._key if self._key.startswith("#") else Palette.c[self._key]
        self.setPixmap(icons.pixmap(self._name, color, self._size))


# ---------------------------------------------------------------- kartu
class Card(QFrame):
    def __init__(self, padding=18, spacing=14):
        super().__init__()
        self.setObjectName("card")
        self.body = QVBoxLayout(self)
        self.body.setContentsMargins(padding, padding, padding, padding)
        self.body.setSpacing(spacing)

    def header(self, title, hint=None, *end):
        row = QHBoxLayout()
        row.setSpacing(10)
        row.addWidget(label(title, "cardTitle"))
        if hint:
            h = label(hint, "hint")
            h.setWordWrap(True)
            row.addWidget(h, 1)
        else:
            row.addStretch(1)
        for w in end:
            row.addWidget(w)
        self.body.addLayout(row)
        return row

    def add(self, item, stretch=0):
        if isinstance(item, QWidget):
            self.body.addWidget(item, stretch)
        else:
            self.body.addLayout(item, stretch)
        return item


class DirCard(QFrame):
    """Kartu arah (Dengar/Bicara) dengan garis warna 3px di atas, seperti .dir di mockup."""

    def __init__(self, color_key):
        super().__init__()
        self._key = color_key
        self.body = QVBoxLayout(self)
        self.body.setContentsMargins(18, 21, 18, 18)
        self.body.setSpacing(14)
        self._fx = QGraphicsOpacityEffect(self)
        self._fx.setOpacity(1.0)
        self.setGraphicsEffect(self._fx)

    def set_off(self, off):
        self._fx.setOpacity(0.6 if off else 1.0)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        path = QPainterPath()
        path.addRoundedRect(r, 14, 14)
        p.fillPath(path, Palette.q("card"))
        p.setClipPath(path)
        p.fillRect(QRectF(0, 0, self.width(), 3), QColor(Palette.c[self._key]))
        p.setClipping(False)
        p.setPen(QPen(Palette.q("line"), 1))
        p.drawPath(path)


# ---------------------------------------------------------------- kontrol
class Switch(QAbstractButton):
    def __init__(self, checked=False):
        super().__init__()
        self.setCheckable(True)
        self.setChecked(checked)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedSize(38, 22)
        self._pos = 1.0 if checked else 0.0
        self._anim = QPropertyAnimation(self, b"knob", self)
        self._anim.setDuration(160)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)
        self.toggled.connect(self._animate)

    def _animate(self, on):
        self._anim.stop()
        self._anim.setStartValue(self._pos)
        self._anim.setEndValue(1.0 if on else 0.0)
        self._anim.start()

    def get_knob(self):
        return self._pos

    def set_knob(self, v):
        self._pos = v
        self.update()

    knob = Property(float, get_knob, set_knob)

    def sizeHint(self):
        return QSize(38, 22)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        off, on = QColor(Palette.c["line_strong"]), QColor(Palette.c["accent"])
        t = self._pos
        track = QColor(
            round(off.red() + (on.red() - off.red()) * t),
            round(off.green() + (on.green() - off.green()) * t),
            round(off.blue() + (on.blue() - off.blue()) * t),
        )
        if not self.isEnabled():
            track.setAlphaF(0.5)
        p.setPen(Qt.NoPen)
        p.setBrush(track)
        p.drawRoundedRect(QRectF(0, 0, 38, 22), 11, 11)
        p.setBrush(QColor(0, 0, 0, 40))
        x = 3 + 16 * t
        p.drawEllipse(QRectF(x, 3.6, 16, 16))
        p.setBrush(QColor("#ffffff"))
        p.drawEllipse(QRectF(x, 3, 16, 16))


class Segmented(QFrame):
    changed = Signal(str)

    def __init__(self, items, value=None):
        super().__init__()
        self.setObjectName("seg")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(3, 3, 3, 3)
        lay.setSpacing(2)
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        self._buttons = {}
        for key, text in items:
            b = QPushButton(text)
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            self._group.addButton(b)
            self._buttons[key] = b
            lay.addWidget(b)
            b.clicked.connect(lambda _=False, k=key: self.changed.emit(k))
        self.set_value(value if value is not None else items[0][0])
        self.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)

    def value(self):
        for k, b in self._buttons.items():
            if b.isChecked():
                return k
        return None

    def set_value(self, key):
        if key in self._buttons:
            self._buttons[key].setChecked(True)
        else:
            # Tidak ada yang terpilih (mis. posisi subtitle "custom").
            self._group.setExclusive(False)
            for b in self._buttons.values():
                b.setChecked(False)
            self._group.setExclusive(True)


class LevelMeter(QWidget):
    def __init__(self, height=6):
        super().__init__()
        self._v = 0.0
        self.setFixedHeight(height)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def set_level(self, v):
        self._v = max(0.0, min(1.0, v))
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        h = self.height()
        p.setPen(Qt.NoPen)
        p.setBrush(Palette.q("sunken"))
        p.drawRoundedRect(QRectF(0, 0, self.width(), h), h / 2, h / 2)
        w = self.width() * self._v
        if w > 1:
            g = QLinearGradient(0, 0, w, 0)
            g.setColorAt(0, Palette.q("ok"))
            g.setColorAt(1, Palette.q("warn"))
            p.setBrush(g)
            p.drawRoundedRect(QRectF(0, 0, w, h), h / 2, h / 2)


class MeterRow(QWidget):
    """[ikon] [====meter====] [-32 dB]"""

    def __init__(self, icon_name=None):
        super().__init__()
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(10)
        if icon_name:
            lay.addWidget(IconLabel(icon_name, "muted", 14))
        self.meter = LevelMeter()
        lay.addWidget(self.meter, 1)
        self.text = label("—", "small")
        self.text.setFixedWidth(52)
        self.text.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        lay.addWidget(self.text)

    def set_db(self, db):
        if db is None:
            self.meter.set_level(0)
            self.text.setText("—")
            return
        self.meter.set_level((db + 60) / 55)
        self.text.setText("{:.0f} dB".format(max(db, -90)))


class VramBar(QWidget):
    def __init__(self, height=6, total=6.0):
        super().__init__()
        self.parts = []
        self.total = total
        self.setFixedHeight(height)

    def set_parts(self, parts, total=None):
        self.parts = parts
        if total:
            self.total = total
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        h = self.height()
        path = QPainterPath()
        path.addRoundedRect(QRectF(0, 0, self.width(), h), h / 2, h / 2)
        p.fillPath(path, Palette.q("sunken"))
        p.setClipPath(path)
        x = 0.0
        for i, v in enumerate(self.parts):
            w = self.width() * v / max(self.total, 0.1)
            p.fillRect(QRectF(x, 0, w, h), QColor(VRAM_COLORS[i % len(VRAM_COLORS)]))
            x += w


class Dot(QWidget):
    """Titik status 8px. state: ok | warn | bad | none. pulse=True berkedip (sesi berjalan)."""

    def __init__(self, state="none", size=8):
        super().__init__()
        self.state = state
        self.setFixedSize(size + 6, size + 6)
        self._size = size
        self._pulse = False
        self._dim = False
        self._halo = False
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)

    def set_state(self, state, pulse=False, halo=False):
        self.state, self._halo = state, halo
        if pulse != self._pulse:
            self._pulse = pulse
            self._dim = False
            self._timer.start(700) if pulse else self._timer.stop()
        self.update()

    def _tick(self):
        self._dim = not self._dim
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        key = {"ok": "ok", "warn": "warn", "bad": "danger"}.get(self.state, "faint")
        c = QColor(Palette.c[key])
        r = QRectF(3, 3, self._size, self._size)
        if self._halo:
            halo = QColor(c)
            halo.setAlphaF(0.25)
            p.setPen(Qt.NoPen)
            p.setBrush(halo)
            p.drawEllipse(r.adjusted(-3, -3, 3, 3))
        if self._dim:
            c.setAlphaF(0.35)
        p.setPen(Qt.NoPen)
        p.setBrush(c)
        p.drawEllipse(r)


class StatusCircle(QLabel):
    """Lingkaran 26px berisi ✓ / ! (daftar kesiapan sistem)."""

    def __init__(self, state="ok", text=None):
        super().__init__()
        self.setFixedSize(26, 26)
        self.setAlignment(Qt.AlignCenter)
        self.set_state(state, text)
        theme_bus.changed.connect(lambda: self.set_state(self._state, self._text))

    def set_state(self, state, text=None):
        self._state, self._text = state, text
        fg, bg = {"ok": ("ok", "ok_soft"), "warn": ("warn", "warn_soft"), "bad": ("danger", "danger_soft"),
                  "wait": ("muted", "sunken")}[state]
        self.setText(text or {"ok": "✓", "wait": "…"}.get(state, "!"))
        self.setStyleSheet("background: {}; color: {}; border-radius: 13px; font-size: 13px; font-weight: 600;".format(
            Palette.c[bg], Palette.c[fg]))


class Banner(QFrame):
    def __init__(self, title="", text="", button_text=None):
        super().__init__()
        self.setObjectName("bannerWarn")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(14, 12, 14, 12)
        lay.setSpacing(12)
        lay.addWidget(label("⚠", "bannerIcon"))
        col = QVBoxLayout()
        col.setSpacing(0)
        self.title = label(title, "bannerTitle", wrap=True)
        self.text = label(text, wrap=True)
        col.addWidget(self.title)
        col.addWidget(self.text)
        lay.addLayout(col, 1)
        self.button = button(button_text or "", "btnWarn")
        self.button.setVisible(bool(button_text))
        lay.addWidget(self.button)

    def set(self, title, text, button_text=None):
        self.title.setText(title)
        self.text.setText(text)
        self.button.setVisible(bool(button_text))
        if button_text:
            self.button.setText(button_text)


class Badge(QWidget):
    """Pil kecil berisi angka/tanda (badge menu). warn=True: kuning."""

    def __init__(self):
        super().__init__()
        self.text, self.warn = "", False
        self.setFixedHeight(18)
        self.hide()

    def set(self, text, warn=False):
        self.text, self.warn = str(text), warn
        self.setVisible(bool(self.text))
        self.setFixedWidth(max(18, self.fontMetrics().horizontalAdvance(self.text) + 14))
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        p.setBrush(Palette.q("warn_soft" if self.warn else "sunken"))
        p.drawRoundedRect(QRectF(0, 0, self.width(), 18), 9, 9)
        p.setPen(Palette.q("warn" if self.warn else "muted"))
        p.setFont(font(11, QFont.DemiBold))
        p.drawText(QRectF(0, 0, self.width(), 18), Qt.AlignCenter, self.text)


class NavButton(QPushButton):
    def __init__(self, icon_name, text):
        super().__init__()
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedHeight(38)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 0, 10, 0)
        lay.setSpacing(10)
        self.icon_label = IconLabel(icon_name, "muted", 18)
        self.text_label = label(text, "navText")
        self.live = Dot("ok")
        self.live.hide()
        self.badge = Badge()
        for w in (self.icon_label, self.text_label, self.live, self.badge):
            w.setAttribute(Qt.WA_TransparentForMouseEvents)
        lay.addWidget(self.icon_label)
        lay.addWidget(self.text_label)
        lay.addStretch(1)
        lay.addWidget(self.live, 0, Qt.AlignVCenter)
        lay.addWidget(self.badge, 0, Qt.AlignVCenter)
        self.toggled.connect(self._sync)
        theme_bus.changed.connect(self._sync)
        self._sync()

    def _color(self, key):
        self.icon_label.set_color(key)
        self.text_label.setStyleSheet("color: {}; font-weight: 500; background: transparent;".format(Palette.c[key]))

    def _sync(self, *_):
        self._color("accent_text" if self.isChecked() else "muted")

    def enterEvent(self, e):
        if not self.isChecked():
            self._color("text")
        super().enterEvent(e)

    def leaveEvent(self, e):
        self._sync()
        super().leaveEvent(e)

    def set_badge(self, text, warn=False):
        self.badge.set(text, warn)

    def set_live(self, on):
        self.live.setVisible(on)
        self.live.set_state("ok", halo=True)


def tag(text, nc=False):
    t = label(text, "tagNc" if nc else "tag")
    t.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
    return t


class Chip(QLabel):
    def __init__(self, text):
        super().__init__(text)
        self.setObjectName("chip")


class Route(QFrame):
    """Rute suara: [Zoom] → [Whisper] → [Gemma] → [Subtitle] (membungkus ke baris baru jika sempit)."""

    def __init__(self, items):
        super().__init__()
        self.setObjectName("route")
        self.flow = FlowLayout(self, margin=10, spacing=6)
        self.chips = []
        for i, text in enumerate(items):
            if i:
                self.flow.addWidget(label("→", "arrow"))
            c = Chip(text)
            self.chips.append(c)
            self.flow.addWidget(c)


# ---------------------------------------------------------------- tata letak
from PySide6.QtWidgets import QLayout  # noqa: E402
from PySide6.QtCore import QPoint, QRect  # noqa: E402


class FlowLayout(QLayout):
    def __init__(self, parent=None, margin=0, spacing=8):
        super().__init__(parent)
        self.setContentsMargins(margin, margin, margin, margin)
        self._spacing = spacing
        self._items = []

    def addItem(self, item):
        self._items.append(item)

    def count(self):
        return len(self._items)

    def itemAt(self, i):
        return self._items[i] if 0 <= i < len(self._items) else None

    def takeAt(self, i):
        return self._items.pop(i) if 0 <= i < len(self._items) else None

    def expandingDirections(self):
        return Qt.Orientations(0)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, w):
        return self._do(QRect(0, 0, w, 0), True)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._do(rect, False)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        s = QSize()
        for it in self._items:
            s = s.expandedTo(it.minimumSize())
        m = self.contentsMargins()
        return s + QSize(m.left() + m.right(), m.top() + m.bottom())

    def _do(self, rect, test):
        m = self.contentsMargins()
        r = rect.adjusted(m.left(), m.top(), -m.right(), -m.bottom())
        x, y, line_h = r.x(), r.y(), 0
        for it in self._items:
            hint = it.sizeHint()
            nx = x + hint.width() + self._spacing
            if nx - self._spacing > r.right() + 1 and line_h > 0:
                x, y = r.x(), y + line_h + self._spacing
                nx, line_h = x + hint.width() + self._spacing, 0
            if not test:
                # Pusatkan vertikal dalam satu baris (panah lebih pendek dari chip).
                it.setGeometry(QRect(QPoint(x, y), hint))
            x, line_h = nx, max(line_h, hint.height())
        return y + line_h - rect.y() + m.bottom()


class AutoGrid(QWidget):
    """Grid kolom otomatis seperti CSS repeat(auto-fill, minmax(min_w, 1fr))."""

    def __init__(self, min_w=132, item_h=92, gap=10):
        super().__init__()
        self.min_w, self.item_h, self.gap = min_w, item_h, gap
        self.items = []
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)

    def clear(self):
        for w in self.items:
            w.setParent(None)
            w.deleteLater()
        self.items = []
        self._relayout()

    def add(self, w):
        w.setParent(self)
        w.show()
        self.items.append(w)
        self._relayout()

    def _cols(self, width):
        return max(1, (width + self.gap) // (self.min_w + self.gap))

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, w):
        rows = (len(self.items) + self._cols(w) - 1) // self._cols(w)
        return max(0, rows * self.item_h + (rows - 1) * self.gap)

    def sizeHint(self):
        return QSize(600, self.heightForWidth(max(self.width(), 600)))

    def resizeEvent(self, e):
        self._relayout()

    def _relayout(self):
        w = max(self.width(), 1)
        cols = self._cols(w)
        iw = (w - self.gap * (cols - 1)) / cols
        for i, item in enumerate(self.items):
            r, c = divmod(i, cols)
            item.setGeometry(round(c * (iw + self.gap)), r * (self.item_h + self.gap), round(iw), self.item_h)
        self.setMinimumHeight(self.heightForWidth(w))
        self.updateGeometry()


# ---------------------------------------------------------------- kartu sumber & model
class SourceCard(QAbstractButton):
    """Kartu aplikasi sumber suara (ikon exe asli, nama, keterangan, equalizer saat aktif)."""

    def __init__(self, key, title, sub, pixmap=None, letter=None, color="#64748b"):
        super().__init__()
        self.key, self.title, self.sub = key, title, sub
        self.pm, self.letter, self.color = pixmap, letter, color
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self._playing = False
        self._phase = 0
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._hover = False

    def set_playing(self, on):
        self._playing = on
        self._timer.start(60) if on else self._timer.stop()
        self.update()

    def _tick(self):
        self._phase += 1
        self.update()

    def enterEvent(self, e):
        self._hover = True
        self.update()

    def leaveEvent(self, e):
        self._hover = False
        self.update()

    def paintEvent(self, e):
        import math

        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(1.5, 1.5, -1.5, -1.5)
        on = self.isChecked()
        if on:
            ring = QColor(Palette.c["accent"])
            ring.setAlphaF(0.16)
            p.setPen(QPen(ring, 3))
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(r, 12, 12)
        border = Palette.c["accent"] if on else (mix(Palette.c["line"], Palette.c["accent"], 0.45) if self._hover else Palette.c["line"])
        p.setPen(QPen(QColor(border), 1))
        p.setBrush(Palette.q("card" if on else "win"))
        p.drawRoundedRect(r, 12, 12)
        # logo
        lr = QRectF(13, 13, 30, 30)
        if self.pm is not None and not self.pm.isNull():
            p.drawPixmap(lr.toRect(), self.pm)
        else:
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(self.color))
            p.drawRoundedRect(lr, 8, 8)
            p.setPen(QColor("#ffffff"))
            p.setFont(font(13, QFont.Bold))
            p.drawText(lr, Qt.AlignCenter, self.letter or self.title[:1].upper())
        # teks
        p.setPen(Palette.q("text"))
        p.setFont(font(13, QFont.DemiBold))
        fm = p.fontMetrics()
        p.drawText(QRectF(13, 51, self.width() - 26, 18), Qt.AlignLeft | Qt.AlignVCenter,
                   fm.elidedText(self.title, Qt.ElideRight, self.width() - 26))
        p.setPen(Palette.q("muted"))
        p.setFont(font(11))
        fm = p.fontMetrics()
        p.drawText(QRectF(13, 69, self.width() - 26, 16), Qt.AlignLeft | Qt.AlignVCenter,
                   fm.elidedText(self.sub, Qt.ElideRight, self.width() - 26))
        # equalizer
        p.setPen(Qt.NoPen)
        p.setBrush(Palette.q("ok"))
        for i in range(3):
            h = 3 + (9 * (0.5 + 0.5 * math.sin(self._phase * 0.45 + i * 1.4)) if self._playing else 0)
            p.drawRoundedRect(QRectF(self.width() - 26 + i * 5, 26 - h, 3, h), 1, 1)

    def sizeHint(self):
        return QSize(132, 92)


class ModelCard(QAbstractButton):
    def __init__(self, name, size, accuracy, speed, note=""):
        super().__init__()
        self.name, self.size, self.acc, self.spd, self.note = name, size, accuracy, speed, note
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setMinimumHeight(118)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(1.5, 1.5, -1.5, -1.5)
        on = self.isChecked()
        if on:
            ring = QColor(Palette.c["accent"])
            ring.setAlphaF(0.15)
            p.setPen(QPen(ring, 3))
            p.drawRoundedRect(r, 10, 10)
        p.setPen(QPen(QColor(Palette.c["accent" if on else "line"]), 1))
        p.setBrush(Palette.q("card" if on else "win"))
        p.drawRoundedRect(r, 10, 10)
        x, w = 11, self.width() - 22
        p.setPen(Palette.q("text"))
        p.setFont(font(13, QFont.DemiBold))
        p.drawText(QRectF(x, 10, w, 18), Qt.AlignLeft | Qt.AlignVCenter, self.name)
        p.setPen(Palette.q("muted"))
        p.setFont(font(11))
        p.drawText(QRectF(x, 27, w, 16), Qt.AlignLeft | Qt.AlignVCenter,
                   self.size + (" · " + self.note if self.note else ""))
        for row, (title, val, key) in enumerate((("Akurasi", self.acc, "accent"), ("Kecepatan", self.spd, "accent2"))):
            y = 50 + row * 30
            p.setPen(Palette.q("muted"))
            p.drawText(QRectF(x, y, w, 15), Qt.AlignLeft | Qt.AlignVCenter, title)
            bw = (w - 4 * 3) / 5
            p.setPen(Qt.NoPen)
            for i in range(5):
                p.setBrush(Palette.q(key if i < val else "line_strong"))
                p.drawRoundedRect(QRectF(x + i * (bw + 3), y + 18, bw, 4), 2, 2)


class Stage(QFrame):
    """Satu tahap pada alur suara (Mic → Teks → Terjemah → Suara → Rapat)."""

    def __init__(self, icon_name, title, sub):
        super().__init__()
        self._active = False
        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 12, 10, 12)
        lay.setSpacing(2)
        self.icon = IconLabel(icon_name, "muted", 20)
        lay.addWidget(self.icon, 0, Qt.AlignHCenter)
        lay.addSpacing(4)
        t = label(title)
        t.setStyleSheet("font-size: 12px; font-weight: 600;")
        t.setAlignment(Qt.AlignCenter)
        self.sub = label(sub, "small")
        self.sub.setStyleSheet("font-size: 11px;")
        self.sub.setAlignment(Qt.AlignCenter)
        lay.addWidget(t)
        lay.addWidget(self.sub)

    def set_active(self, on):
        self._active = on
        self.icon.set_color("speak" if on else "muted")
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        if self._active:
            p.setPen(QPen(Palette.q("speak"), 1))
            p.setBrush(QColor(mix(Palette.c["card"], Palette.c["speak"], 0.10)))
        else:
            p.setPen(QPen(Palette.q("line"), 1))
            p.setBrush(Palette.q("sunken"))
        p.drawRoundedRect(r, 12, 12)


class Wave(QWidget):
    """Bentuk gelombang sampel suara (batang)."""

    def __init__(self, bars=64):
        super().__init__()
        self.values = [0.2 + 0.78 * abs(__import__("math").sin(i * .55) * __import__("math").cos(i * .19)) for i in range(bars)]
        self.setFixedHeight(36)

    def set_audio(self, audio):
        import numpy as np

        if audio is None or len(audio) == 0:
            return
        n = len(self.values)
        chunks = np.array_split(np.abs(audio), n)
        peaks = np.array([c.max() if len(c) else 0 for c in chunks])
        peaks = peaks / (peaks.max() + 1e-9)
        self.values = [0.12 + 0.88 * float(v) for v in peaks]
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        n = len(self.values)
        gap = 2
        bw = (self.width() - gap * (n - 1)) / n
        c = QColor(Palette.c["speak"])
        c.setAlphaF(0.6)
        p.setPen(Qt.NoPen)
        p.setBrush(c)
        for i, v in enumerate(self.values):
            h = self.height() * v
            p.drawRoundedRect(QRectF(i * (bw + gap), (self.height() - h) / 2, bw, h), 1.5, 1.5)


class RoundButton(QAbstractButton):
    """Tombol bulat 38px (putar sampel suara)."""

    def __init__(self, icon_name="play", color_key="speak"):
        super().__init__()
        self._icon, self._key = icon_name, color_key
        self.setFixedSize(38, 38)
        self.setCursor(Qt.PointingHandCursor)

    def set_icon(self, name):
        self._icon = name
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        p.setBrush(Palette.q(self._key))
        p.drawEllipse(QRectF(0, 0, 38, 38))
        p.drawPixmap(12, 12, icons.pixmap(self._icon, "#ffffff", 14))


class Progress(QWidget):
    def __init__(self, color_key="danger"):
        super().__init__()
        self._v, self._key = 0.0, color_key
        self.setFixedHeight(6)

    def set_value(self, v):
        self._v = max(0.0, min(1.0, v))
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        p.setBrush(Palette.q("sunken"))
        p.drawRoundedRect(QRectF(0, 0, self.width(), 6), 3, 3)
        if self._v > 0:
            p.setBrush(Palette.q(self._key))
            p.drawRoundedRect(QRectF(0, 0, self.width() * self._v, 6), 3, 3)


class StepBar(QWidget):
    def __init__(self, n):
        super().__init__()
        self.n, self.cur = n, 0
        self.setFixedHeight(4)

    def set_step(self, i):
        self.cur = i
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        gap = 6
        w = (self.width() - gap * (self.n - 1)) / self.n
        for i in range(self.n):
            p.setBrush(Palette.q("accent" if i <= self.cur else "line"))
            p.drawRoundedRect(QRectF(i * (w + gap), 0, w, 4), 2, 2)


# ---------------------------------------------------------------- transkrip
class Avatar(QWidget):
    def __init__(self, direction):
        super().__init__()
        self.key = "listen" if direction == "in" else "speak"
        self.icon = "ear" if direction == "in" else "mic"
        self.setFixedSize(30, 30)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        c = QColor(Palette.c[self.key])
        c.setAlphaF(0.15)
        p.setPen(Qt.NoPen)
        p.setBrush(c)
        p.drawEllipse(QRectF(0, 0, 30, 30))
        p.drawPixmap(7, 7, icons.pixmap(self.icon, Palette.c[self.key], 16))


class MsgItem(QFrame):
    def __init__(self, direction, original, translation, time_text="", meta=""):
        super().__init__()
        self.setObjectName("msg")
        self.direction = direction
        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 10, 10, 10)
        lay.setSpacing(10)
        lay.addWidget(Avatar(direction), 0, Qt.AlignTop)
        col = QVBoxLayout()
        col.setSpacing(1)
        self.o = label(original, "msgO", wrap=True)
        self.t = label(translation, "msgT", wrap=True)
        for w in (self.o, self.t):
            w.setTextInteractionFlags(Qt.TextSelectableByMouse)
            w.setTextFormat(Qt.PlainText)
        col.addWidget(self.o)
        col.addWidget(self.t)
        self.meta = label(meta, "msgMeta", rich=True)
        self.meta.setVisible(bool(meta))
        col.addSpacing(2)
        col.addWidget(self.meta)
        lay.addLayout(col, 1)
        self.time = label(time_text, "msgTime")
        lay.addWidget(self.time, 0, Qt.AlignTop)

    def update_text(self, original, translation, meta=None):
        """Perbarui baris yang sama (subtitle langsung: teks sementara -> final)."""
        self.o.setText(original)
        self.t.setText(translation or "…")
        if meta is not None:
            self.meta.setText(meta)
            self.meta.setVisible(bool(meta))


class Feed(QScrollArea):
    def __init__(self, empty_text, max_height=340, empty_icon=True, margins=(0, 0, 4, 0)):
        super().__init__()
        self.setObjectName("feed")
        self.setWidgetResizable(True)
        self.viewport().setAutoFillBackground(False)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setFrameShape(QFrame.NoFrame)
        if max_height:
            self.setMaximumHeight(max_height)
        inner = QWidget()
        inner.setObjectName("feedInner")
        self.lay = QVBoxLayout(inner)
        self.lay.setContentsMargins(*margins)
        self.lay.setSpacing(4)
        self.lay.addStretch(1)
        self.setWidget(inner)
        self.items = []
        self.filter = "all"
        self.empty = QWidget()
        el = QVBoxLayout(self.empty)
        el.setContentsMargins(12, 34, 12, 34)
        if empty_icon:
            el.addWidget(IconLabel("chat", "faint", 34), 0, Qt.AlignHCenter)
        et = label(empty_text, "small", wrap=True, rich=True)
        et.setStyleSheet("font-size: 14px;")
        et.setAlignment(Qt.AlignCenter)
        el.addWidget(et)
        self.lay.insertWidget(0, self.empty)

    def clear(self):
        for it in self.items:
            it.setParent(None)
            it.deleteLater()
        self.items = []
        self.empty.show()

    def add(self, item, scroll=True):
        self.empty.hide()
        self.items.append(item)
        self.lay.insertWidget(self.lay.count() - 1, item)
        item.setVisible(self.filter in ("all", item.direction))
        if scroll:
            QTimer.singleShot(30, lambda: self.verticalScrollBar().setValue(self.verticalScrollBar().maximum()))

    def scroll_to_end(self):
        QTimer.singleShot(30, lambda: self.verticalScrollBar().setValue(self.verticalScrollBar().maximum()))

    def set_filter(self, f):
        self.filter = f
        for it in self.items:
            it.setVisible(f in ("all", it.direction))


# ---------------------------------------------------------------- baris pengaturan
class SettingRows(QWidget):
    """Daftar baris "judul + keterangan | kontrol" dengan garis pemisah, seperti .rows di mockup."""

    def __init__(self):
        super().__init__()
        self.lay = QVBoxLayout(self)
        self.lay.setContentsMargins(0, 0, 0, 0)
        self.lay.setSpacing(0)
        self._n = 0

    def add(self, title, sub=None, control=None, block=None):
        if self._n:
            self.lay.addWidget(separator())
        row = QWidget()
        if block is not None:
            rl = QVBoxLayout(row)
            rl.setContentsMargins(0, 12 if self._n else 0, 0, 12)
            rl.addWidget(block)
        else:
            rl = QHBoxLayout(row)
            rl.setContentsMargins(0, 12 if self._n else 0, 0, 12)
            rl.setSpacing(14)
            col = QVBoxLayout()
            col.setSpacing(1)
            col.addWidget(label(title, "rowTitle", wrap=True))
            if sub:
                col.addWidget(label(sub, "rowSub", wrap=True))
            rl.addLayout(col, 1)
            if control is not None:
                if isinstance(control, QWidget):
                    rl.addWidget(control, 0, Qt.AlignVCenter)
                else:
                    rl.addLayout(control)
        self.lay.addWidget(row)
        self._n += 1
        return row


# ---------------------------------------------------------------- toast
class Toast(QFrame):
    def __init__(self, parent):
        super().__init__(parent)
        self.setObjectName("toast")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(16, 10, 16, 10)
        self.text = QLabel()
        lay.addWidget(self.text)
        self._fx = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self._fx)
        self._anim = QPropertyAnimation(self._fx, b"opacity", self)
        self._anim.setDuration(220)
        self._hide = QTimer(self)
        self._hide.setSingleShot(True)
        self._hide.timeout.connect(lambda: self._fade(0))
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.hide()

    def show_message(self, msg, ms=2400):
        self.text.setText(msg)
        self.adjustSize()
        par = self.parentWidget()
        self.move((par.width() - self.width()) // 2, par.height() - self.height() - 24)
        self.show()
        self.raise_()
        self._fade(1)
        self._hide.start(ms)

    def _fade(self, to):
        self._anim.stop()
        self._anim.setStartValue(self._fx.opacity())
        self._anim.setEndValue(to)
        self._anim.start()
