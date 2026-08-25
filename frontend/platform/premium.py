# -*- coding: utf-8 -*-
"""Premium shared UI toolkit for stock-classroom — THEME-AWARE.

Reads all colours/stops from the ACTIVE theme (frontend.platform.theme), so a
theme switch re-styles every premium widget (gradient cards, section titles,
count-up labels, gauges, split bars) without per-plugin edits.

Public: PAL (synced to the active theme), ACCENT, card_qss(), value_ss(),
label_ss(), pill_ss(), SectionTitle, CountUpLabel, BreadthGauge, SplitBar,
_tilt_color().
"""

import math

from PyQt5.QtCore import Qt, QTimer, QRectF, QPointF
from PyQt5.QtWidgets import QLabel, QFrame, QWidget, QHBoxLayout
from PyQt5.QtGui import QPainter, QColor, QPen, QFont, QLinearGradient, QPainterPath

from . import theme as _th

# ── Palette, synced from the active theme ──────────────────────
PAL = {
    "bg": "#0B0D11", "c_top": "#15181D", "c_mid": "#12151A", "c_bot": "#0E1115",
    "border_lo": "#232830", "border_hi": "#2E343C", "accent": "#7AA2F7",
    "text": "#E8EAED", "sub": "#9AA3B0", "faint": "#5C6670",
    "up": "#E5484D", "down": "#3FB950", "grid": "#1D222A", "axis": "#2E343C",
}

# maps premium key -> theme token path (callables so they re-read live)
__MAP = {
    "bg": lambda t: t["bg"],
    "c_top": lambda t: t["card_stops"][0],
    "c_mid": lambda t: t["card_stops"][1],
    "c_bot": lambda t: t["card_stops"][2],
    "border_lo": lambda t: t["card_border"],
    "border_hi": lambda t: t["card_border_top"],
    "accent": lambda t: t["accent"],
    "text": lambda t: t["text"],
    "sub": lambda t: t["sub"],
    "faint": lambda t: t["faint"],
    "up": lambda t: t["up"],
    "down": lambda t: t["down"],
    "grid": lambda t: t["border_soft"],
    "axis": lambda t: t["border_top"],
}


def _sync_pal():
    t = _th.current_theme()
    for k, fn in __MAP.items():
        PAL[k] = fn(t)


_sync_pal()


def _tkey(key):
    return _th.current_theme()[key]


def card_qss(name="card", radius: int = None) -> str:
    """Vertical matte gradient card + top-highlight bevel (+ hover edge)."""
    r = _tkey("radius_card") if radius is None else radius
    s = _tkey("card_stops")
    return (
        f"QFrame#{name}{{background:qlineargradient(x1:0,y1:0,x2:0,y2:1,"
        f"stop:0 {s[0]},stop:0.55 {s[1]},stop:1 {s[2]});"
        f"border:1px solid {_tkey('card_border')};border-top:1px solid {_tkey('card_border_top')};"
        f"border-radius:{_th.dps(r)};}}"
        f"QFrame#{name}:hover{{border-top:1px solid {_tkey('card_hover_border')};border-color:{_tkey('raised')};}}"
    )


def value_ss(color=None, size=17) -> str:
    """Light-weight wide number style (Segoe UI Light, font-weight 300)."""
    return (
        f"color:{color or _tkey('text')};font-size:{_th.fs(size)};font-weight:300;background:transparent;"
        f"font-family:'Segoe UI Light','Microsoft YaHei UI Light','Microsoft YaHei',sans-serif;"
        f"letter-spacing:{_th.dp(0.5)}px;"
    )


def label_ss(size=10, color=None) -> str:
    """Small unit label — widened letter-spacing for a refined look."""
    return (
        f"color:{color or _tkey('sub')};font-size:{_th.fs(size)};font-weight:500;"
        f"letter-spacing:{_th.dp(1.5)}px;background:transparent;"
    )


