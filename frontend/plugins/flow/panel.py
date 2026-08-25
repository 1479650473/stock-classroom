# -*- coding: utf-8 -*-
"""Flow Panel — 全流程指挥舱(app内插件): 数据管道→因子研究→回测→重平衡→纸面盘→对比.
读真实状态(DB + _chain_result.json), 每阶段一个卡片 + 介入按钮(后台线程调后端真函数)."""
import os, sqlite3, json, threading, time
from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame,
                             QPushButton, QScrollArea)
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QColor
from frontend.platform.theme import dp, fs, dps, qss_table
from frontend.platform.premium import PAL, card_qss, label_ss, value_ss, well
import frontend.platform.premium as _pm

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

STAGES = [
    ('data',     '数据管道', 'K线 / 基本面 / 股票列表日更'),
    ('research', '因子研究', '价值 / 动量 / 波动 IC'),
    ('backtest', '策略回测', '组合级多因子分层'),
    ('paper',    '纸面盘',   '保持分层 + 慢调仓'),
    ('compare',  '收益对比', '纸面盘 vs 买持'),
]

def _read_dbs():
    """读真实数据新鲜度 + 纸面盘账户."""
    out = {'kline_max': None, 'active': 0, 'log': None, 'paper': None}
    try:
        K = sqlite3.connect(os.path.join(ROOT, 'data', 'kline.db'))
        c = K.cursor()
        out['kline_max'] = c.execute('SELECT MAX(date) FROM kline_daily').fetchone()[0]
        out['active'] = c.execute("SELECT COUNT(*) FROM stock_list WHERE status='active'").fetchone()[0]
        out['log'] = c.execute('SELECT update_date FROM data_update_log ORDER BY id DESC LIMIT 1').fetchone()[0]
        K.close()
    except Exception:
        pass
    try:
        T = sqlite3.connect(os.path.join(ROOT, 'data', 'sim_trade.db'))
        t = T.cursor()
        a = t.execute('SELECT name,balance FROM accounts ORDER BY id DESC LIMIT 1').fetchone()
        out['paper'] = {'name': a[0], 'balance': round(a[1], 2)} if a else None
        print_hdr = ('trades', t.execute('SELECT COUNT(*) FROM trades').fetchone()[0])
        T.close()
        out['trades'] = print_hdr[1]
    except Exception:
        pass
    return out

def _chain():
    try:
        return json.load(open(os.path.join(ROOT, '_chain_result.json'), encoding='utf-8'))
    except Exception:
        return {}

class FlowPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.on_status = None
        self.setStyleSheet(f"background:{PAL['bg']}")
        self._built = False
        self._build()
        self.refresh()

    # ── 主题 ──
    def on_theme_changed(self):
        self.setStyleSheet(f"background:{PAL['bg']}")
        self._build()
        self.refresh()

    # ── 界面 ──
    def _build(self):
        if self._built:
            while self.layout().count():
                it = self.layout().takeAt(0)
                w = it.widget()
                if w: w.deleteLater()
        else:
            lo = QVBoxLayout(self)
            lo.setContentsMargins(dp(14), dp(12), dp(14), dp(12))
            lo.setSpacing(dp(8))
            title = QLabel("全流程指挥舱")
            title.setStyleSheet(label_ss(size=11) + f"color:{PAL['text']};")
            lo.addWidget(title)
            cap = QLabel("数据管道 → 因子研究 → 策略回测 → 组合重平衡 → 纸面盘 → 收益对比")
            cap.setStyleSheet(value_ss(size=10) + f"color:{PAL['sub']};")
            lo.addWidget(cap)
            self._cards = QVBoxLayout()
            self._cards.setSpacing(dp(8))
            scroll = QScrollArea(); scroll.setWidgetResizable(True)
            inner = QWidget(); inner.setLayout(self._cards)
            scroll.setWidget(inner)
            scroll.setStyleSheet(f"QScrollArea{{background:transparent;border:none;}}")
            lo.addWidget(scroll, 1)
            self._built = True
        if not hasattr(self, '_cards') or self._cards.count() == 0:
            return

    def refresh(self):
        d = _read_dbs()
        chain = _chain()
        # 清空重建卡片
        while self._cards.count():
            it = self._cards.takeAt(0)
            w = it.widget()
            if w: w.deleteLater()
        for sid, title, desc in STAGES:
            self._cards.addWidget(self._stage_card(sid, title, desc, d, chain))

    def _stage_card(self, sid, title, desc, d, chain):
        card = QFrame()
        card.setStyleSheet(card_qss("card"))
        lo = QVBoxLayout(card)
        lo.setContentsMargins(dp(12), dp(8), dp(12), dp(8))
        lo.setSpacing(dp(4))
        # 标题行
        row = QHBoxLayout(); row.setSpacing(dp(6))
        dot = QLabel("●"); dot.setStyleSheet(f"color:{PAL['accent']};font-size:{fs(8)};")
        t = QLabel(title); t.setStyleSheet(label_ss(size=10) + f"color:{PAL['text']};")
        row.addWidget(dot); row.addWidget(t); row.addStretch()
        lo.addLayout(row)
        dd = QLabel(desc); dd.setStyleSheet(value_ss(size=9) + f"color:{PAL['faint']};")
        lo.addWidget(dd)
        m = QLabel(self._metric(sid, d, chain))
        m.setStyleSheet(value_ss(size=12) + f"color:{PAL['accent']};")
        lo.addWidget(m)
        btn = QPushButton("介入 / 运行")
        btn.setObjectName("flowBtn")
        btn.setFixedHeight(dp(26))
        btn.setCursor(Qt.PointingHandCursor)
        btn.clicked.connect(lambda _, s=sid, b=btn: self._run(s, b))
        lo.addWidget(btn)
        return card

    def _metric(self, sid, d, chain):
        if sid == 'data':
            return f"K线 {d['kline_max']} · 活跃 {d['active']} 只"
        if sid == 'research':
            r = chain.get('research') or {}
            icir = r.get('BP', {}).get('icir') if isinstance(r, dict) else None
            return f"BP ICIR {icir if icir is not None else '待算'}"
        if sid == 'backtest':
            r = chain.get('backtest') or {}
            icir = r.get('icir') if isinstance(r, dict) else None
            return f"BP(HP20) ICIR {icir if icir is not None else '待算'}"
        if sid == 'paper':
            p = d.get('paper')
            return f"净值 {p['balance'] if p else '—'} · {d.get('trades', 0)} 笔"
        if sid == 'compare':
            p = (chain.get('paper') or {}).get('_summary')
            if p and isinstance(p, dict):
                return f"paper 末 {p.get('final_nav')} vs 买持 {p.get('buyhold_final')} · {p.get('rebalances')} 调仓"
            return "paper vs 买持 (待算)"
        return ""

    def _run(self, sid, btn):
        btn.setEnabled(False); btn.setText("运行中…")
        def work():
            t0 = time.time()
            try:
                if sid == 'data':
                    from backend.data_manager import daily_update
                    daily_update(catch_up_days=10)
                elif sid == 'research':
                    from frontend.plugins.research.worker import study_factors
                    study_factors('2022-01-01')
                elif sid == 'backtest':
                    from frontend.plugins.research.worker import run_backtest
                    run_backtest('BP', 20, '2022-01-01')
                elif sid == 'paper':
                    from frontend.plugins.research.worker import build_paper_only
                    build_paper_only(hp=20, fwd_start='2024-01-01')
                elif sid == 'compare':
                    from backend.agent.decision_gate import market_breadth
                    market_breadth()
            except Exception:
                pass
            finally:
                try:
                    btn.setEnabled(True); btn.setText("介入 / 运行")
                except Exception:
                    pass
                self.refresh()
        threading.Thread(target=work, daemon=True).start()
