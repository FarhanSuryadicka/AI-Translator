"""Membaca file transkrip sesi (transcripts/*.txt) untuk halaman Riwayat, dan ekspor ke .srt.

Format baris yang ditulis pipeline.Session.emit():
    [HH:MM:SS] DENGAR (en) teks asli
               -> terjemahan
"""

import datetime
import os
import re
from dataclasses import dataclass, field

from .config import TRANSCRIPT_DIR

_LINE = re.compile(r"^\[(\d\d:\d\d:\d\d)\] (DENGAR|BICARA) \(([^)]*)\) (.*)$")
_NAME = re.compile(r"^(\d{4}-\d\d-\d\d)_(\d\d)(\d\d)(\d\d)\.txt$")


@dataclass
class Line:
    direction: str  # "in" (Dengar) | "out" (Bicara)
    time: str
    language: str
    original: str
    translation: str = ""


@dataclass
class Session:
    path: str
    started: datetime.datetime
    lines: list = field(default_factory=list)

    @property
    def title(self):
        return "Sesi " + self.started.strftime("%H:%M")

    @property
    def duration_min(self):
        if len(self.lines) < 2:
            return 0
        fmt = "%H:%M:%S"
        a = datetime.datetime.strptime(self.lines[0].time, fmt)
        b = datetime.datetime.strptime(self.lines[-1].time, fmt)
        return max(0, int((b - a).total_seconds() // 60))

    @property
    def pair(self):
        langs_in = {l.language.upper() for l in self.lines if l.direction == "in"}
        has_out = any(l.direction == "out" for l in self.lines)
        if has_out and langs_in:
            return "{} ⇄ ID".format("/".join(sorted(langs_in))[:7])
        if langs_in:
            return "{} → ID".format("/".join(sorted(langs_in))[:7])
        return "ID → …" if has_out else "—"

    def text(self):
        return "\n".join("[{}] {}\n-> {}".format(l.time, l.original, l.translation) for l in self.lines)


def parse(path):
    m = _NAME.match(os.path.basename(path))
    if m:
        started = datetime.datetime.strptime("{} {}:{}:{}".format(*m.groups()), "%Y-%m-%d %H:%M:%S")
    else:
        started = datetime.datetime.fromtimestamp(os.path.getmtime(path))
    sess = Session(path, started)
    with open(path, encoding="utf-8", errors="replace") as f:
        for raw in f:
            line = raw.rstrip("\n")
            hit = _LINE.match(line)
            if hit:
                t, tag, lang, text = hit.groups()
                sess.lines.append(Line("in" if tag == "DENGAR" else "out", t, lang, text))
            elif line.strip().startswith("->") and sess.lines:
                sess.lines[-1].translation = line.strip()[2:].strip()
    return sess


def sessions():
    """Semua sesi, terbaru dulu (sesi kosong dilewati)."""
    if not os.path.isdir(TRANSCRIPT_DIR):
        return []
    out = []
    for name in os.listdir(TRANSCRIPT_DIR):
        if name.endswith(".txt"):
            try:
                s = parse(os.path.join(TRANSCRIPT_DIR, name))
            except OSError:
                continue
            if s.lines:
                out.append(s)
    return sorted(out, key=lambda s: s.started, reverse=True)


def relative_day(dt):
    today = datetime.date.today()
    if dt.date() == today:
        day = "Hari ini"
    elif dt.date() == today - datetime.timedelta(days=1):
        day = "Kemarin"
    else:
        months = ["Jan", "Feb", "Mar", "Apr", "Mei", "Jun", "Jul", "Agu", "Sep", "Okt", "Nov", "Des"]
        day = "{} {}".format(dt.day, months[dt.month - 1])
    return "{} · {}".format(day, dt.strftime("%H:%M"))


def to_srt(sess):
    """Subtitle .srt: tiap kalimat tampil sampai kalimat berikutnya (maks. 6 detik)."""
    def secs(t):
        h, m, s = map(int, t.split(":"))
        return h * 3600 + m * 60 + s

    def stamp(x):
        return "{:02d}:{:02d}:{:02d},000".format(int(x // 3600), int(x % 3600 // 60), int(x % 60))

    base = secs(sess.lines[0].time) if sess.lines else 0
    blocks = []
    for i, l in enumerate(sess.lines):
        start = secs(l.time) - base
        nxt = secs(sess.lines[i + 1].time) - base if i + 1 < len(sess.lines) else start + 4
        end = min(max(nxt, start + 1), start + 6)
        blocks.append("{}\n{} --> {}\n{}\n".format(i + 1, stamp(start), stamp(end), l.translation or l.original))
    return "\n".join(blocks)