def pill_ss(color, alpha=0.12, border_alpha=0.35) -> str:
    """Tinted status pill (bg rgba + border) — restrained, not flat text."""
    try:
        r, g, b = _hex_rgb(color)
    except Exception:
        r, g, b = 212, 165, 116
    return (
        f"background:rgba({r},{g},{b},{alpha});color:{color};"
        f"border:1px solid rgba({r},{g},{b},{border_alpha});"
        f"border-radius:{_th.dps(5)};padding:{_th.dp(2)} {_th.dp(9)};"
    )


def _hex_rgb(c):
    c = c.strip().lstrip("#")
    if len(c) == 3:
        c = "".join(ch * 2 for ch in c)
    return int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16)


def _tilt_color(tilt):
    t = _th.current_theme()
    if tilt == "value_favorable" or tilt == "favorable":
        return t["down"]
    if tilt == "value_headwind" or tilt == "headwind":
        return t["up"]
    return t["accent"]


class SectionTitle(QWidget):
    """Accent short-bar + letter-spaced label section heading."""

    def __init__(self, text, parent=None, size=12):
        super().__init__(parent)
        lo = QHBoxLayout(self)
        lo.setContentsMargins(0, 0, 0, 0)
        lo.setSpacing(_th.dp(7))
        bar = QFrame()
        bar.setFixedSize(_th.dp(3), _th.dp(15))
        bar.setStyleSheet(
            f"background:{_tkey('accent')};border-radius:{_th.dp(1)}px;border:none;")
        lo.addWidget(bar)
        self._lbl = QLabel(text)
        self._lbl.setStyleSheet(
            f"color:{_tkey('text')};font-size:{_th.fs(size)};font-weight:600;"
            f"letter-spacing:{_th.dp(2)}px;background:transparent;")
        lo.addWidget(self._lbl)
        lo.addStretch()

    def setText(self, text):
        self._lbl.setText(text)


class CountUpLabel(QLabel):
    """Animated count-up numeric label (ease-out cubic, step-based)."""

    def __init__(self, parent=None, fmt=None, duration=800, max_chars=30):
        super().__init__(parent)
        self._fmt = fmt or (lambda v: f"{v:,.0f}")
        self._interval = 16
        self._steps = max(int(duration / self._interval), 1)
        self._step = 0
        self._max_chars = max_chars
        self._cur = 0.0
        self._target = 0.0
        self._from = 0.0
        self._last = None
        self._timer = QTimer(self)
        self._timer.setInterval(self._interval)
        self._timer.timeout.connect(self._tick)
        self.setStyleSheet(value_ss())
        self.setText(self._fmt(0.0))

    def _tick(self):
        self._step += 1
        t = self._step / self._steps
        if t >= 1.0:
            self._timer.stop()
            self._cur = self._target
            self.setText(self._fmt(self._target)[: self._max_chars])
            return
        e = 1.0 - (1.0 - t) ** 3
        self._cur = self._from + (self._target - self._from) * e
        self.setText(self._fmt(self._cur)[: self._max_chars])

    def animate_to(self, target, fmt=None):
        if fmt is not None:
            self._fmt = fmt
        target = float(target)
        if self._last is not None and abs(target - self._last) < 1e-9:
            self.setText(self._fmt(target)[: self._max_chars])
            return
        self._last = target
        self._from = self._cur
        self._target = target
        self._step = 0
        self._timer.start()

    def set_immediate(self, value, fmt=None):
        if fmt is not None:
            self._fmt = fmt
        self._cur = float(value)
        self._last = float(value)
        self._timer.stop()
        self.setText(self._fmt(self._cur)[: self._max_chars])


