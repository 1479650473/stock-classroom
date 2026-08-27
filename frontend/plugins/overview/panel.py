# -*- coding: utf-8 -*-
"""总览面板 —— 产品核心入口.

布局(自上而下):
  ① 页头: "总览" + 数据截止说明
  ② 核心账户卡: AI账户(净值/总资产/持仓/盈亏) + 主账户(市值/盈亏)
  ③ 最近策略: 5因子家族里当前最强(总收益/年化/α/回撤) 一键跳研究
  ④ 市场速览: 指数卡(上证/科创50 等, 读 kline)
  ⑤ 主功能入口: 研究/选股/持仓/交易/AI操盘 大按钮
  ⑥ 账户中心: 全部账户表(余额/市值/总资产/盈亏/持仓数) + 新建/改名/重置/删除
"""
import os, json, sqlite3
from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame,
    QPushButton, QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView,
    QInputDialog, QMessageBox, QComboBox, QLineEdit, QGridLayout)
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont, QColor, QPainter, QPainterPath, QPen
from PyQt5.QtCore import QRectF

from frontend.platform.theme import (
    dp, dps, fs, tr,
    C_BG, C_BORDER, C_BORDER_SOFT, C_TEXT, C_SUBTEXT, C_FAINT, C_ACCENT, C_GOLD,
    C_UP as C_RISE, C_DOWN as C_FALL, qss_table, style_title, style_label, style_caption,
)
from frontend.platform.premium import PAL, card_qss, value_ss, label_ss, hero_ss, SectionTitle, well
from frontend.platform.local_worker import LocalWorker

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


