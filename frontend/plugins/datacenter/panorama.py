# -*- coding: utf-8 -*-
"""Data Panorama - Gantt chart showing database coverage across time."""

import sqlite3
from datetime import date, timedelta
from PyQt5.QtWidgets import QWidget, QToolTip
from PyQt5.QtCore import Qt, QThread, pyqtSignal, QRectF
from PyQt5.QtGui import QPainter, QColor, QFont, QPen

C_BG = "#0D1117"
C_PANEL = "#161B22"
C_BORDER = "#21262D"
C_TEXT = "#E6EDF3"
C_SUBTEXT = "#8B949E"
C_ACCENT = "#D4A574"

DATE_CANDIDATES = ["date", "trade_date", "week_start", "update_date", "last_date"]

TABLES = [
    ("kline", "kline_daily", "\u65e5K\u7ebf", "#3fb950"),
    ("kline", "kline_weekly", "\u5468K\u7ebf", "#79C0FF"),
    ("kline", "north_flow", "\u5317\u5411\u8d44\u91d1", "#FFA198"),
    ("kline", "limit_up", "\u6da8\u505c\u677f", "#FF7B72"),
    ("kline", "lhb_daily", "\u9f99\u864e\u699c", "#D2A8FF"),
    ("kline", "high_low", "\u65b0\u9ad8\u65b0\u4f4e", "#FFC371"),
    ("kline", "chip_distribution", "\u7b79\u7801\u5206\u5e03", "#56D4DD"),
    ("cache", "fund_flow", "\u8d44\u91d1\u6d41\u5411", "#E6A8D7"),
]


class PanoramaWorker(QThread):
    done = pyqtSignal(object)

    def __init__(self, kline_db, cache_db):
        super().__init__()
        self.kline_db = kline_db
        self.cache_db = cache_db
        self._running = True

    def stop(self):
        self._running = False

    def _find_date_col(self, conn, table):
        try:
            info = conn.execute(f"PRAGMA table_info([{table}])").fetchall()
            for row in info:
                if row[1] in DATE_CANDIDATES:
                    return row[1]
        except Exception:
            pass
        return None

    def _group_intervals(self, months):
        if not months:
            return []
        intervals = []
        start = months[0]
        prev = months[0]
        for m in months[1:]:
            prev_d = date(int(prev[:4]), int(prev[5:7]), 1)
            curr_d = date(int(m[:4]), int(m[5:7]), 1)
            next_month = (prev_d.replace(day=28) + timedelta(days=4)).replace(day=1)
            if curr_d == next_month:
                prev = m
            else:
                end_d = (prev_d.replace(day=28) + timedelta(days=4)).replace(day=1)
                intervals.append((date(int(start[:4]), int(start[5:7]), 1), end_d))
                start = m
                prev = m
        prev_d = date(int(prev[:4]), int(prev[5:7]), 1)
        end_d = (prev_d.replace(day=28) + timedelta(days=4)).replace(day=1)
        intervals.append((date(int(start[:4]), int(start[5:7]), 1), end_d))
        return intervals

    def run(self):
        results = []
        for db_key, table, label, color in TABLES:
            if not self._running:
                return
            db_path = self.kline_db if db_key == "kline" else self.cache_db
            if not db_path:
                continue
            try:
                conn = sqlite3.connect(db_path)
                date_col = self._find_date_col(conn, table)
                if not date_col:
                    conn.close()
                    continue
                rows = conn.execute(
                    f"SELECT strftime('%Y-%m', [{date_col}]) as m, COUNT(*) "
                    f"FROM [{table}] WHERE [{date_col}] IS NOT NULL "
                    f"GROUP BY m ORDER BY m"
                ).fetchall()
                conn.close()
                if not rows:
                    continue
                months = [r[0] for r in rows if r[0]]
                intervals = self._group_intervals(months)
                first_d = date(int(months[0][:4]), int(months[0][5:7]), 1)
                last_d = date(int(months[-1][:4]), int(months[-1][5:7]), 1)
                total_span = ((last_d.year - first_d.year) * 12 + (last_d.month - first_d.month)) + 1
                coverage = len(months) / total_span if total_span > 0 else 0
                results.append({
                    "label": label, "color": color,
                    "intervals": intervals,
                    "coverage": min(coverage, 1.0),
                    "total_months": len(months),
                    "min_date": first_d,
                    "max_date": last_d,
                })
            except Exception:
                pass
        if self._running:
            self.done.emit(results)


