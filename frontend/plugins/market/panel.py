"""Market Panel -- 大盘指数 + 板块表现"""
import sqlite3, traceback
from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QTableWidget, QTableWidgetItem, QHeaderView, QFrame, QAbstractItemView,
    QPushButton)
from frontend.platform.theme import (
    dp, dps, fs, tr,
    C_BG, C_PANEL, C_BORDER, C_BORDER_SOFT, C_TEXT, C_SUBTEXT, C_FAINT,
    C_ACCENT, C_GOLD, C_UP as C_RISE, C_DOWN as C_FALL, C_RAISED as C_HOVER,
    qss_table, style_h1, style_label, style_caption, style_title,
)
from frontend.platform.premium import (
    PAL, card_qss, value_ss, label_ss, hero_ss, SectionTitle, SplitBar, well,
)
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QColor, QFont
from frontend.platform.local_worker import LocalWorker


INDEX_MAP = {
    "sh000001": "上证指数", "sz399001": "深证成指",
    "sz399006": "创业板指", "sh000688": "科创50",
    "sh000300": "沪深300",
}
# Only codes that actually exist in kline_daily render; the rest gracefully skip.
_PRESENT = {c for c in INDEX_MAP}


class MarketPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.db_path = None
        self.on_open_kline = None
        self.on_status = None
        self.setStyleSheet(f"background:{C_BG}")
        self._build_ui()

    def _build_ui(self):
        lo = QVBoxLayout(self)
        lo.setContentsMargins(dp(14), dp(12), dp(14), dp(12))
        lo.setSpacing(dp(12))

        # ── Page header: 标题(无冗余说明) ──
        head = QHBoxLayout(); head.setSpacing(dp(10))
        title = QLabel("看盘")
        title.setStyleSheet(style_title())
        head.addWidget(title)
        head.addStretch()
        lo.addLayout(head)

        # ── 市场环境条 (牛/熊/震荡 + 建议策略 + 系统风险) ──
        self._regime_card = well("card")
        rl = QHBoxLayout(self._regime_card)
        rl.setContentsMargins(dp(14), dp(9), dp(14), dp(9))
        rl.setSpacing(dp(10))
        self._regime_lbl = QLabel("市场环境 --")
        self._regime_lbl.setStyleSheet(value_ss(size=15, gold=True))
        rl.addWidget(self._regime_lbl)
        self._regime_strat = QLabel("")
        self._regime_strat.setStyleSheet(label_ss(size=10) + f"color:{C_SUBTEXT};")
        rl.addWidget(self._regime_strat)
        rl.addStretch()
        self._regime_risk = QLabel("")
        self._regime_risk.setStyleSheet(label_ss(size=9) + f"color:{C_FALL};")
        self._regime_risk.setWordWrap(True)
        rl.addWidget(self._regime_risk)
        lo.addWidget(self._regime_card)

        # ── 📰 今日事件驱动 (突发利好·短期观察, 不进长期策略) ──
        self._news_card = well("card")
        nl = QVBoxLayout(self._news_card)
        nl.setContentsMargins(dp(14), dp(9), dp(14), dp(9))
        nl.setSpacing(dp(5))
        nrow = QHBoxLayout(); nrow.setSpacing(dp(8))
        ntitle = SectionTitle("今日事件驱动")
        nrow.addWidget(ntitle)
        self._news_tag = QLabel("📰 突发利好 · 短期观察")
        self._news_tag.setStyleSheet(label_ss(size=9) + f"color:{C_FALL};")
        nrow.addWidget(self._news_tag)
        nrow.addStretch()
        self._news_asof = QLabel("")
        self._news_asof.setStyleSheet(label_ss(size=9) + f"color:{C_FAINT};")
        nrow.addWidget(self._news_asof)
        nl.addLayout(nrow)
        self._news_topics_lbl = QLabel("")
        self._news_topics_lbl.setStyleSheet(label_ss(size=9) + f"color:{C_SUBTEXT};")
        self._news_topics_lbl.setWordWrap(True)
        self._news_topics_lbl.setMaximumHeight(dp(30))
        nl.addWidget(self._news_topics_lbl)
        # 事件股 chips(横向滚动)
        self._news_chips = QHBoxLayout(); self._news_chips.setSpacing(dp(6))
        nl.addLayout(self._news_chips)
        lo.addWidget(self._news_card)

        # ── Index hero cards ──
        self.card_row = QHBoxLayout()
        self.card_row.setSpacing(dp(10))
        lo.addLayout(self.card_row)

        # ── Breadth: 涨跌分布(去文字标签, 大数字+比例条) ──
        bar = well("card")
        bl = QVBoxLayout(bar)
        bl.setContentsMargins(dp(14), dp(10), dp(14), dp(10))
        bl.setSpacing(dp(6))
        bt = QHBoxLayout(); bt.setSpacing(dp(8))
        btL = SectionTitle("今日涨跌")
        bt.addWidget(btL); bt.addStretch()
        self._date_lbl = QLabel("--")
        self._date_lbl.setStyleSheet(label_ss(size=10) + f"color:{C_FAINT};")
        bt.addWidget(self._date_lbl)
        bl.addLayout(bt)

        stats_row = QHBoxLayout()
        stats_row.setSpacing(dp(26))
        # 只用两个主数字: 上涨 / 下跌 (小红绿, 不带文字, 数字大)
        self.bar_widgets = {}
        for key, colorize in [("up", True), ("dn", True)]:
            col = QVBoxLayout(); col.setSpacing(0)
            w = QLabel("--")
            w.setStyleSheet(value_ss(size=19, gold=colorize))
            col.addWidget(w)
            stats_row.addLayout(col)
            self.bar_widgets[key] = w
        stats_row.addStretch()
        bl.addLayout(stats_row)

        self._split = SplitBar()
        self._split.setMinimumHeight(dp(18))
        bl.addWidget(self._split)
        # 平盘/总数/成交额 收进一行小字(角落, 不抢视觉)
        small = QLabel("--")
        small.setStyleSheet(label_ss(size=9) + f"color:{C_FAINT};")
        self._small_stat = small
        bl.addWidget(small)
        lo.addWidget(bar)

        # ── 板块 Tabs ──
        self._sector_type = "industry"
        tabs = QHBoxLayout(); tabs.setSpacing(dp(6))
        st = SectionTitle("板块表现")
        tabs.addWidget(st)
        tabs.addStretch()
        self._btn_ind = QPushButton("行业板块")
        self._btn_ind.setCheckable(True)
        self._btn_ind.setChecked(True)
        self._btn_ind.clicked.connect(lambda: (setattr(self, "_sector_type", "industry"),
            self._btn_ind.setChecked(True), self._btn_cpt.setChecked(False), self._load_sectors()))
        self._btn_cpt = QPushButton("概念板块")
        self._btn_cpt.setCheckable(True)
        self._btn_cpt.clicked.connect(lambda: (setattr(self, "_sector_type", "concept"),
            self._btn_cpt.setChecked(True), self._btn_ind.setChecked(False), self._load_sectors()))
        for btn in [self._btn_ind, self._btn_cpt]:
            btn.setFixedHeight(dp(28))
            btn.setCursor(Qt.PointingHandCursor)
            # 内联选中样式(父级 setStyleSheet 破坏全局 indBtn 背景级联, 须内联)
            btn.setStyleSheet(
                f"QPushButton{{background:{PAL['c_mid']};color:{PAL['sub']};"
                f"border:1px solid {PAL['border_lo']};border-top:1px solid {PAL['border_hi']};"
                f"border-radius:{dps(6)};font-size:{fs(tr(12))};font-weight:600;padding:{dps(3)} {dps(12)};}}"
                f"QPushButton:hover{{color:{PAL['text']};border-top-color:{PAL['gold']};}}"
                f"QPushButton:checked{{background:{PAL['gold']};color:#14110B;border-color:{PAL['gold']};}}")
            tabs.addWidget(btn)
        lo.addLayout(tabs)

        self.table = QTableWidget()
        self.table.setStyleSheet(qss_table())
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.cellClicked.connect(self._on_click)
        self.table.verticalHeader().setVisible(False)
        self.table.setShowGrid(False)
        lo.addWidget(self.table, 1)

    def _load_sectors(self):
        if getattr(self, "_sector_worker", None) is not None and self._sector_worker.isRunning():
            return
        self._sector_worker = LocalWorker(self._work_sectors, "sectors", args=[self._sector_type])
        self._sector_worker.result.connect(self._on_sectors)
        self._sector_worker.start()

    def _work_sectors(self, stype):
        conn = sqlite3.connect(self.db_path)
        try:
            rows = conn.execute(
                'SELECT name, rank, latest_price, change_pct, up_count, dn_count, leader, leader_chg '
                'FROM sector_board WHERE type = ? ORDER BY rank LIMIT 12', (stype,)
            ).fetchall()
            return {"code": 0, "sectors": [
                {"name": r[0], "rank": r[1], "price": r[2], "change_pct": r[3],
                 "up": r[4], "dn": r[5], "leader": r[6], "leader_chg": r[7]} for r in rows
            ]}
        finally:
            conn.close()

    def _on_sectors(self, tag, data):
        if data.get("code") != 0: return
        sectors = data.get("sectors", [])
        self._build_sector_table(sectors)
        label = "行业板块" if self._sector_type == "industry" else "概念板块"
        if self.on_status: self.on_status(f"{label}已加载 - {len(sectors)}条")

    def on_theme_changed(self):
        self.table.setStyleSheet(qss_table())
        self.table.viewport().update()
        self.update()

    def load(self):
        if not self.db_path:
            return
        if getattr(self, "_worker", None) is not None and self._worker.isRunning():
            return
        if self.on_status:
            self.on_status("加载市场数据...")
        self._worker = LocalWorker(self._work_market, "market")
        self._worker.result.connect(self._on_market)
        self._worker.start()
        # 板块表也随激活自动加载(否则打开市场页时板块区空白, 需手动点'行业板块')
        if getattr(self, "_sector_worker", None) is None or not self._sector_worker.isRunning():
            self._load_sectors()

    def _work_market(self):
        conn = sqlite3.connect(self.db_path)
        try:
            dates = conn.execute(
                "SELECT DISTINCT date FROM kline_daily ORDER BY date DESC LIMIT 2"
            ).fetchall()
            if len(dates) < 2:
                return {"code": -1, "error": "数据不足"}
            d_latest, d_prev = dates[0][0], dates[1][0]

            idx_codes = list(INDEX_MAP.keys())

            # Each index has its own data freshness (they lag the global max).
            # Look up the LATEST date per index so stale indices still show a real
            # price, not 0.00. Indices with zero rows are dropped entirely.
            idx_final = {}
            for code in idx_codes:
                latest = conn.execute(
                    "SELECT MAX(date) FROM kline_daily WHERE code=?", (code,)
                ).fetchone()[0]
                if not latest:
                    continue
                prev = conn.execute(
                    "SELECT MAX(date) FROM kline_daily WHERE code=? AND date<?", (code, latest)
                ).fetchone()[0]
                cur = conn.execute(
                    "SELECT close FROM kline_daily WHERE code=? AND date=?", (code, latest)
                ).fetchone()
                prv = conn.execute(
                    "SELECT close FROM kline_daily WHERE code=? AND date=?", (code, prev)
                ).fetchone() if prev else None
                idx_final[code] = {
                    "price": cur[0] if cur else None,
                    "prev": prv[0] if prv else None,
                    "date": latest,
                }

            indices = []
            for code in idx_codes:
                if code not in idx_final or idx_final[code]["price"] is None:
                    continue
                cur = idx_final[code]["price"]
                prv = idx_final[code]["prev"]
                cp = (cur - prv) / prv * 100 if cur and prv else 0
                indices.append({
                    "code": code, "name": INDEX_MAP[code],
                    "price": cur, "change_pct": round(cp, 2),
                    "date": idx_final[code].get("date"),
                })

            today_rows = conn.execute(
                "SELECT code, close, volume FROM kline_daily WHERE date = ?", (d_latest,)
            ).fetchall()
            prev_rows = conn.execute(
                "SELECT code, close FROM kline_daily WHERE date = ?", (d_prev,)
            ).fetchall()
            prev_map = dict(prev_rows)
            total_up = total_dn = total_flat = 0
            total_vol = 0.0
            for code, close, volume in today_rows:
                total_vol += float(volume or 0)
                prv = prev_map.get(code)
                cp = (float(close) - float(prv)) / float(prv) * 100 if prv and prv > 0 else 0
                if cp > 0: total_up += 1
                elif cp < 0: total_dn += 1
                else: total_flat += 1
            return {"code": 0, "indices": indices, "stats": {
                "date": d_latest,
                "up": total_up, "dn": total_dn, "flat": total_flat,
                "count": total_up + total_dn + total_flat, "volume": total_vol,
            }}
        finally:
            conn.close()

    def _on_market(self, tag, data):
        if data.get("code") != 0:
            if self.on_status:
                self.on_status("市场数据加载失败")
            return

        indices = data.get("indices", [])
        stats = data.get("stats", {})

        while self.card_row.count():
            w = self.card_row.takeAt(0).widget()
            if w:
                w.deleteLater()

        for d in indices:
            card = well("card")
            card.setFixedSize(dp(150), dp(110))
            card.setCursor(Qt.PointingHandCursor)
            card._code = d.get("code", "")
            card._name = d.get("name", "")
            orig_mpe = card.mousePressEvent
            def _make_click(c, n):
                def handler(e, cc=c, nn=n):
                    if orig_mpe:
                        orig_mpe(e)
                    if e.button() == Qt.LeftButton and self.on_open_kline:
                        self.on_open_kline(cc, nn)
                return handler
            card.mousePressEvent = _make_click(card._code, card._name)

            cl = QVBoxLayout(card)
            cl.setContentsMargins(dp(12), dp(9), dp(12), dp(9))
            cl.setSpacing(2)

            nm = QLabel(d.get("name", ""))
            nm.setStyleSheet(label_ss(size=10, gold=True))
            cl.addWidget(nm)

            p = QLabel("{:.2f}".format(d.get("price", 0)))
            p.setStyleSheet(hero_ss(size=17))
            cl.addWidget(p)

            chg = d.get("change_pct", 0)
            color = C_RISE if chg >= 0 else C_FALL
            c = QLabel("{}{:.2f}%".format("+" if chg >= 0 else "", chg))
            c.setStyleSheet(f"color:{color};font-size:{fs(tr(12))};font-weight:600;background:transparent")
            cl.addWidget(c)

            # 数据日期(每个指数自己的最新交易日)
            dt = d.get("date")
            dd = QLabel(f"数据至 {_fmt_date(dt)}" if dt else "数据至 —")
            dd.setStyleSheet(label_ss(size=8) + f"color:{C_FAINT};")
            cl.addWidget(dd)

            self.card_row.addWidget(card)
        if not indices:
            self.card_row.addStretch()

        fmt_vol = lambda v: "{:.0f}亿".format(v / 1e8) if v else "--"
        self._date_lbl.setText(str(stats.get("date", "--")))
        self.bar_widgets["up"].setText(str(stats.get("up", 0)))
        self.bar_widgets["up"].setStyleSheet(value_ss(size=19, gold=True))
        self.bar_widgets["dn"].setText(str(stats.get("dn", 0)))
        self.bar_widgets["dn"].setStyleSheet(value_ss(size=19, gold=True))
        # 平盘/总数/成交额 → 右上角一行小字
        sm = "平盘 {} · 共 {} · 成交 {}".format(
            stats.get("flat", 0), stats.get("count", 0), fmt_vol(stats.get("volume", 0)))
        self._small_stat.setText(sm)
        # 今日涨跌分布(只有涨/跌两段, 平盘忽略)
        self._split.set_data(stats.get("up", 0), stats.get("dn", 0), 0)

        if self.on_status:
            self.on_status(f"市场数据已加载 - {stats.get('date', '')}")
        self._load_sectors()
        self._load_regime()
        self._load_news_driven()

    def _load_news_driven(self):
        """读 data/news_driven.json 填充'今日事件驱动'卡(突发利好·短期观察)."""
        import os, json
        path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
            os.path.dirname(os.path.abspath(__file__))))), 'data', 'news_driven.json')
        try:
            with open(path, encoding='utf-8') as f:
                nd = json.load(f)
        except Exception:
            return
        if not isinstance(nd, dict) or not nd.get('entries') and not nd.get('hot_sectors'):
            return
        as_of = nd.get('as_of', '')
        self._news_asof.setText(f"数据至 {str(as_of)[:4]}-{str(as_of)[4:6]}-{str(as_of)[6:8]}" if as_of else "")
        # 热门话题(豆包搜到的当日消息)
        topics = [t for t in (nd.get('topics') or []) if t][:3]
        if topics:
            self._news_topics_lbl.setText(" · ".join(topics))
        # 事件股 chips (涨停/板板块领涨, 前8)
        while self._news_chips.count():
            w = self._news_chips.takeAt(0).widget()
            if w: w.deleteLater()
        entries = (nd.get('entries') or [])[:8]
        btn_qss = ("QPushButton{{background:{bg};color:{fg};border:1px solid {bd};"
                   "border-radius:{r};padding:{p};font-size:{fs};}}"
                   "QPushButton:hover{{border-color:{acc};}}").format(
                       bg="transparent", fg=C_SUBTEXT, bd=C_BORDER_SOFT, r=dps(5), p="2px 10px", fs=fs(tr(11)), acc=C_GOLD)
        for e in entries:
            name = e.get('name') or e.get('code')
            chg = e.get('change_pct')
            lbl = name
            b = QPushButton(lbl)
            b.setCursor(Qt.PointingHandCursor)
            b.setStyleSheet(btn_qss)
            b.setToolTip(f"{name}({e.get('code')}) {f'{chg:+.1f}%' if chg is not None else ''}\n"
                         f"来源: {e.get('source')} · {e.get('reason')}\n板块: {e.get('sector') or '—'}\n⚠ 突发利好·短期观察, 不进长期策略")
            code = e.get('code', '')
            b.clicked.connect(lambda _=False, c=code: self._open_news_kline(c))
            self._news_chips.addWidget(b)
        self._news_chips.addStretch()

    def _open_news_kline(self, code):
        """点事件股chip → 打开该股K线(若支持)."""
        try:
            if not code: return
            if self.on_open_kline:
                self.on_open_kline(code, "")
        except Exception:
            pass

    def _load_regime(self):
        """读 data/regime.json 填充市场环境条 (牛/熊/震荡 + 建议策略 + 系统风险)."""
        import os, json
        path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
            os.path.dirname(os.path.abspath(__file__))))), 'data', 'regime.json')
        try:
            with open(path, encoding='utf-8') as f:
                r = json.load(f)
        except Exception:
            return
        if not isinstance(r, dict) or not r.get('regime_cn'):
            return
        rc = r.get('regime_cn', '--')
        as_of = r.get('as_of', '')
        self._regime_lbl.setText(f"市场环境 · {rc}")
        strat = r.get('suggest_strategy')
        lst = r.get('suggest_list') or []
        rot = r.get('rotation') or {}
        basis = rot.get('basis', '')
        # 权重动态化展示
        dw = r.get('dyn_weights') or {}
        if dw:
            parts = []
            lbl = {"BP": "价值", "REVERSAL_20": "反转", "VOLATILITY_20": "低波"}
            for f, w in dw.items():
                nm = lbl.get(f, f)
                parts.append(f"{nm}{w:+.1f}")
            self._regime_strat.setText(
                f"建议策略: {strat} · 权重[{'  '.join(parts)}]" if strat else f"权重[{'  '.join(parts)}]")
            tip = (f"当前环境因子权重(BP价值/REV反转/VOL低波): 牛市重进攻、熊市重防守\n"
                   f"适配策略: {' · '.join(lst)}\n"
                   + (f"轮换依据: {basis}\n" if basis else "")
                   + f"数据至 {as_of}")
            self._regime_strat.setToolTip(tip)
        elif strat:
            self._regime_strat.setText(f"建议策略: {strat}")
            tip = f"当前环境适配: {' · '.join(lst)}"
            if basis:
                tip += f"\n轮换依据: {basis}"
            self._regime_strat.setToolTip(tip + f" (数据至 {as_of})")
        if not self._regime_risk.text():
            sr = r.get('sys_risk') or {}
            if sr.get('triggered'):
                self._regime_risk.setText("⚠ " + sr['reason'])
            else:
                dd = sr.get('drawdown')
                self._regime_risk.setText(f"回撤 {dd*100:.1f}%" if dd else "")

    def _build_sector_table(self, sectors):
        cols = ["板块", "排名", "价格", "涨跌幅", "领涨股", "领涨涨幅"]
        self.table.setRowCount(len(sectors))
        self.table.setColumnCount(len(cols))
        self.table.setHorizontalHeaderLabels(cols)

        for i, b in enumerate(sectors):
            bg = QColor(PAL["c_mid"]) if i % 2 else QColor(PAL["bg"])
            change = b.get("change_pct", 0)
            chg_color = C_RISE if change >= 0 else C_FALL
            ldr_chg = b.get("leader_chg", 0)
            ldr_color = C_RISE if ldr_chg >= 0 else C_FALL

            items = [
                (b.get("name", ""), C_TEXT),
                (str(b.get("rank", "")), C_SUBTEXT),
                ("{:.2f}".format(b.get("price", 0) or 0), C_TEXT),
                ("{}{:.2f}%".format("+" if change >= 0 else "", change), chg_color),
                (b.get("leader", "--"), C_SUBTEXT),
                ("{}{:.2f}%".format("+" if ldr_chg >= 0 else "", ldr_chg), ldr_color),
            ]
            for j, (text, color) in enumerate(items):
                it = QTableWidgetItem(text)
                it.setForeground(QColor(color))
                it.setBackground(bg)
                it.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
                it.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter if j > 0 else Qt.AlignLeft | Qt.AlignVCenter)
                self.table.setItem(i, j, it)

        self.table.resizeColumnsToContents()
        self.table.setColumnWidth(0, dp(100))
        for j in range(1, len(cols)):
            if self.table.columnWidth(j) < 55:
                self.table.setColumnWidth(j, dp(55))

    def _on_click(self, row, col):
        pass


def _fmt_date(d):
    """把 'YYYYMMDD' / 'YYYY-MM-DD HH:MM:SS' 归一化为 'YYYY-MM-DD'."""
    s = str(d).strip()
    s = s[:10].replace('/', '-')
    if len(s) == 8 and s.isdigit():
        return s[:4] + "-" + s[4:6] + "-" + s[6:8]
    return s