class MiniNavSpark(QWidget):
    """账户净值 mini 曲线(纯色折线, 无 QLinearGradient, 防 DLL 硬崩)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._nav = []
        self.setMinimumHeight(dp(26))
        self.setMinimumWidth(dp(180))

    def set_nav(self, nav):
        self._nav = [float(x) for x in (nav or []) if x is not None]
        self.update()

    def paintEvent(self, _e):
        if len(self._nav) < 2:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        lo, hi = min(self._nav), max(self._nav)
        rng = (hi - lo) or 1.0
        pad = 3.0
        n = len(self._nav)
        pts = []
        for i, v in enumerate(self._nav):
            x = pad + (w - 2 * pad) * i / (n - 1)
            y = h - pad - (h - 2 * pad) * ((v - lo) / rng)
            pts.append((x, y))
        # 折线
        up = self._nav[-1] >= self._nav[0]
        color = QColor(PAL['up'] if up else PAL['down'])
        pen = QPen(color); pen.setWidthF(1.6); pen.setCosmetic(True)
        p.setPen(pen)
        path = QPainterPath()
        path.moveTo(pts[0][0], pts[0][1])
        for x, y in pts[1:]:
            path.lineTo(x, y)
        p.drawPath(path)
        # 末点
        p.setPen(Qt.NoPen); p.setBrush(color)
        p.drawEllipse(QRectF(pts[-1][0] - 2, pts[-1][1] - 2, 4, 4))
        p.end()


class OverviewPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._db_path = None
        self._services = None
        self.setStyleSheet(f"background:{C_BG}")
        self._build_ui()

    def set_kline_db(self, path):
        self._db_path = path

    def set_services(self, services):
        self._services = services

    # ── UI 骨架 ──────────────────────────────────────────────
    def _build_ui(self):
        lo = QVBoxLayout(self)
        lo.setContentsMargins(dp(16), dp(14), dp(16), dp(14))
        lo.setSpacing(dp(12))

        # 页头
        head = QHBoxLayout(); head.setSpacing(dp(10))
        title = QLabel("总览")
        title.setStyleSheet(style_title())
        head.addWidget(title)
        self._asof_lbl = QLabel("—")
        self._asof_lbl.setStyleSheet(label_ss(size=10) + f"color:{C_FAINT};padding-top:{dp(4)}px;")
        head.addWidget(self._asof_lbl)
        head.addStretch()
        lo.addLayout(head)

        # 核心账户卡
        lo.addWidget(SectionTitle("核心账户", size=12))
        self._acct_row = QHBoxLayout(); self._acct_row.setSpacing(dp(10))
        lo.addLayout(self._acct_row)
        self._acct_cards = {}

        # 最近策略
        lo.addWidget(SectionTitle("最近策略 · 最强家族", size=12))
        self._strat_frame = well("card"); self._strat_frame.setMinimumHeight(dp(96))
        slo = QVBoxLayout(self._strat_frame); slo.setContentsMargins(dp(12), dp(10), dp(12), dp(10)); slo.setSpacing(dp(4))
        self._strat_name = QLabel("—"); self._strat_name.setStyleSheet(hero_ss(size=13) + f"color:{PAL['accent']};")
        slo.addWidget(self._strat_name)
        self._strat_desc = QLabel("")
        self._strat_desc.setStyleSheet(value_ss(size=10) + f"color:{C_SUBTEXT};")
        slo.addWidget(self._strat_desc)
        self._strat_metrics = QLabel("")
        self._strat_metrics.setStyleSheet(label_ss(size=9) + f"color:{C_FAINT};")
        slo.addWidget(self._strat_metrics)
        lo.addWidget(self._strat_frame)

        # 市场速览
        lo.addWidget(SectionTitle("市场速览", size=12))
        self._mkt_row = QHBoxLayout(); self._mkt_row.setSpacing(dp(10))
        lo.addLayout(self._mkt_row)
        self._mkt_cards = {}

        # 主功能入口
        lo.addWidget(SectionTitle("主功能", size=12))
        self._nav_row = QHBoxLayout(); self._nav_row.setSpacing(dp(8))
        for pid, label, payload in [
            ("research", "研究", {"hp": 20}), ("picks", "选股", None),
            ("holdings", "持仓", None), ("trade", "交易", None),
            ("agentops", "AI操盘", None)]:
            btn = QPushButton(label)
            btn.setObjectName("navBtn")
            btn.setFixedHeight(dp(40))
            btn.setCursor(Qt.PointingHandCursor)
            btn.clicked.connect(lambda _=False, p=pid, pl=payload: self._go(p, pl))
            self._nav_row.addWidget(btn)
        lo.addLayout(self._nav_row)

        # 账户中心
        lo.addWidget(SectionTitle("账户中心", size=12))
        acct = well("card")
        alo = QVBoxLayout(acct); alo.setContentsMargins(dp(12), dp(8), dp(12), dp(10)); alo.setSpacing(dp(6))
        self._acct_table = QTableWidget()
        self._acct_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._acct_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._acct_table.verticalHeader().setVisible(False); self._acct_table.setShowGrid(False)
        self._acct_table.verticalHeader().setDefaultSectionSize(dp(24))
        self._acct_table.setFont(QFont("Microsoft YaHei", int(str(fs(tr(10))).replace("px", ""))))
        alo.addWidget(self._acct_table)
        # 账户操作行
        arow = QHBoxLayout(); arow.setSpacing(dp(6))
        self._acct_combo = QComboBox(); self._acct_combo.setFixedHeight(dp(28))
        self._acct_combo.setStyleSheet(
            f"QComboBox{{background:{PAL['c_mid']};border:1px solid {PAL['border_lo']};"
            f"border-radius:5px;padding:2px 8px;color:{PAL['text']};}}"
            f"QComboBox::drop-down{{border:none;}}")
        arow.addWidget(self._acct_combo)
        for txt, cb in [("+ 新建", self._new_account), ("改名", self._rename_account),
                        ("重置", self._reset_account), ("删除", self._delete_account)]:
            b = QPushButton(txt); b.setObjectName("indBtn"); b.setFixedHeight(dp(28))
            b.setCursor(Qt.PointingHandCursor); b.clicked.connect(cb)
            arow.addWidget(b)
        arow.addStretch()
        alo.addLayout(arow)
        lo.addWidget(acct)
        lo.addStretch()

    # ── 数据加载 ─────────────────────────────────────────────
    def load(self):
        self._load_accounts()
        self._load_strategy()
        self._load_market()

    def _go(self, plugin_id, payload=None):
        if self._services is not None:
            self._services.navigate(plugin_id, payload)

    # ── 账户 ────────────────────────────────────────────────
    def _load_accounts(self):
        try:
            from trade_engine.engine import TradeEngine
            eng = TradeEngine()
            summaries = eng.list_account_summaries()
        except Exception as e:
            summaries = []
        # 核心账户卡(前两个: 默认主账户 + AI账户)
        self._clear(self._acct_row)
        self._acct_cards = {}
        for s in summaries[:2]:
            card = self._acct_card(s, nav=self._nav_of(s["account_id"]))
            self._acct_row.addWidget(card)
            self._acct_cards[s["account_id"]] = card
        if not summaries:
            empty = QLabel("暂无账户 — 点击下方'新建'")
            empty.setStyleSheet(value_ss(size=11) + f"color:{C_FAINT};")
            self._acct_row.addWidget(empty)
        # 账户表(左栏 360px 偏窄: 精简列+显式宽度, 免横向滚动)
        if summaries:
            self._acct_table.setColumnCount(4)
            self._acct_table.setHorizontalHeaderLabels(["账户名", "总资产", "盈亏", "持有"])
            self._acct_table.setRowCount(len(summaries))
            for i, s in enumerate(summaries):
                row = [s["name"], f"{s['total_assets']:,.0f}",
                       f"{s['total_profit']:+,.0f}", str(s["positions"])]
                for j, v in enumerate(row):
                    it = QTableWidgetItem(v)
                    it.setTextAlignment(Qt.AlignCenter)
                    if j == 2:
                        col = C_RISE if s["total_profit"] >= 0 else C_FALL
                        it.setForeground(QColor(col))
                    self._acct_table.setItem(i, j, it)
            hh = self._acct_table.horizontalHeader()
            for j, w in enumerate([120, 100, 90, 50]):
                hh.resizeSection(j, dp(w))
        else:
            self._acct_table.setRowCount(0)
        self._acct_table.horizontalHeader().setStretchLastSection(True)
        # 账户选择下拉
        self._acct_combo.blockSignals(True)
        self._acct_combo.clear()
        for s in summaries:
            self._acct_combo.addItem(f"[{s['account_id']}] {s['name']}", s["account_id"])
        self._acct_combo.blockSignals(False)

    def _nav_of(self, account_id):
        """取账户真实净值曲线(snapshot_nav 累计). 无快照→[]."""
        try:
            from trade_engine.engine import TradeEngine
            h = TradeEngine().get_nav_history(account_id)
            return h.get("nav", [])
        except Exception:
            return []

    def _acct_card(self, s, nav=None):
        card = well("card"); card.setMinimumHeight(dp(84))
        lo = QVBoxLayout(card); lo.setContentsMargins(dp(12), dp(8), dp(12), dp(8)); lo.setSpacing(dp(2))
        nm = QLabel(s["name"]); nm.setStyleSheet(label_ss(size=9) + f"color:{C_FAINT};")
        lo.addWidget(nm)
        val = QLabel(f"{s['total_assets']:,.0f}"); val.setStyleSheet(hero_ss(size=15) + f"color:{PAL['accent']};")
        lo.addWidget(val)
        pnl = QLabel(f"盈亏 {s['total_profit']:+,.0f} · 持仓 {s['positions']} · 市值 {s['market_value']:,.0f}")
        col = C_RISE if s["total_profit"] >= 0 else C_FALL
        pnl.setStyleSheet(label_ss(size=8) + f"color:{col};")
        lo.addWidget(pnl)
        # 净值 mini 曲线(有真实快照才画; 单点/无→显示平线+提示)
        if nav is not None:
            spark = MiniNavSpark()
            if len(nav) >= 2:
                spark.set_nav(nav)
                lo.addWidget(spark)
            else:
                hint = QLabel("净值曲线自今日起记录")
                hint.setStyleSheet(label_ss(size=8) + f"color:{C_FAINT};")
                lo.addWidget(hint)
        return card

    def _new_account(self):
        name, ok = QInputDialog.getText(self, "新建模拟账户", "账户名称:", text="主账户")
        if not ok or not name.strip():
            return
        cap, ok2 = QInputDialog.getDouble(self, "初始资金", "初始资金(元):", 100000, 1000, 1e9, 0)
        if not ok2:
            return
        try:
            from trade_engine.engine import TradeEngine
            eng = TradeEngine()
            eng.create_account(name.strip(), int(cap))
            self._services.status(f"账户 {name} 已创建")
            self.load()
        except Exception as e:
            QMessageBox.warning(self, "失败", str(e))

    def _rename_account(self):
        aid = self._acct_combo.currentData()
        if not aid:
            return
        from trade_engine.engine import TradeEngine
        eng = TradeEngine()
        acc = eng.get_account(aid)
        if not acc:
            return
        name, ok = QInputDialog.getText(self, "重命名账户", "新名称:", text=acc["name"])
        if ok and name.strip():
            eng.rename_account(aid, name.strip())
            self._services.status("账户已重命名")
            self.load()

    def _reset_account(self):
        aid = self._acct_combo.currentData()
        if not aid:
            return
        if QMessageBox.question(self, "重置账户", f"清空账户[{aid}]的持仓与订单并恢复初始资金?") == QMessageBox.Yes:
            from trade_engine.engine import TradeEngine
            TradeEngine().reset_account(aid)
            self._services.status("账户已重置")
            self.load()

    def _delete_account(self):
        aid = self._acct_combo.currentData()
        if not aid:
            return
        if QMessageBox.question(self, "删除账户", f"永久删除账户[{aid}]? 此操作不可恢复!") == QMessageBox.Yes:
            from trade_engine.engine import TradeEngine
            TradeEngine().delete_account(aid)
            self._services.status("账户已删除")
            self.load()

    # ── 最近策略 ─────────────────────────────────────────────
    def _load_strategy(self):
        try:
            p = os.path.join(_ROOT, "data", "paper_runs.json")
            with open(p, encoding="utf-8") as f:
                d = json.load(f)
            runs = d.get("runs") or {}
            asof = d.get("as_of", "")
        except Exception:
            self._strat_name.setText("暂无纸面盘数据")
            self._asof_lbl.setText("")
            return
        # 找最强(总收益最高, 不算error)
        best, best_m = None, None
        for n, r in runs.items():
            if not isinstance(r, dict) or r.get("error"):
                continue
            m = r.get("metrics") or {}
            if best_m is None or (m.get("total_return") or 0) > (best_m.get("total_return") or 0):
                best, best_m = n, m
        if best is None:
            self._strat_name.setText("暂无策略结果")
            self._asof_lbl.setText(f"数据截至 {asof}" if asof else "")
            return
        self._asof_lbl.setText(f"数据截至 {asof}" if asof else "")
        self._strat_name.setText(best)
        alpha = best_m.get("alpha")
        alpha_s = f"α {alpha*100:+.1f}%" if alpha is not None else "α —"
        self._strat_desc.setText(
            f"总收益 {best_m.get('total_return',0)*100:+.1f}% · 年化 {best_m.get('cagr',0)*100:+.1f}% · {alpha_s}")
        self._strat_metrics.setText(
            f"夏普 {best_m.get('sharpe',0):.2f} · 最大回撤 {best_m.get('max_drawdown',0)*100:.1f}% · "
            f"调仓 {runs[best].get('rebalances',0)} 次 · 持仓 {len(runs[best].get('final_holdings',{}))} 只")

    # ── 市场速览 ─────────────────────────────────────────────
    def _load_market(self):
        # 上证(kline) + 沪深300(hs300.json, 更到最新)
        self._clear(self._mkt_row)
        self._mkt_cards = {}
        cards = [("index", "sh000001", "上证指数"), ("hs300", None, "沪深300")]
        for src, code, name in cards:
            card = self._mkt_card(src, code, name)
            self._mkt_row.addWidget(card)
        if not self._mkt_cards:
            empty = QLabel("市场数据未更新")
            empty.setStyleSheet(value_ss(size=10) + f"color:{C_FAINT};")
            self._mkt_row.addWidget(empty)

    def _mkt_card(self, src, code, name):
        card = well("card"); card.setMinimumHeight(dp(80))
        lo = QVBoxLayout(card); lo.setContentsMargins(dp(12), dp(8), dp(12), dp(8)); lo.setSpacing(dp(2))
        nm = QLabel(name); nm.setStyleSheet(label_ss(size=9) + f"color:{C_FAINT};")
        lo.addWidget(nm)
        val, chg, dstr = "—", "—", ""
        try:
            if src == "index" and self._db_path:
                con = sqlite3.connect(self._db_path)
                row = con.execute(
                    "SELECT date, close FROM kline_daily WHERE code=? ORDER BY date DESC LIMIT 2", (code,)).fetchall()
                con.close()
                if row:
                    latest = float(row[0][1]); prev = float(row[1][1]) if len(row) > 1 else latest
                    val, chg = f"{latest:,.0f}", (f"{(latest/prev-1)*100:+.2f}%" if prev else "—")
                    d = str(row[0][0]); dstr = f"{d[:4]}-{d[4:6]}-{d[6:8]}" if len(d) == 8 else d
            elif src == "hs300":
                p = os.path.join(_ROOT, "data", "hs300.json")
                if os.path.exists(p):
                    with open(p, encoding="utf-8") as f:
                        h = json.load(f)
                    ds, cs = h.get("dates", []), h.get("closes", [])
                    if len(ds) >= 2 and len(cs) >= 2:
                        latest, prev = float(cs[-1]), float(cs[-2])
                        val, chg = f"{latest:,.0f}", (f"{(latest/prev-1)*100:+.2f}%" if prev else "—")
                        dstr = str(ds[-1])
        except Exception:
            pass
        self._mkt_cards[name] = val
        v = QLabel(val); v.setStyleSheet(value_ss(size=14) + f"color:{PAL['accent']};")
        lo.addWidget(v)
        label = chg + (f"  数据至 {dstr}" if dstr else "")
        c = QLabel(label)
        col = C_RISE if (chg.startswith("+") and chg != "—") else (C_FALL if chg.startswith("-") else C_FAINT)
        c.setStyleSheet(label_ss(size=8) + f"color:{col};")
        lo.addWidget(c)
        return card

    def _clear(self, layout):
        while layout.count():
            item = layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
