# -*- coding: utf-8 -*-
"""Flow Panel (原生 Qt 版) — 全流程指挥舱: 数据管道→因子研究→回测→重平衡→纸面盘→对比.
复用 flow_server 的进度引擎(_run_stage/_run_all/PROGRESS/LAST), QTimer 轮询驱动每张卡进度条+消息+秒表.
与 web 指挥舱同源进度, 零重复逻辑."""
import os, sqlite3, json
from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame,
                             QPushButton, QProgressBar, QScrollArea)
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QColor
from frontend.platform.theme import dp, fs, dps
from frontend.platform.premium import PAL, card_qss, label_ss, value_ss
from frontend.flow import flow_server as fe   # 复用进度引擎

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
STAGES = [
    ('data',     '数据管道', 'K线 / 基本面 / 股票列表日更'),
    ('research', '因子研究', '价值 / 动量 / 波动 IC'),
    ('backtest', '策略回测', 'BP 单因子截面 HP20'),
    ('paper',    '纸面盘',   '保持分层 + 慢调仓'),
    ('compare',  '收益对比', '纸面盘 vs 买持'),
]
STATUS_COLOR = {'idle': QColor('#5c6670'), 'running': QColor('#d29922'),
                'ok': QColor('#3fb950'), 'error': QColor('#e5484d')}


def _data():
    try:
        K = sqlite3.connect(os.path.join(ROOT, 'data', 'kline.db')); c = K.cursor()
        kmx = c.execute('SELECT MAX(date) FROM kline_daily').fetchone()[0]
        nact = c.execute("SELECT COUNT(*) FROM stock_list WHERE status='active'").fetchone()[0]
        K.close()
        return {'kline_max': kmx, 'active': nact}
    except Exception:
        return {'kline_max': '—', 'active': 0}


def _chain():
    try:
        return json.load(open(os.path.join(ROOT, '_chain_result.json'), encoding='utf-8'))
    except Exception:
        return {}


def _metric(sid, data, chain):
    if sid == 'data':
        return f"K线 {data['kline_max']} · 活跃 {data['active']} 只"
    if sid == 'research':
        r = (chain.get('research') or {}).get('BP') or {}
        return f"BP IC {r.get('ic')} · ICIR {r.get('icir')}" if r else "BP ICIR 待算"
    if sid == 'backtest':
        b = chain.get('backtest') or {}
        g = (b.get('groups') or [{}])
        return f"IC {b.get('ic')} · ICIR {b.get('icir')}" if b else "IC 待算"
    if sid == 'paper':
        s = (chain.get('paper') or {}).get('_summary') or {}
        return (f"净值 {s.get('final_nav')} · {s.get('rebalances')} 调仓" if s else "净值待算")
    if sid == 'compare':
        s = (chain.get('paper') or {}).get('_summary') or {}
        return f"paper {s.get('final_nav')} vs 买持 {s.get('buyhold_final')}" if s else "对比待算"
    return ""


class FlowPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.on_status = None
        self._cards = {}   # sid -> {dot, bar, msg, metric, btn, last}
        self.setStyleSheet(f"background:{PAL['bg']}")
        self._build()
        self._poll()
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._poll)
        self._timer.start(1000)

    def _build(self):
        lo = QVBoxLayout(self)
        lo.setContentsMargins(dp(14), dp(12), dp(14), dp(12))
        lo.setSpacing(dp(8))
        head = QHBoxLayout(); head.setSpacing(dp(8))
        title = QLabel("全流程指挥舱"); title.setStyleSheet(label_ss(size=11) + f"color:{PAL['text']};")
        head.addWidget(title)
        head.addStretch()
        self._btn_all = QPushButton("整链运行")
        self._btn_all.setObjectName("flowBtnAll")
        self._btn_all.setFixedHeight(dp(26))
        self._btn_all.setCursor(Qt.PointingHandCursor)
        self._btn_all.clicked.connect(self._run_all)
        head.addWidget(self._btn_all)
        lo.addLayout(head)
        cap = QLabel("数据管道 → 因子研究 → 策略回测 → 组合重平衡 → 纸面盘 → 收益对比")
        cap.setStyleSheet(value_ss(size=10) + f"color:{PAL['sub']};")
        lo.addWidget(cap)
        scroll = QScrollArea(); scroll.setWidgetResizable(True)
        inner = QWidget(); self._cards_lo = QVBoxLayout(inner)
        self._cards_lo.setSpacing(dp(8)); self._cards_lo.setContentsMargins(0, 0, 0, 0)
        scroll.setWidget(inner)
        scroll.setStyleSheet("QScrollArea{background:transparent;border:none;}")
        lo.addWidget(scroll, 1)
        # 建卡片
        for sid, title, desc in STAGES:
            self._cards_lo.addWidget(self._make_card(sid, title, desc))

    def _make_card(self, sid, title, desc):
        card = QFrame(); card.setStyleSheet(card_qss("card"))
        lo = QVBoxLayout(card); lo.setContentsMargins(dp(12), dp(8), dp(12), dp(8)); lo.setSpacing(dp(4))
        row = QHBoxLayout(); row.setSpacing(dp(6))
        dot = QLabel("\u25cf"); dot.setStyleSheet(f"color:{PAL['faint']};font-size:{fs(8)};")
        t = QLabel(title); t.setStyleSheet(label_ss(size=10) + f"color:{PAL['text']};")
        row.addWidget(dot); row.addWidget(t); row.addStretch()
        lo.addLayout(row)
        dd = QLabel(desc); dd.setStyleSheet(value_ss(size=9) + f"color:{PAL['faint']};")
        lo.addWidget(dd)
        # 进度条(默认隐藏)
        bar = QProgressBar(); bar.setRange(0, 100); bar.setValue(0)
        bar.setVisible(False)
        bar.setFixedHeight(dp(5))
        bar.setStyleSheet(self._bar_ss())
        lo.addWidget(bar)
        msg = QLabel(""); msg.setVisible(False)
        msg.setStyleSheet(value_ss(size=9) + f"color:{PAL['sub']};")
        lo.addWidget(msg)
        metric = QLabel(self._metric_fresh(sid)); metric.setStyleSheet(value_ss(size=12) + f"color:{PAL['accent']};")
        lo.addWidget(metric)
        btn = QPushButton("介入 / 运行")
        btn.setFixedHeight(dp(26)); btn.setCursor(Qt.PointingHandCursor)
        btn.clicked.connect(lambda _, s=sid: self._run_stage(s))
        lo.addWidget(btn)
        last = QLabel(""); last.setStyleSheet(value_ss(size=9) + f"color:{PAL['faint']};")
        lo.addWidget(last)
        self._cards[sid] = {'dot': dot, 'bar': bar, 'msg': msg, 'metric': metric,
                            'btn': btn, 'last': last}
        return card

    def _bar_ss(self):
        return (f"QProgressBar{{background:rgba(122,162,247,.12);border:none;border-radius:2px;}}"
                f"QProgressBar::chunk{{background:{PAL['accent']};border-radius:2px;}}")

    def _metric_fresh(self, sid):
        data = _data(); chain = _chain()
        return _metric(sid, data, chain)

    # ── 轮询引擎进度 → 更新卡片 ──
    def _poll(self):
        data = _data(); chain = _chain()
        for sid, c in self._cards.items():
            p = fe.PROGRESS.get(sid)
            l = fe.LAST.get(sid)
            running = fe.RUNNING.get(sid) or (p and p.get('status') == 'running')
            # 状态灯
            if running:
                color = STATUS_COLOR['running']
            elif l:
                color = STATUS_COLOR.get(l['status'], STATUS_COLOR['idle'])
            else:
                color = STATUS_COLOR['idle']
            c['dot'].setStyleSheet(f"color:{color.name()};font-size:{fs(8)};")
            # 进度条 + 消息
            if running and p:
                c['bar'].setVisible(True)
                c['bar'].setValue(int(p.get('pct') or 0))
                c['msg'].setVisible(True)
                c['msg'].setText(f"{p.get('msg') or ''} · {int(p.get('started') and __import__('time').time() - p['started'])}s")
            else:
                c['bar'].setVisible(False); c['msg'].setVisible(False)
            # 按钮状态
            c['btn'].setEnabled(not running)
            c['btn'].setText("运行中…" if running else "介入 / 运行")
            # 结果/指标
            c['metric'].setText(_metric(sid, data, chain))
            if l:
                c['last'].setText(f"{(l.get('sec') or 0)}s · {l.get('detail','')[:40]}")
            else:
                c['last'].setText("")
        # 整链运行按钮
        cp = fe.PROGRESS.get('_chain')
        chain_running = fe.RUNNING.get('_chain') or (cp and cp.get('status') == 'running')
        self._btn_all.setEnabled(not chain_running)
        self._btn_all.setText("整链运行中…" if chain_running else "整链运行")

    def _run_stage(self, sid):
        try:
            fe._run_stage(sid)
        except Exception:
            pass

    def _run_all(self):
        try:
            fe._run_all()
        except Exception:
            pass

    def refresh(self):
        self._poll()

    def on_theme_changed(self):
        self.setStyleSheet(f"background:{PAL['bg']}")
        for c in self._cards.values():
            c['bar'].setStyleSheet(self._bar_ss())
            c['dot'].setStyleSheet(f"color:{STATUS_COLOR['idle'].name()};font-size:{fs(8)};")
        self._poll()
