# -*- coding: utf-8 -*-
"""Premium shared UI toolkit for stock-classroom.

Single source for the '高级感' design language used across plugins:
palette, gradient card QSS, gold-section-title, and the count-up label.

Mirrors the research panel's _PAL / _CARD_QSS / light-numbers look so the
trade companion, datacenter, and any new panel can inherit it without each
re-declaring colors or QSS (which previously drift apart).
"""

from PyQt5.QtCore import Qt, QTimer, QRectF
from PyQt5.QtWidgets import QLabel, QFrame, QWidget, QHBoxLayout
from PyQt5.QtGui import QPainter, QColor, QPen, QFont, QLinearGradient

import math

from .theme import dp, dps, fs, C_ACCENT, C_BORDER_SOFT

# ── Premium palette (deep grey-gold, restrained) ──────────────────
PAL = {
    "bg": "#0D1117", "c_top": "#1D2431", "c_mid": "#161C27", "c_bot": "#121720",
    "border_lo": "#10141B", "border_hi": "#333D4A", "accent": "#D4A574",
    "text": "#E6EDF3", "sub": "#8B949E", "faint": "#6E7681",
    "up": "#E5484D", "down": "#3FB950",
    # brightened soft for charts/grids
    "grid": "#1A2028", "axis": "#2A3340",
}

ACCENT = PAL["accent"]


def card_qss(name="card", radius=10) -> str:
    """Vertical matte gradient card + top-highlight bevel (+ hover gold edge).

    Use on a QFrame: `f.setObjectName(name); f.setStyleSheet(card_qss(name))`.
    NOTE: QSS braces are built by string concatenation — never .format() here.
    """
    return (
        f"QFrame#{name}{{background:qlineargradient(x1:0,y1:0,x2:0,y2:1,"
        f"stop:0 {PAL['c_top']},stop:0.55 {PAL['c_mid']},stop:1 {PAL['c_bot']});"
        f"border:1px solid {PAL['border_lo']};border-top:1px solid {PAL['border_hi']};"
        f"border-radius:{dps(radius)};}}"
        f"QFrame#{name}:hover{{border-top:1px solid {PAL['accent']};border-color:#2B3441;}}"
    )


def value_ss(color=None, size=17) -> str:
    """Light-weight wide number style (Segoe UI Light, font-weight 300)."""
    return (
        f"color:{color or PAL['text']};font-size:{fs(size)};font-weight:300;background:transparent;"
        f"font-family:'Segoe UI Light','Microsoft YaHei UI Light','Microsoft YaHei',sans-serif;"
        f"letter-spacing:{dp(0.5)}px;"
    )


def label_ss(size=10, color=None) -> str:
    """Small unit label — widened letter-spacing for a refined look."""
    return (
        f"color:{color or PAL['sub']};font-size:{fs(size)};font-weight:500;"
        f"letter-spacing:{dp(1.5)}px;background:transparent;"
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
        f"border-radius:{dps(5)};padding:{dps(2)} {dps(9)};"
    )


def _hex_rgb(c):
    c = c.strip().lstrip("#")
    if len(c) == 3:
        c = "".join(ch * 2 for ch in c)
    return int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16)


class SectionTitle(QWidget):
    """Gold short-bar + letter-spaced label section heading."""

    def __init__(self, text, parent=None, size=12):
        super().__init__(parent)
        lo = QHBoxLayout(self)
        lo.setContentsMargins(0, 0, 0, 0)
        lo.setSpacing(dp(7))
        bar = QFrame()
        bar.setFixedSize(dp(3), dp(15))
        bar.setStyleSheet(
            f"background:{PAL['accent']};border-radius:{dp(1)}px;border:none;")
        lo.addWidget(bar)
        self._lbl = QLabel(text)
        self._lbl.setStyleSheet(
            f"color:{PAL['text']};font-size:{fs(size)};font-weight:600;"
            f"letter-spacing:{dp(2)}px;background:transparent;")
        lo.addWidget(self._lbl)
        lo.addStretch()

    def setText(self, text):
        self._lbl.setText(text)


class CountUpLabel(QLabel):
    """Animated count-up numeric label (ease-out cubic, ~0.8s).

    `animate_to(value, fmt=None)` rides smoothly from the currently-displayed
    value to the new target (first call counts up from 0). `fmt` is a callable
    value -> str; default is thousands-separated integer. Repeated calls with
    the same target are a no-op (no churn on refresh).
    """

    def __init__(self, parent=None, fmt=None, duration=800, max_chars=30):
        super().__init__(parent)
        self._fmt = fmt or (lambda v: f"{v:,.0f}")
        self._interval = 16
        # step-based (not wall-clock): QTimer + time.monotonic resolution can be
        # unreliable on some hosts (t never reached 1.0). Stepping by count
        # guarantees convergence to the exact target.
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
        # ease-out cubic
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
        """Set instantly (no animation) — for empty/placeholder states."""
        if fmt is not None:
            self._fmt = fmt
        self._cur = float(value)
        self._last = float(value)
        self._timer.stop()
        self.setText(self._fmt(self._cur)[: self._max_chars])


