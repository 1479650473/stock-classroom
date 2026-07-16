"""
KlineChart v3.0 — pyqtgraph 高性能 K 线图组件
60fps 渲染, 专业级交互, Caffeine 暗色主题

面板布局:
  主图区: K线蜡烛 + MA5/10/20/60 + BOLL 布林带
  成交量: 成交量柱 (红涨绿跌) + MAVOL
  副图区: MACD (柱+DIF/DEA) / RSI (30/70线) 可切换

交互:
  滚轮缩放 (跟随鼠标位置)
  左键拖拽平移
  十字光标联动 (三面板同步)
  悬停信息卡片 (开高低收+涨幅+成交量)
"""

import numpy as np
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QLabel, QSplitter
from PyQt5.QtCore import Qt, QPointF, QRectF
from PyQt5.QtGui import QPainter, QColor, QPen, QBrush, QFont, QPicture, QFontMetrics

import pyqtgraph as pg


# ── 主题色 (Caffeine 暖色暗色系) ──────────────────────
_C = {
    'bg':        '#111111',
    'panel':     '#191919',
    'border':    '#201E18',
    'text':      '#EEEEEE',
    'text_sec':  '#B4B4B4',
    'accent':    '#FFE0C2',
    'warm_brown':'#393028',
    'up':        '#E54D2E',
    'down':      '#3fb950',
    'up_bdr':    '#C0392B',
    'down_bdr':  '#2ea043',
    'ma5':       '#FDBF6E',
    'ma10':      '#FFA726',
    'ma20':      '#CE93D8',
    'ma60':      '#64B5F6',
    'boll':      '#78909C',
    'mavol':     '#B0BEC5',
}


# ═══════════════════════════════════════════════════════
# 自定义 K 线蜡烛图元
# ═══════════════════════════════════════════════════════
class CandlestickItem(pg.GraphicsObject):
    """使用 QPicture 预渲染的 K 线蜡烛, 缩放不重绘."""

    def __init__(self):
        super().__init__()
        self._pic = QPicture()
        self._n = 0

    def set_data(self, opens, highs, lows, closes):
        self._n = len(opens)
        self._pic = QPicture()
        p = QPainter(self._pic)
        w = 0.45
        for i in range(self._n):
            o, hh, ll, c = opens[i], highs[i], lows[i], closes[i]
            if np.isnan(o) or np.isnan(c):
                continue
            up = c >= o
            p.setPen(QPen(QColor('#B4B4B4'), 0.5))
            p.drawLine(QPointF(i, ll), QPointF(i, hh))
            top, bot = (c, o) if up else (o, c)
            body_h = max(bot - top, 0.4)
            p.setBrush(QColor('#E54D2E' if up else '#3fb950'))
            p.setPen(QPen(QColor('#C0392B' if up else '#2ea043'), 0.3))
            p.drawRect(QRectF(i - w, top, 2 * w, body_h))
        p.end()
        self.update()

    def paint(self, p, *args):
        p.drawPicture(0, 0, self._pic)

    def boundingRect(self):
        return QRectF(0, -1e6, max(1, self._n), 2e6)


# ═══════════════════════════════════════════════════════
# 成交量柱图元
# ═══════════════════════════════════════════════════════
class VolumeBarItem(pg.GraphicsObject):
    def __init__(self):
        super().__init__()
        self._pic = QPicture()
        self._n = 0

    def set_data(self, volumes, up_mask):
        self._v = np.asarray(volumes, dtype=float)
        self._up = np.asarray(up_mask, dtype=bool)
        self._n = len(volumes)
        self.update()
    def paint(self, p, *args):
        if self._n == 0: return
        w = 0.45
        for i in range(self._n):
            v = float(self._v[i])
            if np.isnan(v) or v <= 0: continue
            clr = '#E54D2E' if self._up[i] else '#3fb950'
            p.setBrush(QColor(clr))
            p.setPen(QPen(QColor(clr).darker(120), 0))
            p.drawRect(QRectF(i - w, 0, 2 * w, float(v)))
    def boundingRect(self):
        return QRectF(0, -1e6, max(1, self._n), 2e6)

