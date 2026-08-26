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

    def __init__(self, rounds=3, use_llm=True, account_id=None, universe_code=None, mode='stock'):
        super().__init__()
        self._rounds = int(rounds)
        self._use_llm = bool(use_llm)
        self._account_id = account_id
        self._universe_code = universe_code
        self._mode = mode                        # 'stock'=单标的闭环; 'portfolio'=组合重平衡
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

            if self._mode == 'portfolio':
                # 组合级: 读当前持仓 → 多因子目标组合 → 批量调仓
                self.line.emit(f"模式 → 组合重平衡 · 多因子(价值+反转-波动)+价值tilt")
                self.line.emit(f"后端 → {'LLM' if self._use_llm else 'stub'} (组合级为规则因子, 与LLM无关)")
                from backend.strategy.portfolio_rebalance import SelectionContract
                contract = SelectionContract(top_k_pct=0.2, rebalance_bars=20, initial_balance=100000.0)
                res = loop.portfolio_paper(gw=loop.gw, contract=contract, account_id=ai,
                                           max_pool=200, progress=lambda m: self._safe_line(m))
                if self._stopped:
                    return
                orders = res.get("orders", [])
                filled = sum(1 for o in orders if o.get("order") and o["order"].get("status") == "filled")
                self.done.emit({
                    "mode": "portfolio",
                    "as_of": res.get("as_of"),
                    "n_trades": res.get("n_trades"),
                    "filled": filled,
                    "w_value": res.get("w_value"),
                    "tilt_label": (res.get("tilt") or {}).get("tilt_label"),
                    "paper": {"signal": "portfolio", "note": f"{res.get('n_trades')} 笔调仓成交 {filled}"},
                    "account_summary": eng.get_summary(ai),
                    "positions": self._positions(eng, ai),
                    "backend": "portfolio",
                })
                return

            # 单标的闭环(默认)
            self.line.emit(f"模式 → 单标的闭环 · {self._rounds} 轮研究")
            self.line.emit(f"后端 → {'LLM(模型真正决策)' if self._use_llm else 'stub(确定性验证)'}")

            def _progress(msg):
                if not self._stopped:
                    self.line.emit(msg)
            res = loop.run(rounds=self._rounds, paper=True, paper_account_id=ai,
                           universe_code=self._universe_code, use_factor_research=True,
                           progress=_progress)
            if self._stopped:
                return
            paper = res.paper or {}
            best = res.best
            self.done.emit({
                "mode": "stock",
                "universe": res.universe.get('code') if res.universe else None,
                "best_round": best.round_id if best else None,
                "best_score": best.score if best else None,
                "best_return": (best.metrics.get('total_return', 0) * 100 if best else 0),
                "best_mdd": (best.metrics.get('max_drawdown', 0) * 100 if best else 0),
                "best_sharpe": (best.metrics.get('sharpe', 0) if best else 0),
                "best_contract": best.contract if best else None,
                "paper": paper,
                "account_summary": eng.get_summary(ai),
                "positions": self._positions(eng, ai),
                "backend": loop.backend.name,
            })
        except Exception as e:
            self.error.emit(str(e))

    def _safe_line(self, msg):
        if not self._stopped:
            self.line.emit(msg)

    def _positions(self, eng, ai):
        return [{
            "code": p['code'], "name": p['name'], "qty": p['qty'],
            "cost": round(p['cost_price'], 2), "price": round(p['current_price'], 2),
            "mv": round(p['market_value'], 2), "pnl": round(p['float_pnl'], 2),
        } for p in eng.get_positions(ai)]