def _tilt_color(tilt):
    if tilt == "value_favorable" or tilt == "favorable":
        return PAL["down"]
    if tilt == "value_headwind" or tilt == "headwind":
        return PAL["up"]
    return PAL["accent"]


class BreadthGauge(QWidget):
    """Semicircular gauge for a 0-1 fraction (e.g. 破年线占比 / 市场宽度).

    Arc colored by value-tilt (favorable=green, headwind=red, ACID accent), ticks
    at the 0.5 / 0.6 regime boundaries, + a needle and centered % readout.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._value = 0.5
        self._tilt = "value_neutral"
        self.setMinimumHeight(dp(96))

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
        cx = w / 2.0
        cy = h * 0.82
        radius = min(w * 0.42, h * 0.72)
        rect = QRectF(cx - radius, cy - radius, radius * 2, radius * 2)
        span = 180.0
        thick = max(radius * 0.16, dp(3))
        arc = int(-span * 16)

        # track (full semicircle)
        p.setPen(QPen(QColor(PAL["axis"]), thick, Qt.SolidLine, Qt.RoundCap))
        p.drawArc(rect, 180 * 16, arc)

        # regime tick marks at 0.5 and 0.6
        tick = QPen(QColor(PAL["faint"]), max(1.0, radius * 0.02))
        for frac in (0.5, 0.6):
            a = math.pi - math.pi * frac  # 180deg -> 0deg (left->right)
            x1 = cx + math.cos(a) * radius
            y1 = cy - math.sin(a) * radius
            x2 = cx + math.cos(a) * (radius - thick * 0.9)
            y2 = cy - math.sin(a) * (radius - thick * 0.9)
            p.setPen(tick)
            p.drawLine(int(x1), int(y1), int(x2), int(y2))

        # value arc (colored by tilt)
        color = QColor(_tilt_color(self._tilt))
        p.setPen(QPen(color, thick, Qt.SolidLine, Qt.RoundCap))
        p.drawArc(rect, 180 * 16, int(-span * self._value * 16))

        # needle
        a = math.pi - math.pi * self._value
        nx = cx + math.cos(a) * (radius - thick)
        ny = cy - math.sin(a) * (radius - thick)
        p.setPen(QPen(QColor(PAL["text"]), max(1.5, radius * 0.03), Qt.SolidLine, Qt.RoundCap))
        p.drawLine(int(cx), int(cy - radius * 0.10), int(nx), int(ny))
        p.setBrush(QColor(PAL["accent"]))
        p.setPen(Qt.NoPen)
        p.drawEllipse(QRectF(nx - 3, ny - 3, 6, 6))

        # center % readout
        p.setFont(QFont("Segoe UI Light", int(max(radius * 0.24, 12))))
        p.setPen(QColor(PAL["text"]))
        p.drawText(QRectF(0, cy - radius * 0.5, w, radius * 0.5),
                   Qt.AlignCenter, "{:.0%}".format(self._value))
        p.setFont(QFont("Segoe UI", 8))
        p.setPen(QColor(PAL["faint"]))
        p.drawText(QRectF(0, cy + radius * 0.15, w, 16), Qt.AlignCenter,
                   "← {:.0f}%  突破年线 {:.0f}% →".format(self._value * 100, (1 - self._value) * 100))
        p.end()


class SplitBar(QWidget):
    """Horizontal stacked composition bar — up / down / flat share (今日涨跌分布)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._up = self._dn = self._flat = 0
        self.setMinimumHeight(dp(24))

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
        total = self._up + self._dn + self._flat
        seg_h = min(h - 6, dp(12))
        y = (h - seg_h) / 2.0
        x = 0.0
        r = min(seg_h / 2, dp(5))
        if total <= 0:
            p.setBrush(QColor(PAL["axis"]))
            p.setPen(Qt.NoPen)
            p.drawRoundedRect(QRectF(x, y, w, seg_h), r, r)
            p.end()
            return
        for value, color in ((self._up, PAL["up"]), (self._dn, PAL["down"]), (self._flat, PAL["faint"])):
            if value <= 0:
                continue
            seg_w = w * value / total
            p.setBrush(QColor(color))
            p.setPen(Qt.NoPen)
            p.drawRoundedRect(QRectF(x, y, seg_w, seg_h), r, r)
            x += seg_w
        # labels
        p.setFont(QFont("Segoe UI", 8))
        if self._up:
            p.setPen(QColor(PAL["up"]))
            p.drawText(QRectF(0, y, w * self._up / total, seg_h),
                       Qt.AlignLeft | Qt.AlignVCenter,
                       "涨 {:.0%}".format(self._up / total))
        if self._dn:
            p.setPen(QColor(PAL["down"]))
            p.drawText(
                QRectF(w * self._up / total, y, w * self._dn / total, seg_h),
                Qt.AlignCenter | Qt.AlignVCenter,
                "跌 {:.0%}".format(self._dn / total))
        if self._flat:
            p.setPen(QColor(PAL["faint"]))
            p.drawText(
                QRectF(w * (self._up + self._dn) / total, y, w * self._flat / total, seg_h),
                Qt.AlignRight | Qt.AlignVCenter,
                "{:.0%}".format(self._flat / total))
        p.end()