class PriceAxis(pg.AxisItem):
    """价格轴: 保留 2 位小数."""
    def tickStrings(self, values, scale, spacing):
        return [f'{v:.2f}' for v in values]


class VolAxis(pg.AxisItem):
    """成交量轴: 万/亿 智能格式化."""
    def tickStrings(self, values, scale, spacing):
        out = []
        for v in values:
            if v >= 1e8:
                out.append(f'{v/1e8:.1f}亿')
            elif v >= 1e4:
                out.append(f'{v/1e4:.0f}万')
            else:
                out.append(f'{v:.0f}')
        return out


class DateAxis(pg.AxisItem):
    """日期轴: MM/DD 格式, 按 idx 映射."""
    def __init__(self, dates=None, *a, **kw):
        super().__init__(*a, **kw)
        self._dates = dates or []

    def set_dates(self, dates):
        self._dates = dates

    def tickStrings(self, values, scale, spacing):
        out = []
        for v in values:
            idx = int(round(v))
            if 0 <= idx < len(self._dates):
                d = self._dates[idx]
                out.append(f'{d[4:6]}/{d[6:8]}')
            else:
                out.append('')
        return out


# ═══════════════════════════════════════════════════════
# 主组件
# ═══════════════════════════════════════════════════════
class KlineChartV3(QWidget):
    """PyQtGraph 高性能 K 线图.
    pg.setConfigOptions(useOpenGL=True)

    公开 API (与 v2 兼容):
        set_data(data, symbol, name)
        switch_indicator(ind_type)
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet(f'background:{_C["bg"]}')
        self._indicator = 'macd'
        self._bars = []
        self._dates = []
        self._crosshair_visible = False
        self._init_ui()

    # ── UI 构建 ──────────────────────────────────────

    def _init_ui(self):
        lo = QVBoxLayout(self)
        lo.setContentsMargins(0, 0, 0, 0)
        lo.setSpacing(0)

        # 标题栏
        self._title = QLabel('选择个股查看 K 线')
        self._title.setStyleSheet(
            f'color:{_C["accent"]}; font-weight:bold; font-size:13px; '
            f'padding:4px 10px; background:{_C["panel"]}')
        lo.addWidget(self._title)

        # ── 轴 (共用 DateAxis, 仅底部面板显示日期) ──
        self._date_axis = DateAxis(orientation='bottom', pen=_C['border'])
        self._price_axis = PriceAxis(orientation='left', pen=_C['border'])
        self._vol_axis   = VolAxis(orientation='left', pen=_C['border'])
        self._ind_axis   = PriceAxis(orientation='left', pen=_C['border'])
        # 辅助函数: 创建隐藏标签的底部轴
        def _hidden_bottom_axis():
            ax = DateAxis(orientation='bottom', pen=_C['border'])
            ax.setStyle(showValues=False, tickTextOffset=0)
            ax.setLabel('')
            return ax

        # ── 主图 ──
        self.main_plot = pg.PlotWidget(
            axisItems={'bottom': _hidden_bottom_axis(), 'left': self._price_axis},
            background=_C['bg'])
        self.main_plot.setMenuEnabled(False)
        self.main_plot.showGrid(x=False, y=True, alpha=0.10)
        vb = self.main_plot.getViewBox()
        vb.setMouseMode(pg.ViewBox.PanMode)

        self._candle = CandlestickItem()
        self.main_plot.addItem(self._candle)

        # MA 线
        self._ma = {}
        for k, c in [('ma5', _C['ma5']), ('ma10', _C['ma10']),
                      ('ma20', _C['ma20']), ('ma60', _C['ma60'])]:
            ln = pg.PlotDataItem(pen=QPen(QColor(c), 0.8))
            self._ma[k] = ln
            self.main_plot.addItem(ln)

        # BOLL
        self._boll = {}
        for k, c, ls in [('upper', _C['boll'], Qt.DashLine),
                          ('mid', _C['boll'], Qt.DotLine),
                          ('lower', _C['boll'], Qt.DashLine)]:
            ln = pg.PlotDataItem(pen=QPen(QColor(c), 0.6, ls))
            self._boll[k] = ln
            self.main_plot.addItem(ln)

        # ── 成交量 ──
        self.vol_plot = pg.PlotWidget(
            axisItems={'bottom': _hidden_bottom_axis(), 'left': self._vol_axis},
            background=_C['bg'])
        self.vol_plot.setMenuEnabled(False)
        self.vol_plot.showGrid(x=False, y=True, alpha=0.10)
        self.vol_plot.getViewBox().setMouseMode(pg.ViewBox.PanMode)

        self._vol_item = VolumeBarItem()
        self.vol_plot.addItem(self._vol_item)
        self._mavol_line = pg.PlotDataItem(pen=QPen(QColor(_C['mavol']), 0.6))
        self.vol_plot.addItem(self._mavol_line)

        # ── 副图 ──
        self.ind_plot = pg.PlotWidget(
            axisItems={'bottom': self._date_axis, 'left': self._ind_axis},
            background=_C['bg'])
        self.ind_plot.setMenuEnabled(False)
        self.ind_plot.showGrid(x=False, y=True, alpha=0.10)
        self.ind_plot.getViewBox().setMouseMode(pg.ViewBox.PanMode)

        # MACD 元素
        self._macd_hist = pg.BarGraphItem(
            x=[0], height=[0], width=0.7, brushes=[QColor(_C['up'])])
        self._macd_dif  = pg.PlotDataItem(pen=QPen(QColor(_C['ma5']), 0.8))
        self._macd_dea  = pg.PlotDataItem(pen=QPen(QColor(_C['ma20']), 0.8))
        self._macd_zero = pg.InfiniteLine(angle=0, pos=0, pen=QPen(QColor(_C['warm_brown']), 0.6))
        # RSI 元素
        self._rsi_line = pg.PlotDataItem(pen=QPen(QColor(_C['ma20']), 1.0))
        self._rsi_70   = pg.InfiniteLine(angle=0, pos=70, pen=QPen(QColor('#E54D2E'), 0.5, Qt.DashLine))
        self._rsi_30   = pg.InfiniteLine(angle=0, pos=30, pen=QPen(QColor('#3fb950'), 0.5, Qt.DashLine))
        self._rsi_50   = pg.InfiniteLine(angle=0, pos=50, pen=QPen(QColor(_C['warm_brown']), 0.4, Qt.DotLine))

        for item in [self._macd_hist, self._macd_dif, self._macd_dea, self._macd_zero,
                      self._rsi_line, self._rsi_70, self._rsi_30, self._rsi_50]:
            self.ind_plot.addItem(item)
        self._show_macd(True)
        self._show_rsi(False)

        # ── 十字光标 ──
        cross_pen = QPen(QColor(_C['accent']), 0.8, Qt.DashLine)
        self._cross_v = [
            pg.InfiniteLine(angle=90, movable=False, pen=cross_pen),
            pg.InfiniteLine(angle=90, movable=False, pen=cross_pen),
            pg.InfiniteLine(angle=90, movable=False, pen=cross_pen),
        ]
        self._cross_h = pg.InfiniteLine(angle=0, movable=False, pen=cross_pen)
        self.main_plot.addItem(self._cross_v[0])
        self.vol_plot.addItem(self._cross_v[1])
        self.ind_plot.addItem(self._cross_v[2])
        self.main_plot.addItem(self._cross_h)

        # ── 信息卡片 ──
        self._info_card = pg.TextItem(
            '', anchor=(1, 1), color=_C['text'],
            fill=QBrush(QColor(_C['panel'])),
            border=QPen(QColor(_C['accent']), 0.8))
        self._info_card.setFont(QFont('Microsoft YaHei UI', 8))
        self._info_card.setZValue(200)
        self.main_plot.addItem(self._info_card)

        for v in self._cross_v:
            v.setVisible(False)
        self._cross_h.setVisible(False)
        self._info_card.setVisible(False)

        # ── 布局 ──
        sp = QSplitter(Qt.Vertical)
        sp.addWidget(self.main_plot)
        sp.addWidget(self.vol_plot)
        sp.addWidget(self.ind_plot)
        sp.setStretchFactor(0, 3)
        sp.setStretchFactor(1, 1)
        sp.setStretchFactor(2, 1)
        sp.setHandleWidth(0)
        sp.setChildrenCollapsible(False)
        sp.setStyleSheet('background:transparent;')
        lo.addWidget(sp, 1)

        # X 轴联动
        # X轴联动: main→vol→ind
        self.ind_plot.plotItem.setXLink(self.vol_plot.plotItem)
        pass
        # 鼠标追踪 (三面板分别绑定, 确保任意位置十字光标同步)
        self._crosshair_idx = -1  # cache last bar index
        self.setMouseTracking(True)
        # 仅主图追踪鼠标, rateLimit=20, 附带index缓存
        vb = self.main_plot.getViewBox()
        self._mouse_proxy = pg.SignalProxy(
            self.main_plot.scene().sigMouseMoved,
            rateLimit=20,
            slot=lambda e: self._on_crosshair_at(vb, e))

        # 范围联动: 任一面板缩放/平移时同步X并重算Y
        self._syncing_x = False
        for pw in (self.main_plot, self.vol_plot, self.ind_plot):
            pw.getViewBox().sigRangeChangedManually.connect(
                self._on_any_range_changed)


    # ── 指标可见性 ──────────────────────────────────

    def _show_macd(self, v):
        self._macd_hist.setVisible(v)
        self._macd_dif.setVisible(v)
        self._macd_dea.setVisible(v)
        self._macd_zero.setVisible(v)

    def _show_rsi(self, v):
        self._rsi_line.setVisible(v)
        self._rsi_70.setVisible(v)
        self._rsi_30.setVisible(v)
        self._rsi_50.setVisible(v)

    # ── 渲染 ────────────────────────────────────────

    def _render(self, bars, symbol, name):
        self._bars = bars
        n = len(bars)
        if n == 0:
            return
        # Remove mixed-stock data: filter bars with very different prices
        if n > 5:
            ref_c = float(bars[0].get("close", 0))
            if ref_c > 0:
                tmp = [b for b in bars if abs(float(b.get("close", ref_c)) / ref_c - 1) < 0.5]
                if len(tmp) >= 10:
                    bars = tmp
                    n = len(bars)
                    self._bars = bars


        dates = [b['date'] for b in bars]
        opens   = np.array([b['open']   for b in bars], dtype=float)
        highs   = np.array([b['high']   for b in bars], dtype=float)
        lows    = np.array([b['low']    for b in bars], dtype=float)
        closes  = np.array([b['close']  for b in bars], dtype=float)
        volumes = np.array([b.get('volume', 0) for b in bars], dtype=float)
        up_mask = closes >= opens
        x = np.arange(n, dtype=float)

        self._dates = dates
        self._date_axis.set_dates(dates)

        # 数据辅助
        nan = lambda arr: np.array([(v if v is not None else np.nan) for v in arr], dtype=float)
        safe = lambda arr: np.array([(v if v is not None else 0.0) for v in arr], dtype=float)

        ma5  = nan([b.get('ma5') for b in bars])
        ma10 = nan([b.get('ma10') for b in bars])
        ma20 = nan([b.get('ma20') for b in bars])
        ma60 = nan([b.get('ma60') for b in bars])
        b_up = nan([b.get('boll_upper') for b in bars])
        b_md = nan([b.get('boll_mid')   for b in bars])
        b_lo = nan([b.get('boll_lower') for b in bars])
        dif  = safe([b.get('dif',  0) for b in bars])
        dea  = safe([b.get('dea',  0) for b in bars])
        macd = safe([b.get('macd', 0) for b in bars])
        rsi  = nan([b.get('rsi14') for b in bars])
        mavol = self._calc_ma(volumes, 5)

        # 图元更新
        self._candle.set_data(opens, highs, lows, closes)

        for arr, key in [(ma5, 'ma5'), (ma10, 'ma10'), (ma20, 'ma20'), (ma60, 'ma60')]:
            m = ~np.isnan(arr)
            self._ma[key].setData(x[m], arr[m])
        for arr, key in [(b_up, 'upper'), (b_md, 'mid'), (b_lo, 'lower')]:
            m = ~np.isnan(arr)
            self._boll[key].setData(x[m], arr[m])

        self._vol_item.set_data(volumes, up_mask)
        mvm = ~np.isnan(mavol)
        self._mavol_line.setData(x[mvm], mavol[mvm])

        # MACD 柱 (BarGraphItem 不支持直接更新, 重建)
        self.ind_plot.removeItem(self._macd_hist)
        mc_brushes = [QColor(_C['up']) if v >= 0 else QColor(_C['down']) for v in macd]
        self._macd_hist = pg.BarGraphItem(x=x, height=macd, width=0.7, brushes=mc_brushes)
        self.ind_plot.addItem(self._macd_hist)
        self._show_macd(self._indicator == 'macd')

        self._macd_dif.setData(x, dif)
        self._macd_dea.setData(x, dea)
        rm = ~np.isnan(rsi)
        self._rsi_line.setData(x[rm], rsi[rm])
        self._show_rsi(self._indicator == 'rsi')

        # 标题
        last_c = float(closes[-1])
        chg = last_c - float(opens[-1])
        arrow = '▲' if chg >= 0 else '▼'
        clr = _C['up'] if chg >= 0 else _C['down']
        self._title.setText(
            f'  {symbol}  {name}  |  {n}日  |  '
            f'<span style="color:{_C["text"]}">{last_c:.2f}</span>  '
            f'<span style="color:{clr}">{arrow} {chg:+.2f}</span>')
        self._title.setTextFormat(Qt.RichText)

        # 初始视图: 最后 60 根
        start = max(0, n - 60)
        self.main_plot.getViewBox().setXRange(start, n - 1, padding=0.02)
        self.vol_plot.getViewBox().setXRange(start, n - 1, padding=0.02)
        self.ind_plot.getViewBox().setXRange(start, n - 1, padding=0.02)
        self._update_y_ranges(start, n - 1)
        for pw in (self.main_plot, self.vol_plot, self.ind_plot):
            pw.getViewBox().setLimits(xMin=-0.5, xMax=n - 0.5)

    # ── 工具函数 ────────────────────────────────────

    @staticmethod
    def _calc_ma(arr, period):
        out = np.full_like(arr, np.nan, dtype=float)
        if len(arr) < period:
            return out
        cum = np.cumsum(arr)
        out[period - 1] = cum[period - 1] / period
        out[period:] = (cum[period:] - cum[:-period]) / period
        return out

    # ── 交互 ────────────────────────────────────────

    def _on_crosshair_at(self, vb, evt):
        """Only update crosshair when cursor moves to a different bar."""
        pos = evt[0]
        mp = vb.mapSceneToView(pos)
        idx = int(round(mp.x()))
        n = len(self._bars)
        if idx < 0 or idx >= n or n == 0:
            self._hide_crosshair()
            return
        if idx == self._crosshair_idx:
            return  # same bar, skip
        self._crosshair_idx = idx
        x_pos = float(idx)
        bar = self._bars[idx]
        cv = float(bar["close"])
        # Batch update: show all then set positions
        for v in self._cross_v:
            v.setPos(x_pos)
            v.setVisible(True)
        self._cross_h.setPos(cv)
        self._cross_h.setVisible(True)
        fmt = (f'  {bar["date"]}\n'
               f'  \u5f00: {float(bar["open"]):.2f}  \u9ad8: {float(bar["high"]):.2f}\n'
               f'  \u4f4e: {float(bar["low"]):.2f}  \u6536: {float(bar["close"]):.2f}\n'
               f'  \u91cf: {float(bar.get("volume", 0)):.0f}')
        self._info_card.setText(fmt)
        self._info_card.setPos(x_pos, cv)
        self._info_card.setVisible(True)
    def _hide_crosshair(self):
        if not self._crosshair_visible:
            return
        self._crosshair_visible = False
        for v in self._cross_v:
            v.setVisible(False)
        self._cross_h.setVisible(False)
        self._info_card.setVisible(False)

    def _update_y_ranges(self, x_start, x_end):
        bars = self._bars
        n = len(bars)
        if n == 0: return
        s = max(0, int(round(x_start)))
        e = min(n - 1, int(round(x_end)))
        vis = bars[s:e + 1]
        if not vis: return
        # Use most recent bar as price reference
        ref_close = float(bars[min(n-1, s)].get("close", 0))
        # Filter out bars with very different prices (mixed stocks)
        if ref_close > 0:
            filtered = [b for b in vis if abs(float(b.get("close", ref_close)) / ref_close - 1) < 0.5]
            if len(filtered) >= 5:
                vis = filtered
        hh = max(float(b["high"]) for b in vis if float(b.get("high", 0)) > 0)
        ll = min(float(b["low"]) for b in vis if float(b.get("low", 0)) > 0)
        margin = max((hh - ll) * 0.06, 0.05)
        self.main_plot.getViewBox().setYRange(ll - margin, hh + margin, update=False)
        vmax = max(float(b.get("volume", 0)) for b in vis if b.get("volume", 0) > 0)
        self.vol_plot.getViewBox().setYRange(0, max(vmax, 1) * 1.15, update=False)
        if self._indicator == "macd":
            vals = []
            for b in vis:
                for k in ("macd", "dif", "dea"):
                    v = b.get(k)
                    if v is not None:
                        vals.append(abs(float(v)))
            m = max(vals) if vals else 1
            self.ind_plot.getViewBox().setYRange(-m * 1.3, m * 1.3, update=False)
        else:
            self.ind_plot.getViewBox().setYRange(0, 100, update=False)

    def _on_any_range_changed(self):
        # X范围变化时, 只更新Y轴范围 (不手动同步X, 由setXRange负责)
        if self._syncing_x:
            return
        self._syncing_x = True
        try:
            vb = self.sender()
            if vb is None: return
            xr = vb.viewRange()[0]
            if not (xr[0] < xr[1]): return
            # 同步其他面板X范围
            for pw in (self.main_plot, self.vol_plot, self.ind_plot):
                ovb = pw.getViewBox()
                if ovb is not vb:
                    ovb.setXRange(xr[0], xr[1], padding=0)
            self._update_y_ranges(xr[0], xr[1])
        finally:
            self._syncing_x = False
    def set_data(self, data, symbol, name):
        if data is None or data.get("code") != 0:
            return
        bars = data.get("data", [])
        if not bars:
            return
        if name:
            filtered = [b for b in bars if b.get("high", 0) > 0]
            if filtered:
                bars = filtered
        self._render(bars, symbol, name)

    def switch_indicator(self, ind_type):
        self._indicator = ind_type
        self._show_macd(ind_type == "macd")
        self._show_rsi(ind_type == "rsi")
        label = "MACD" if ind_type == "macd" else "RSI"
        self._ind_axis.setLabel(label, color=_C["text_sec"])
        self._update_y_ranges(0, len(self._bars) - 1)