class DataPanorama(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMouseTracking(True)
        self.setMinimumHeight(200)
        self._items = []
        self._time_min = None
        self._time_max = None
        self._worker = None

    def load(self, kline_db, cache_db):
        if self._worker and self._worker.isRunning():
            self._worker.stop()
            self._worker.wait(1000)
        self._items = []
        self._time_min = None
        self._time_max = None
        self.update()
        self._worker = PanoramaWorker(kline_db, cache_db)
        self._worker.done.connect(self._on_data)
        self._worker.start()

    def _on_data(self, results):
        self._items = [r for r in results if r.get("intervals")]
        if self._items:
            dates = []
            for it in self._items:
                for s, e in it["intervals"]:
                    dates.append(s)
                    dates.append(e)
            if dates:
                self._time_min = min(dates)
                self._time_max = max(dates)
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        w = self.width()
        h = self.height()

        if not self._items or not self._time_min or not self._time_max:
            painter.setPen(QColor(C_SUBTEXT))
            f = QFont()
            f.setPixelSize(14)
            painter.setFont(f)
            painter.drawText(self.rect(), Qt.AlignCenter, "\u6682\u65e0\u5168\u666f\u6570\u636e")
            painter.end()
            return

        font_label = QFont()
        font_label.setPixelSize(13)
        font_pct = QFont()
        font_pct.setPixelSize(12)
        font_axis = QFont()
        font_axis.setPixelSize(11)

        LABEL_W = 80
        PCT_W = 34
        HEADER_H = 20
        AXIS_H = 30
        PAD = 4

        chart_left = LABEL_W + PCT_W + PAD * 2
        chart_right = w - PAD
        chart_top = HEADER_H
        chart_bottom = h - AXIS_H
        chart_w = chart_right - chart_left
        chart_h = chart_bottom - chart_top

        if chart_h <= 0 or chart_w <= 0:
            painter.end()
            return

        total_days = max((self._time_max - self._time_min).days, 1)

        def to_x(d):
            return chart_left + ((d - self._time_min).days / total_days) * chart_w

        n_items = len(self._items)
        row_h = max(min(chart_h // n_items, 30), 22)
        y_offset = chart_top

        for i, item in enumerate(self._items):
            y = y_offset + i * row_h
            bg = QColor(C_BG) if i % 2 == 0 else QColor(C_PANEL)
            painter.fillRect(0, int(y), w, int(row_h), bg)

            painter.setPen(QColor(item["color"]))
            painter.setFont(font_label)
            painter.drawText(int(PAD), int(y), LABEL_W - PAD, int(row_h),
                             Qt.AlignLeft | Qt.AlignVCenter, item["label"])

            pct_value = item.get("coverage", 0) * 100
            if pct_value >= 90:
                pct_c = QColor("#3fb950")
            elif pct_value >= 70:
                pct_c = QColor("#79C0FF")
            elif pct_value >= 40:
                pct_c = QColor("#FFC371")
            else:
                pct_c = QColor("#FF7B72")
            painter.setPen(pct_c)
            painter.setFont(font_pct)
            painter.drawText(LABEL_W + PAD, int(y), PCT_W, int(row_h),
                             Qt.AlignRight | Qt.AlignVCenter, f"{pct_value:.0f}%")

            intervals = item.get("intervals", [])
            for s, e in intervals:
                x1 = to_x(s)
                x2 = to_x(e)
                if x2 - x1 < 2:
                    x2 = x1 + 2
                bar_m = 5
                bar_h_px = row_h - bar_m * 2
                bar_y_px = y + bar_m

                bc = QColor(item["color"])
                bc.setAlpha(230)
                painter.setBrush(bc)
                painter.setPen(Qt.NoPen)
                painter.drawRoundedRect(QRectF(x1, bar_y_px, x2 - x1, bar_h_px), 3, 3)

            painter.setPen(QPen(QColor("#1A1F28"), 1))
            painter.drawLine(int(chart_left), int(y + row_h), int(chart_right), int(y + row_h))

        axis_y = chart_bottom + 4
        span_months = (self._time_max.year - self._time_min.year) * 12 \
                      + (self._time_max.month - self._time_min.month)

        if span_months <= 12:
            tick_interval = 1
        elif span_months <= 36:
            tick_interval = 3
        else:
            tick_interval = 6

        painter.setPen(QPen(QColor("#30363D"), 1))
        d = date(self._time_min.year, self._time_min.month, 1)
        end = date(self._time_max.year, self._time_max.month, 1)
        if end < d:
            end = d
        tick_dates = []
        while d <= end:
            tick_dates.append(date(d.year, d.month, 1))
            d = (d.replace(day=28) + timedelta(days=4 * tick_interval * 30)).replace(day=1)

        for td in tick_dates:
            x = to_x(td)
            if chart_left <= x <= chart_right:
                painter.drawLine(int(x), int(chart_top), int(x), int(chart_bottom))

        painter.setPen(QColor(C_SUBTEXT))
        painter.setFont(font_axis)
        for td in tick_dates:
            x = to_x(td)
            if chart_left - 5 <= x <= chart_right + 5:
                if span_months <= 12:
                    label = f"{td.month}\u6708"
                elif span_months <= 36:
                    label = f"{str(td.year)[2:]}Q{(td.month - 1) // 3 + 1}"
                else:
                    label = f"{str(td.year)[2:]}-{td.month:02d}"
                painter.drawText(QRectF(x - 28, axis_y, 56, 16), Qt.AlignCenter, label)

        painter.end()

    def mouseMoveEvent(self, event):
        if not self._items or not self._time_min or not self._time_max:
            QToolTip.hideText()
            return

        w = self.width()
        h = self.height()

        LABEL_W = 80
        PCT_W = 34
        HEADER_H = 20
        AXIS_H = 30
        PAD = 4
        chart_left = LABEL_W + PCT_W + PAD * 2
        chart_right = w - PAD
        chart_top = HEADER_H
        chart_bottom = h - AXIS_H
        chart_w = chart_right - chart_left
        chart_h = chart_bottom - chart_top

        if chart_h <= 0 or chart_w <= 0:
            QToolTip.hideText()
            return

        total_days = max((self._time_max - self._time_min).days, 1)

        def to_x(d):
            return chart_left + ((d - self._time_min).days / total_days) * chart_w

        n_items = len(self._items)
        row_h = max(min(chart_h // n_items, 30), 22)
        y_offset = chart_top

        mx = event.x()
        my = event.y()

        found = False
        for i, item in enumerate(self._items):
            y = y_offset + i * row_h
            if y <= my <= y + row_h:
                for s, e in item.get("intervals", []):
                    x1 = to_x(s)
                    x2 = to_x(e)
                    if x2 - x1 < 2:
                        x2 = x1 + 2
                    if x1 <= mx <= x2:
                        QToolTip.showText(
                            event.globalPos(),
                            f"{item['label']}\n{s.strftime('%Y-%m-%d')} ~ {e.strftime('%Y-%m-%d')}"
                        )
                        found = True
                        break
                break

        if not found:
            QToolTip.hideText()
