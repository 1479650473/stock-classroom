"""KlineChart v2.8 — matplotlib 实时 K 线图，滚轮缩放+拖拽"""
import numpy as np
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg
from matplotlib.figure import Figure
from PyQt5.QtWidgets import QWidget, QVBoxLayout
from PyQt5.QtCore import Qt


class KlineChartV2(QWidget):
    """K线图: matplotlib FigureCanvasQTAgg, 滚轮缩放+拖拽平移"""

    def __init__(self):
        super().__init__()
        self.setStyleSheet("background:#111111")
        self.indicator = "macd"
        self._last_data = None
        self._last_sym = ""
        self._last_name = ""
        self._ax_a = None
        self._cross_vline = None
        self._cross_hline = None
        self._info_ann = None
        self._bar_store = {}
        self._pan_data = None

        lo = QVBoxLayout(self)
        lo.setContentsMargins(0, 0, 0, 0)
        lo.setSpacing(0)

        self.fig = Figure(figsize=(10, 6), facecolor="#111111")
        gs = self.fig.add_gridspec(3, 1, height_ratios=[3, 1, 1.2],
                                    hspace=0.04, left=0.06, right=0.94,
                                    bottom=0.08, top=0.94)
        self.ax_k = self.fig.add_subplot(gs[0])
        self.ax_v = self.fig.add_subplot(gs[1], sharex=self.ax_k)
        self.ax_i = self.fig.add_subplot(gs[2], sharex=self.ax_k)

        for ax in [self.ax_k, self.ax_v, self.ax_i]:
            ax.set_facecolor("#111111")
            ax.tick_params(colors="#B4B4B4", labelsize=8)
            for sp in ax.spines.values():
                sp.set_color("#393028")
        self.ax_k.tick_params(labelbottom=False)
        self.ax_v.tick_params(labelbottom=False)

        self.canvas = FigureCanvasQTAgg(self.fig)
        lo.addWidget(self.canvas)

        # Mouse events
        self.canvas.mpl_connect("scroll_event", self._on_scroll)
        self.canvas.mpl_connect("button_press_event", self._on_press)
        self.canvas.mpl_connect("motion_notify_event", self._on_motion)
        self.canvas.mpl_connect("button_release_event", self._on_release)

    def _on_scroll(self, event):
        if event.inaxes is None:
            return
        xmin, xmax = self.ax_k.get_xlim()
        cx = event.xdata
        factor = 0.85 if event.button == "up" else 1.18
        nxmin = cx - (cx - xmin) * factor
        nxmax = nxmin + (xmax - xmin) * factor
        max_n = self._data_len() - 1
        nxmin = max(-0.5, nxmin)
        nxmax = min(max_n + 0.5, nxmax)
        if nxmax - nxmin <= 2:
            return
        self.ax_k.set_xlim(nxmin, nxmax)
        self.canvas.draw_idle()

    def _on_press(self, event):
        if event.inaxes is None or event.button != 1:
            return
        self._pan_data = (event.xdata, self.ax_k.get_xlim())

    def _on_motion(self, event):
        # Pan mode (left button held)
        if self._pan_data is not None and event.inaxes is not None:
            x0, (xmin0, xmax0) = self._pan_data
            dx = x0 - (event.xdata if event.xdata is not None else x0)
            nxmin = xmin0 + dx
            nxmax = xmax0 + dx
            max_n = self._data_len() - 1
            nxmin = max(-0.5, nxmin)
            nxmax = min(max_n + 0.5, nxmax)
            if nxmax - nxmin <= 2:
                return
            if self._cross_vline:
                self._cross_vline.set_visible(False)
                self._cross_hline.set_visible(False)
                self._info_ann.set_visible(False)
            self.ax_k.set_xlim(nxmin, nxmax)
            self.canvas.draw_idle()
            return

        # Crosshair + tooltip
        if event.inaxes is None or not self._bar_store:
            if self._cross_vline:
                self._cross_vline.set_visible(False)
                self._cross_hline.set_visible(False)
                self._info_ann.set_visible(False)
                self.canvas.draw_idle()
            return

        if event.inaxes != self.ax_k:
            if self._cross_vline:
                self._cross_vline.set_visible(False)
                self._cross_hline.set_visible(False)
                self._info_ann.set_visible(False)
                self.canvas.draw_idle()
            return

        idx = int(round(event.xdata))
        if idx < 0 or idx >= len(self._bar_store['dates']):
            return

        if self._cross_vline is None:
            self._cross_vline = self.ax_k.axvline(x=0, color='#FFE0C2', linewidth=0.5, alpha=0.5)
            self._cross_hline = self.ax_k.axhline(y=0, color='#FFE0C2', linewidth=0.5, alpha=0.5)
            self._info_ann = self.ax_k.annotate('', xy=(0,0), fontsize=8, color='#EEEEEE',
                bbox=dict(boxstyle='round,pad=0.3', facecolor='#191919', edgecolor='#FFE0C2', alpha=0.9),
                verticalalignment='bottom')

        bar_close = float(self._bar_store['closes'][idx])
        self._cross_vline.set_xdata([idx, idx])
        self._cross_vline.set_visible(True)
        self._cross_hline.set_ydata([bar_close, bar_close])
        self._cross_hline.set_visible(True)

        bd = self._bar_store
        info = ' ' + bd['dates'][idx] + '\n' +                ' 开:' + '{:.2f}'.format(bd['opens'][idx]) + '  高:' + '{:.2f}'.format(bd['highs'][idx]) + '\n' +                ' 低:' + '{:.2f}'.format(bd['lows'][idx]) + '  收:' + '{:.2f}'.format(bd['closes'][idx]) + '\n' +                ' 成交量:' + '{:.0f}'.format(bd['volumes'][idx])
        self._info_ann.xy = (idx, bar_close)
        self._info_ann.set_text(info)
        self._info_ann.set_visible(True)
        self.canvas.draw_idle()

    def _on_release(self, event):
        self._pan_data = None

    def _data_len(self):
        if self._last_data:
            return len(self._last_data.get("data", []))
        return 180

    # ── Public API ──

    def set_data(self, data, symbol, name):
        if data is None or data.get("code") != 0:
            return
        bars = data.get("data", [])
        if not bars:
            return
        self._last_data = data
        self._last_sym = symbol
        self._last_name = name
        self._render(bars, symbol, name)

    def switch_indicator(self, ind_type):
        self.indicator = ind_type
        if self._last_data is not None:
            bars = self._last_data.get("data", [])
            if bars:
                self._render(bars, self._last_sym, self._last_name)

    def _safe(self, vals, default=0):
        return np.array([(v if v is not None else default) for v in vals], dtype=float)

    def _safe_nan(self, vals):
        return np.array([(v if v is not None else np.nan) for v in vals])

    def _render(self, bars, symbol, name):
        if not bars:
            return

        n = len(bars)
        dates = [b["date"] for b in bars]

        opens = self._safe([b["open"] for b in bars])
        closes = self._safe([b["close"] for b in bars])
        highs = self._safe([b["high"] for b in bars])
        lows = self._safe([b["low"] for b in bars])
        volumes = self._safe([b.get("volume", 0) for b in bars])
        amounts = self._safe([b.get("amount", 0) for b in bars])
        self._bar_store = {
            "dates": dates,
            "opens": opens,
            "highs": highs,
            "lows": lows,
            "closes": closes,
            "volumes": volumes,
        }

        ma5 = self._safe_nan([b.get("ma5") for b in bars])
        ma10 = self._safe_nan([b.get("ma10") for b in bars])
        ma20 = self._safe_nan([b.get("ma20") for b in bars])
        dif = self._safe([b.get("dif", 0) for b in bars])
        dea = self._safe([b.get("dea", 0) for b in bars])
        macd = self._safe([b.get("macd", 0) for b in bars])
        rsi14 = self._safe([b.get("rsi14", 50) for b in bars])

        for ax in [self.ax_k, self.ax_v, self.ax_i]:
            ax.clear()
            ax.set_facecolor("#111111")
            ax.tick_params(colors="#B4B4B4", labelsize=8)
            for sp in ax.spines.values():
                sp.set_color("#393028")

        if self._ax_a is not None:
            try:
                self._ax_a.remove()
            except Exception:
                pass
            self._ax_a = None

        x = np.arange(n)
        w = 0.6
        up = closes >= opens
        c_up, c_dn = "#E54D2E", "#3fb950"
        c_up_e, c_dn_e = "#E54D2E", "#2ea043"
        colors_arr = [c_dn if not u else c_up for u in up]
        min_oc = np.minimum(opens, closes)
        max_oc = np.maximum(opens, closes)

        # K-line (vlines for speed)
        self.ax_k.vlines(x, lows, highs, colors="#B4B4B4", linewidth=0.5)
        self.ax_k.vlines(x, min_oc, max_oc, colors=colors_arr, linewidth=3)
        self.ax_k.plot(x, ma5, color="#FDBF6E", linewidth=0.8, label="MA5")
        self.ax_k.plot(x, ma10, color="#FFA726", linewidth=0.8, label="MA10")
        self.ax_k.plot(x, ma20, color="#CE93D8", linewidth=0.8, label="MA20")
        self.ax_k.set_title(f"{symbol} {name}", color="#FFE0C2", fontsize=11, fontweight="bold")
        self.ax_k.legend(loc="upper left", fontsize=7, facecolor="#111111",
                         edgecolor="#393028", labelcolor="#EEEEEE")
        self.ax_k.tick_params(labelbottom=False)
        self.ax_k.autoscale_view()

        # Volume
        self.ax_v.bar(x, volumes, w * 0.8, color=colors_arr, alpha=0.5, linewidth=0)
        self.ax_v.set_ylabel("量", color="#B4B4B4", fontsize=7)
        self.ax_v.tick_params(labelbottom=False)

        self._ax_a = self.ax_v.twinx()
        self._ax_a.set_facecolor("#111111")
        self._ax_a.tick_params(colors="#B4B4B4", labelsize=7)
        self._ax_a.spines["right"].set_color("#201E18")
        self._ax_a.plot(x, amounts, color="#FFE0C2", linewidth=0.8, alpha=0.7)
        self._ax_a.set_ylabel("额", color="#B4B4B4", fontsize=7)

        # Indicator
        if self.indicator == "macd":
            mc = [c_dn if v < 0 else c_up for v in macd]
            self.ax_i.bar(x, macd, w * 0.8, color=mc, alpha=0.4, linewidth=0)
            self.ax_i.plot(x, dif, color="#FDBF6E", linewidth=0.8, label="DIF")
            self.ax_i.plot(x, dea, color="#CE93D8", linewidth=0.8, label="DEA")
            self.ax_i.axhline(0, color="#393028", linewidth=0.5)
            self.ax_i.set_ylabel("MACD", color="#B4B4B4", fontsize=7)
            self.ax_i.legend(loc="upper left", fontsize=7, facecolor="#111111",
                             edgecolor="#393028", labelcolor="#EEEEEE")
        else:
            self.ax_i.plot(x, rsi14, color="#CE93D8", linewidth=1.2, label="RSI")
            self.ax_i.axhline(70, color="#E54D2E", linewidth=0.5, linestyle="--")
            self.ax_i.axhline(30, color="#3fb950", linewidth=0.5, linestyle="--")
            self.ax_i.set_ylim(0, 100)
            self.ax_i.set_ylabel("RSI", color="#B4B4B4", fontsize=7)
            self.ax_i.legend(loc="upper left", fontsize=7, facecolor="#111111",
                             edgecolor="#393028", labelcolor="#EEEEEE")

        tick_step = max(1, n // 10)
        self.ax_i.set_xticks(x[::tick_step])
        self.ax_i.set_xticklabels([dates[i][4:6] + "/" + dates[i][6:8]
                                   for i in range(0, n, tick_step)],
                                  fontsize=7, rotation=30)

        self.canvas.draw()