class BreadthGauge(QWidget):
    """Semicircular gauge for a 0-1 fraction (破年线占比 / 市场宽度)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._value = 0.5
        self._tilt = "value_neutral"
        self.setMinimumHeight(_th.dp(96))

    def set_value(self, value, tilt="value_neutral"):
        self._value = max(0.0, min(1.0, float(value or 0.0)))
        self._tilt = tilt or "value_neutral"
        self.update()

    def paintEvent(self, _ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        if w < 30 or h < 30:
            p.end()
            return
        t = _th.current_theme()
        cx = w / 2.0
        cy = h * 0.82
        radius = min(w * 0.42, h * 0.72)
        rect = QRectF(cx - radius, cy - radius, radius * 2, radius * 2)
        span = 180.0
        thick = max(radius * 0.16, _th.dp(3))
        arc = int(-span * 16)

        p.setPen(QPen(QColor(t["border_top"]), thick, Qt.SolidLine, Qt.RoundCap))
        p.drawArc(rect, 180 * 16, arc)

        tick = QPen(QColor(t["faint"]), max(1.0, radius * 0.02))
        for frac in (0.5, 0.6):
            a = math.pi - math.pi * frac
            x1 = cx + math.cos(a) * radius
            y1 = cy - math.sin(a) * radius
            x2 = cx + math.cos(a) * (radius - thick * 0.9)
            y2 = cy - math.sin(a) * (radius - thick * 0.9)
            p.setPen(tick)
            p.drawLine(int(x1), int(y1), int(x2), int(y2))

        color = QColor(_tilt_color(self._tilt))
        p.setPen(QPen(color, thick, Qt.SolidLine, Qt.RoundCap))
        p.drawArc(rect, 180 * 16, int(-span * self._value * 16))

        a = math.pi - math.pi * self._value
        nx = cx + math.cos(a) * (radius - thick)
        ny = cy - math.sin(a) * (radius - thick)
        p.setPen(QPen(QColor(t["text"]), max(1.5, radius * 0.03), Qt.SolidLine, Qt.RoundCap))
        p.drawLine(int(cx), int(cy - radius * 0.10), int(nx), int(ny))
        p.setBrush(QColor(t["accent"]))
        p.setPen(Qt.NoPen)
        p.drawEllipse(QRectF(nx - 3, ny - 3, 6, 6))

        p.setFont(QFont("Segoe UI Light", int(max(radius * 0.24, 12))))
        p.setPen(QColor(t["text"]))
        p.drawText(QRectF(0, cy - radius * 0.5, w, radius * 0.5),
                   Qt.AlignCenter, "{:.0%}".format(self._value))
        p.setFont(QFont("Segoe UI", 8))
        p.setPen(QColor(t["faint"]))
        p.drawText(QRectF(0, cy + radius * 0.15, w, 16), Qt.AlignCenter,
                   "← {:.0f}%  突破年线 {:.0f}% →".format(self._value * 100, (1 - self._value) * 100))
        p.end()


class SplitBar(QWidget):
    """Horizontal stacked composition bar — up / down / flat share."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._up = self._dn = self._flat = 0
        self.setMinimumHeight(_th.dp(24))

    def set_data(self, up, dn, flat):
        self._up, self._dn, self._flat = int(up or 0), int(dn or 0), int(flat or 0)
        self.update()

    def paintEvent(self, _ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        if w < 40 or h < 10:
            p.end()
            return
        t = _th.current_theme()
        total = self._up + self._dn + self._flat
        seg_h = min(h - 6, _th.dp(12))
        y = (h - seg_h) / 2.0
        x = 0.0
        r = min(seg_h / 2, _th.dp(5))
        if total <= 0:
            p.setBrush(QColor(t["border_top"]))
            p.setPen(Qt.NoPen)
            p.drawRoundedRect(QRectF(x, y, w, seg_h), r, r)
            p.end()
            return
        for value, ck in ((self._up, "up"), (self._dn, "down"), (self._flat, "faint")):
            if value <= 0:
                continue
            seg_w = w * value / total
            p.setBrush(QColor(t[ck]))
            p.setPen(Qt.NoPen)
            p.drawRoundedRect(QRectF(x, y, seg_w, seg_h), r, r)
            x += seg_w
        p.setFont(QFont("Segoe UI", 8))
        if self._up:
            p.setPen(QColor(t["up"]))
            p.drawText(QRectF(0, y, w * self._up / total, seg_h),
                       Qt.AlignLeft | Qt.AlignVCenter, "涨 {:.0%}".format(self._up / total))
        if self._dn:
            p.setPen(QColor(t["down"]))
            p.drawText(QRectF(w * self._up / total, y, w * self._dn / total, seg_h),
                       Qt.AlignCenter | Qt.AlignVCenter, "跌 {:.0%}".format(self._dn / total))
        if self._flat:
            p.setPen(QColor(t["faint"]))
            p.drawText(QRectF(w * (self._up + self._dn) / total, y, w * self._flat / total, seg_h),
                       Qt.AlignRight | Qt.AlignVCenter, "{:.0%}".format(self._flat / total))
        p.end()


class MachinedWell(QFrame):
    """Theme-reactive card frame.

    paintEvent draws the card background itself from the ACTIVE theme every
    paint, so a theme switch repaints cards instantly without rebuilding them.
    In Obsidian it layers a real machined-metal well (vertical sheen + top edge
    highlight + 1px inner groove) on top — the QSS-only path can't express that
    depth. Other themes get the themed matte gradient + top-highlight bevel.
    """

    def __init__(self, name="card", radius=None, parent=None):
        super().__init__(parent)
        self.setObjectName(name)
        self._radius = _tkey("radius_card") if radius is None else radius
        self.setAttribute(Qt.WA_StyledBackground, True)

    def retheme(self):
        self.update()

    def paintEvent(self, ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        t = _th.current_theme()
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        radius = min(max(self._radius, 2), r.width() / 2, r.height() / 2)
        path = QPainterPath()
        path.addRoundedRect(r, radius, radius)

        # themed matte gradient background (top -> mid -> bottom)
        g = QLinearGradient(0, 0, 0, h)
        g.setColorAt(0.0, QColor(t["card_stops"][0]))
        g.setColorAt(0.5, QColor(t["card_stops"][1]))
        g.setColorAt(1.0, QColor(t["card_stops"][2]))
        p.fillPath(path, g)

        # border + top-highlight bevel
        p.setPen(QPen(QColor(t["card_border"]), 1))
        p.setBrush(Qt.NoBrush)
        p.drawPath(path)
        if t["card_hover_border"]:
            p.setPen(QPen(QColor(t["card_border_top"]), 1))
            top = QPainterPath()
            top.addRoundedRect(r.adjusted(0, 0, 0, -r.height() + 4), radius, radius)
            p.drawPath(top)

        if _th.theme_key() == "obsidian":
            # machined metal: vertical sheen (top light -> bottom shadow)
            sheen = QLinearGradient(0, 0, 0, h)
            sheen.setColorAt(0.0, QColor(255, 255, 255, 20))
            sheen.setColorAt(0.35, QColor(255, 255, 255, 0))
            sheen.setColorAt(0.65, QColor(0, 0, 0, 0))
            sheen.setColorAt(1.0, QColor(0, 0, 0, 74))
            p.fillPath(path, sheen)
            # thin top edge highlight
            p.setPen(QPen(QColor(255, 255, 255, 15), 1))
            inner = QPainterPath()
            inner.addRoundedRect(QRectF(r.x() + 1, r.y() + 1, r.width() - 2, r.height() - 2),
                                 max(radius - 1, 0), max(radius - 1, 0))
            p.setBrush(Qt.NoBrush)
            p.drawPath(inner)
            # inner groove (sunk cut line)
            groove = QPainterPath()
            groove.addRoundedRect(QRectF(r.x() + 2.5, r.y() + 2.5, r.width() - 5, r.height() - 5),
                                  max(radius - 2.5, 0), max(radius - 2.5, 0))
            p.setPen(QPen(QColor(0, 0, 0, 110), 1))
            p.drawPath(groove)
        p.end()

        super().paintEvent(ev)


def well(name="card", radius=None, parent=None) -> QFrame:
    """Create a theme-reactive card frame; paints a real machined well in Obsidian."""
    return MachinedWell(name, radius, parent)
