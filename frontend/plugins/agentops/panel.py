# -*- coding: utf-8 -*-
"""AgentOpsPanel — AI 操盘台: 模型 agent 自主研究→决策→下单, 用户旁观其推理/动作流."""

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame, QTextEdit,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView, QComboBox, QSpinBox,
    QTimeEdit, QCheckBox,
)
from PyQt5.QtCore import Qt, QTimer, QTime
from PyQt5.QtGui import QFont, QColor
from frontend.platform.theme import dp, dps, fs
from frontend.platform.premium import PAL, card_qss, label_ss, value_ss, hero_ss, well
from .worker import AgentOpsWorker


def _fmt(v, s=2):
    try:
        return f"{float(v):,.{s}f}"
    except Exception:
        return str(v)


class AgentOpsPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.on_status = None
        self._worker = None
        self._accounts = []
        self._last_fire = None            # 上次自动触发日期(YYYY-MM-DD, 每日一跑)
        self.setStyleSheet(f"background:{PAL['bg']}")
        self._build()
        self._refresh_accounts()
        # 定时器: 每15s检查一次是否到点(自动操盘)
        self._auto_timer = QTimer(self)
        self._auto_timer.timeout.connect(self._check_auto)
        self._auto_timer.start(15000)
        self._load_sched()

    def _build(self):
        lo = QVBoxLayout(self)
        lo.setContentsMargins(dp(14), dp(12), dp(14), dp(12))
        lo.setSpacing(dp(8))

        title = QLabel("AI 操盘台")
        title.setStyleSheet(f"color:{PAL['text']};font-size:{fs(17)};font-weight:700;background:transparent;")
        lo.addWidget(title)
        cap = QLabel("模型 agent 自主：研究 → 生成策略 → 回测 → 复盘 → 择优 → 模拟下单。你只需旁观决策过程。")
        cap.setStyleSheet(value_ss(size=10) + f"color:{PAL['sub']};")
        cap.setWordWrap(True)
        lo.addWidget(cap)

        # 控制条
        ctl = QHBoxLayout(); ctl.setSpacing(dp(8))
        ctl.addWidget(QLabel("账户"))
        self._acct = QComboBox(); self._acct.setFixedHeight(dp(28)); self._acct.setMinimumWidth(dp(120))
        self._acct.setStyleSheet(self._combo_ss())
        ctl.addWidget(self._acct)
        ctl.addWidget(QLabel("轮数"))
        self._rounds = QSpinBox(); self._rounds.setRange(1, 5); self._rounds.setValue(3)
        self._rounds.setFixedHeight(dp(28)); self._rounds.setFixedWidth(dp(56))
        self._rounds.setStyleSheet(self._spin_ss())
        ctl.addWidget(self._rounds)
        self._use_llm = QComboBox(); self._use_llm.setFixedHeight(dp(28)); self._use_llm.setMinimumWidth(dp(110))
        self._use_llm.addItems(["LLM 真实决策", "stub 确定性验证"])
        self._use_llm.setStyleSheet(self._combo_ss())
        ctl.addWidget(self._use_llm)
        ctl.addWidget(QLabel("模式"))
        self._mode = QComboBox(); self._mode.setFixedHeight(dp(28)); self._mode.setMinimumWidth(dp(120))
        self._mode.addItem("单标的闭环", "stock")
        self._mode.addItem("组合重平衡", "portfolio")
        self._mode.setStyleSheet(self._combo_ss())
        ctl.addWidget(self._mode)
        ctl.addStretch()
        self._btn_run = QPushButton("▶ 启动 AI 操盘")
        self._btn_run.setObjectName("flowBtnAll")
        self._btn_run.setFixedHeight(dp(28)); self._btn_run.setCursor(Qt.PointingHandCursor)
        self._btn_run.clicked.connect(self._run)
        ctl.addWidget(self._btn_run)
        self._btn_stop = QPushButton("■ 停止")
        self._btn_stop.setFixedHeight(dp(28)); self._btn_stop.setCursor(Qt.PointingHandCursor)
        self._btn_stop.setEnabled(False)
        self._btn_stop.setStyleSheet(
            f"QPushButton{{background:{PAL['c_mid']};color:{PAL['down']};border:1px solid {PAL['border_lo']};"
            f"border-radius:{dps(6)};font-size:{fs(12)};}}"
            f"QPushButton:hover{{border-top-color:{PAL['gold']};}}")
        self._btn_stop.clicked.connect(self._stop)
        ctl.addWidget(self._btn_stop)
        lo.addLayout(ctl)

        # 定时自动操盘(每日收盘后)
        sched = QHBoxLayout(); sched.setSpacing(dp(8))
        sched.addWidget(QLabel("定时"))
        self._auto_cb = QCheckBox("每日自动操盘")
        self._auto_cb.setStyleSheet(f"color:{PAL['text']};font-size:{fs(12)};background:transparent;")
        self._auto_cb.toggled.connect(self._on_sched_toggle)
        sched.addWidget(self._auto_cb)
        sched.addWidget(QLabel("时间"))
        self._auto_time = QTimeEdit(); self._auto_time.setDisplayFormat("HH:mm")
        self._auto_time.setFixedHeight(dp(28)); self._auto_time.setFixedWidth(dp(64))
        self._auto_time.setStyleSheet(self._spin_ss())
        self._auto_time.setTime(QTime(15, 0))
        self._auto_time.timeChanged.connect(self._persist_sched)
        sched.addWidget(self._auto_time)
        self._refresh_cb = QCheckBox("先刷新数据")
        self._refresh_cb.setStyleSheet(f"color:{PAL['text']};font-size:{fs(12)};background:transparent;")
        self._refresh_cb.setToolTip("开跑前先把量化池 K线 更新到最新(数据截至日前进)")
        self._refresh_cb.toggled.connect(self._on_sched_toggle)
        sched.addWidget(self._refresh_cb)
        self._sched_status = QLabel("")
        self._sched_status.setStyleSheet(value_ss(size=9) + f"color:{PAL['faint']};")
        sched.addWidget(self._sched_status)
        sched.addStretch()
        lo.addLayout(sched)

        # 账户摘要
        self._sum_row = QHBoxLayout(); self._sum_row.setSpacing(dp(8))
        self._sum_labels = {}
        for k, name in [("asset", "总资产"), ("cash", "可用资金"), ("mv", "持仓市值"), ("pnl", "浮动盈亏")]:
            card = QFrame(); card.setStyleSheet(card_qss("card"))
            c = QVBoxLayout(card); c.setContentsMargins(dp(10), dp(8), dp(10), dp(8)); c.setSpacing(2)
            lb = QLabel(name); lb.setStyleSheet(label_ss(size=9, gold=True))
            v = QLabel("—"); v.setStyleSheet(hero_ss(size=15))
            c.addWidget(lb); c.addWidget(v)
            self._sum_row.addWidget(card, 1)
            self._sum_labels[k] = v
        lo.addLayout(self._sum_row)

        # 状态胶囊
        self._state = QLabel("待命")
        self._state.setStyleSheet(f"color:{PAL['sub']};font-size:{fs(12)};background:transparent;")
        lo.addWidget(self._state)

        # 实时推理流
        logf = QFrame(); logf.setStyleSheet(card_qss("card"))
        lf = QVBoxLayout(logf); lf.setContentsMargins(dp(8), dp(6), dp(8), dp(6))
        lh = QLabel("Agent 推理 / 动作流"); lh.setStyleSheet(label_ss(size=9) + f"color:{PAL['sub']};")
        lf.addWidget(lh)
        self._log = QTextEdit(); self._log.setReadOnly(True)
        self._log.setStyleSheet(
            f"QTextEdit{{background:{PAL['bg']};color:{PAL['text']};border:1px solid {PAL['border_lo']};"
            f"border-radius:{dps(6)};font-size:{fs(12)};font-family:'Microsoft YaHei';}}")
        self._log.setMinimumHeight(dp(240))
        lf.addWidget(self._log)
        lo.addWidget(logf, 2)

        # 结果持仓
        posf = QFrame(); posf.setStyleSheet(card_qss("card"))
        pf = QVBoxLayout(posf); pf.setContentsMargins(dp(8), dp(6), dp(8), dp(6))
        ph = QLabel("托管账户持仓"); ph.setStyleSheet(label_ss(size=9) + f"color:{PAL['sub']};")
        pf.addWidget(ph)
        self._pos_table = QTableWidget()
        self._pos_table.setStyleSheet(self._table_ss())
        self._pos_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._pos_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._pos_table.setHorizontalHeaderLabels(["代码", "名称", "数量", "成本", "现价", "市值", "盈亏"])
        self._pos_table.horizontalHeader().setDefaultAlignment(Qt.AlignRight | Qt.AlignVCenter)
        pf.addWidget(self._pos_table)
        lo.addWidget(posf, 1)

    def _combo_ss(self):
        return (f"QComboBox{{background:{PAL['c_mid']};color:{PAL['text']};border:1px solid {PAL['border_lo']};"
                f"border-top:1px solid {PAL['border_hi']};border-radius:{dps(6)};padding:{dps(2)} {dps(6)};font-size:{fs(12)};}}"
                f"QComboBox QAbstractItemView{{background:{PAL['bg']};color:{PAL['text']};selection-background-color:{PAL['gold']};}}")

    def _spin_ss(self):
        return (f"QSpinBox{{background:{PAL['c_mid']};color:{PAL['text']};border:1px solid {PAL['border_lo']};"
                f"border-radius:{dps(6)};padding:{dps(2)} {dps(4)};font-size:{fs(12)};}}")

    def _table_ss(self):
        return (f"QTableWidget{{background:{PAL['bg']};color:{PAL['text']};border:1px solid {PAL['border_lo']};"
                f"border-radius:{dps(6)};gridline-color:{PAL['border_lo']};}}"
                f"QHeaderView::section{{background:{PAL['c_mid']};color:{PAL['sub']};border:none;"
                f"border-bottom:1px solid {PAL['border_lo']};padding:{dps(4)} {dps(6)};font-weight:600;font-size:{fs(11)};}}")

    def _refresh_accounts(self):
        target = self._acct.currentData() if self._acct.count() else None
        self._acct.blockSignals(True)
        self._acct.clear()
        try:
            from trade_engine.engine import TradeEngine
            self._accounts = TradeEngine().list_accounts()
            ai = None
            for a in self._accounts:
                self._acct.addItem(f"#{a['id']} {a['name']}", a['id'])
                if a['name'] == 'AI账户':
                    ai = a['id']
            # 默认: 选中 AI账户(模型 agent 托管), 否则上一个目标或用首户
            if ai is not None:
                idx = self._acct.findData(ai)
                if idx >= 0:
                    self._acct.setCurrentIndex(idx)
            elif target is not None:
                idx = self._acct.findData(target)
                if idx >= 0:
                    self._acct.setCurrentIndex(idx)
        except Exception:
            pass
        self._acct.blockSignals(False)
        self._load_account(None)

    def _load_account(self, _):
        try:
            i = self._acct.currentIndex()
            aid = self._acct.itemData(i) if i >= 0 else None
            if aid is None:
                return
            from trade_engine.engine import TradeEngine
            s = TradeEngine().get_summary(aid)
            if not s:
                return
            self._sum_labels['asset'].setText(_fmt(s['total_assets']))
            self._sum_labels['cash'].setText(_fmt(s['balance']))
            self._sum_labels['mv'].setText(_fmt(s['market_value']))
            pnl = s['float_pnl']
            self._sum_labels['pnl'].setText(f"{pnl:+,.0f}")
            self._sum_labels['pnl'].setStyleSheet(hero_ss(size=15) +
                f";color:{PAL['up'] if pnl >= 0 else PAL['down']}")
            self._fill_positions(TradeEngine().get_positions(aid))
        except Exception:
            pass

    def _fill_positions(self, positions):
        rows = []
        for p in positions or []:
            rows.append([p['code'], p['name'], str(p['qty']),
                         f"{p['cost_price']:.2f}", f"{p['current_price']:.2f}",
                         _fmt(p['market_value']), f"{p['float_pnl']:+,.0f}"])
        self._pos_table.setRowCount(len(rows))
        self._pos_table.setColumnCount(7)
        self._pos_table.setHorizontalHeaderLabels(["代码", "名称", "数量", "成本", "现价", "市值", "盈亏"])
        for i, row in enumerate(rows):
            for j, v in enumerate(row):
                it = QTableWidgetItem(v)
                it.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
                if j > 2:
                    it.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                if j == 6:
                    pnl = positions[i]['float_pnl']
                    it.setForeground(QColor(PAL['up'] if pnl >= 0 else PAL['down']))
                self._pos_table.setItem(i, j, it)
        self._pos_table.resizeColumnsToContents()

    # ── 运行/停止 ──
    def _run(self):
        if self._worker is not None and self._worker.isRunning():
            return
        aid = self._acct.itemData(self._acct.currentIndex())
        use_llm = (self._use_llm.currentIndex() == 0)
        mode = self._mode.itemData(self._mode.currentIndex()) or "stock"
        self._log.clear()
        self._state.setText("运行中…")
        self._state.setStyleSheet(f"color:{PAL['gold']};font-size:{fs(12)};background:transparent;")
        self._btn_run.setEnabled(False); self._btn_stop.setEnabled(True)
        w = AgentOpsWorker(rounds=self._rounds.value(), use_llm=use_llm, account_id=aid,
                           mode=mode, refresh_pool=self._refresh_cb.isChecked())
        w.line.connect(self._on_line); w.done.connect(self._on_done); w.error.connect(self._on_error)
        self._worker = w
        self._append_log("═══ AI 操盘启动 ═══", gold=True)
        w.start()

    def _stop(self):
        if self._worker is not None:
            self._worker.stop()
            self._append_log("\n[已请求停止]", gold=True)
            self._state.setText("已停止")
        self._btn_run.setEnabled(True); self._btn_stop.setEnabled(False)

    def _on_line(self, msg):
        self._append_log(msg)

    def _append_log(self, msg, gold=False):
        color = "'#D4A574'" if gold else f"'{PAL['sub']}'"
        self._log.append(f'<span style="color:{color}">{msg}</span>')
        sb = self._log.verticalScrollBar(); sb.setValue(sb.maximum())

    def _on_done(self, data):
        backend = data.get("backend", "")
        self._state.setText(f"完成 · {backend}")
        self._state.setStyleSheet(f"color:{PAL['up']};font-size:{fs(12)};background:transparent;")
        self._btn_run.setEnabled(True); self._btn_stop.setEnabled(False)
        # 账户持仓刷新
        aid = self._acct.itemData(self._acct.currentIndex())
        if aid is not None:
            from trade_engine.engine import TradeEngine
            s = TradeEngine().get_summary(aid)
            if s:
                self._sum_labels['asset'].setText(_fmt(s['total_assets']))
                self._sum_labels['cash'].setText(_fmt(s['balance']))
                self._sum_labels['mv'].setText(_fmt(s['market_value']))
                pnl = s['float_pnl']
                self._sum_labels['pnl'].setText(f"{pnl:+,.0f}")
                self._sum_labels['pnl'].setStyleSheet(hero_ss(size=15) +
                    f";color:{PAL['up'] if pnl >= 0 else PAL['down']}")
                self._fill_positions(TradeEngine().get_positions(aid))
        # 汇总(按模式)
        mode = data.get("mode", "stock")
        paper = data.get("paper") or {}
        if mode == "portfolio":
            self._append_log("─── 组合重平衡结果 ───", gold=True)
            self._append_log(f"调仓日 {str(data.get('as_of', ''))[:10]} · "
                             f"三路信号 {data.get('tilt_label') or 'neutral'} · "
                             f"价值层权重 ×{data.get('w_value')}")
            self._append_log(f"调仓 {data.get('n_trades')} 笔 · 成交 {data.get('filled')} 笔", gold=True)
            self._append_log(f"持仓已更新为多因子目标组合(见下方持仓表)")
        else:
            best = data.get("best_round")
            self._append_log("─── 择优结果 ───", gold=True)
            if best is not None:
                self._append_log(f"最优策略: 第{best}轮 · "
                                 f"收益 {data.get('best_return', 0):+.2f}% · "
                                 f"回撤 {data.get('best_mdd', 0):.1f}% · "
                                 f"夏普 {data.get('best_sharpe', 0):.2f}")
            if paper.get("signal") == "long":
                self._append_log(f"模拟买入成交: {paper.get('code')} {paper.get('qty')}股 "
                                 f"@{paper.get('filled_price')} (账户#{paper.get('account_id')})", gold=True)
            else:
                self._append_log(f"本次未下单: {paper.get('note', '')}")

    def _on_error(self, msg):
        self._state.setText("出错")
        self._state.setStyleSheet(f"color:{PAL['down']};font-size:{fs(12)};background:transparent;")
        self._btn_run.setEnabled(True); self._btn_stop.setEnabled(False)
        self._append_log(f"❌ {msg}", gold=False)

    def _refresh(self):
        self._refresh_accounts()

    # ── 定时自动操盘 ──
    def _sched_path(self):
        import os
        return os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))),
                            'backend', 'configs', 'settings.json')

    def _load_sched(self):
        try:
            import json
            with open(self._sched_path(), encoding='utf-8') as f:
                d = json.load(f)
            ag = d.get("agentops", {}) or {}
            if ag.get("auto_enabled"):
                self._auto_cb.setChecked(True)
            if ag.get("refresh_pool"):
                self._refresh_cb.setChecked(True)
            t = ag.get("auto_time", "15:00")
            try:
                hh, mm = t.split(":"); self._auto_time.setTime(QTime(int(hh), int(mm)))
            except Exception:
                pass
        except Exception:
            pass
        self._update_sched_status()

    def _persist_sched(self):
        try:
            import json
            with open(self._sched_path(), encoding='utf-8') as f:
                d = json.load(f)
            d["agentops"] = {
                "auto_enabled": self._auto_cb.isChecked(),
                "auto_time": self._auto_time.time().toString("HH:mm"),
                "refresh_pool": self._refresh_cb.isChecked(),
            }
            with open(self._sched_path(), 'w', encoding='utf-8') as f:
                json.dump(d, f, ensure_ascii=False, indent=2)
        except Exception:
            pass
        self._update_sched_status()

    def _on_sched_toggle(self):
        self._persist_sched()

    def _update_sched_status(self):
        if self._auto_cb.isChecked():
            self._sched_status.setText(f"下次 {self._auto_time.time().toString('HH:mm')}")
            self._sched_status.setStyleSheet(value_ss(size=9) + f"color:{PAL['gold']};")
        else:
            self._sched_status.setText("未启用")
            self._sched_status.setStyleSheet(value_ss(size=9) + f"color:{PAL['faint']};")

    def _check_auto(self):
        """每15s: 若启用且到点且今日未跑 → 自动触发一轮操盘(用户旁观)."""
        if not self._auto_cb.isChecked():
            return
        if self._worker is not None and self._worker.isRunning():
            return
        from datetime import datetime
        now = datetime.now()
        hh = self._auto_time.time().hour(); mm = self._auto_time.time().minute()
        if (now.hour, now.minute) < (hh, mm):
            return
        today = now.strftime("%Y-%m-%d")
        if self._last_fire == today:
            return
        self._last_fire = today
        self._append_log(f"⏰ 定时触发 ({today} {now:%H:%M}) —— 自动操盘开始", gold=True)
        self._run()

    def on_theme_changed(self):
        self.setStyleSheet(f"background:{PAL['bg']}")
        self._acct.setStyleSheet(self._combo_ss())
        self._rounds.setStyleSheet(self._spin_ss())
        self._use_llm.setStyleSheet(self._combo_ss())
        self._pos_table.setStyleSheet(self._table_ss())

    def on_activate(self):
        self._refresh_accounts()
