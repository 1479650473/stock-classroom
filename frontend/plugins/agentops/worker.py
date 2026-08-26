# -*- coding: utf-8 -*-
"""AgentOpsWorker — QThread 跑模型 agent 闭环(LLM生成→回测→复盘→择优→paper下单), 逐步 emit 推理/动作."""
import sys, os, json
from PyQt5.QtCore import QThread, pyqtSignal

BD = os.path.normpath(os.path.join(os.path.dirname(__file__), '..', '..', '..', 'backend'))
if BD not in sys.path:
    sys.path.insert(0, BD)


class AgentOpsWorker(QThread):
    line = pyqtSignal(str)                       # 实时推理/动作流
    done = pyqtSignal(dict)                      # {result_summary, account_summary, positions, paper}
    error = pyqtSignal(str)

    def __init__(self, rounds=3, use_llm=True, account_id=None, universe_code=None):
        super().__init__()
        self._rounds = int(rounds)
        self._use_llm = bool(use_llm)
        self._account_id = account_id
        self._universe_code = universe_code
        self._stopped = False

    def stop(self):
        self._stopped = True

    def run(self):
        try:
            import backend.agent.research_loop as rl
            from trade_engine.engine import TradeEngine

            # 目标账户: 默认 AI账户(模型 agent 托管)
            eng = TradeEngine()
            ai = self._account_id
            aname = "?"
            if ai is None:
                for a in eng.list_accounts():
                    if a['name'] == 'AI账户':
                        ai = a['id']
                if ai is None:
                    ai = eng.create_account('AI账户', 100000)
            acc = eng.get_account(ai)
            aname = acc['name'] if acc else str(ai)
            self.line.emit(f"托管账户 → #{ai} ({aname})")

            loop = rl.build_operate_loop(use_llm=self._use_llm)
            self.line.emit(f"后端 → {'LLM(模型真正决策)' if self._use_llm else 'stub(确定性验证)'} · "
                           f"{self._rounds} 轮研究闭环")

            def _progress(msg):
                if not self._stopped:
                    self.line.emit(msg)
            res = loop.run(rounds=self._rounds, paper=True, paper_account_id=ai,
                           universe_code=self._universe_code, use_factor_research=True,
                           progress=_progress)
            if self._stopped:
                return

            # 汇总结果
            paper = res.paper or {}
            account = eng.get_summary(ai) or {}
            positions = [{
                "code": p['code'], "name": p['name'], "qty": p['qty'],
                "cost": round(p['cost_price'], 2), "price": round(p['current_price'], 2),
                "mv": round(p['market_value'], 2), "pnl": round(p['float_pnl'], 2),
            } for p in eng.get_positions(ai)]
            best = res.best
            self.done.emit({
                "universe": res.universe.get('code') if res.universe else None,
                "best_round": best.round_id if best else None,
                "best_score": best.score if best else None,
                "best_return": (best.metrics.get('total_return', 0) * 100 if best else 0),
                "best_mdd": (best.metrics.get('max_drawdown', 0) * 100 if best else 0),
                "best_sharpe": (best.metrics.get('sharpe', 0) if best else 0),
                "best_contract": best.contract if best else None,
                "paper": paper,
                "account_summary": account,
                "positions": positions,
                "backend": loop.backend.name,
            })
        except Exception as e:
            self.error.emit(str(e))
