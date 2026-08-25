# -*- coding: utf-8 -*-
"""Premium shared UI toolkit for stock-classroom.

Single source for the '高级感' design language used across plugins:
palette, gradient card QSS, gold-section-title, and the count-up label.

Mirrors the research panel's _PAL / _CARD_QSS / light-numbers look so the
trade companion, datacenter, and any new panel can inherit it without each
re-declaring colors or QSS (which previously drift apart).
"""

from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtWidgets import QLabel, QFrame, QWidget, QHBoxLayout

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
