# -*- coding: utf-8 -*-
"""flow_server.py — stock-classroom 全流程指挥舱 HTTP API (stdlib, 零额外依赖)
  /              -> flow_cockpit.html  (可视化指挥舱)
  /status        -> GET  各阶段真实状态 JSON
  /run/<stage>   -> POST 触发该阶段真实后端函数 (介入), 后台线程执行
用法: python frontend/flow/flow_server.py  [端口默认 8234]
"""
import os, sys, json, threading, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, 'backend'))
BASE = os.path.dirname(os.path.abspath(__file__))

RUNNING = {}     # stage -> True/False
LAST = {}        # stage -> {time, status, detail}
def _busy(stage): RUNNING.setdefault(stage, False)

def _st(data):
    import os as _os, sqlite3
    from datetime import datetime
    K = sqlite3.connect(_os.path.join(ROOT, 'data', 'kline.db'))
    c = K.cursor()
    kmn, kmx = c.execute('SELECT MIN(date),MAX(date) FROM kline_daily').fetchone()
    nact = c.execute("SELECT COUNT(*) FROM stock_list WHERE status='active'").fetchone()[0]
    upd = c.execute('SELECT update_date,stocks_total,rows_added FROM data_update_log ORDER BY id DESC LIMIT 1').fetchone()
    K.close()
    F = sqlite3.connect(_os.path.join(ROOT, 'data', 'fundamental.db'))
    fmn, fmx, fdc = F.execute('SELECT MIN(date),MAX(date),COUNT(DISTINCT code) FROM fundamental').fetchone()
    F.close()
    T = sqlite3.connect(_os.path.join(ROOT, 'data', 'sim_trade.db'))
    t = T.cursor()
    accts = t.execute('SELECT id,name,balance,total_profit FROM accounts ORDER BY id').fetchall()
    ntrade = t.execute('SELECT COUNT(*) FROM trades').fetchone()[0]
    npos = t.execute('SELECT COUNT(*) FROM positions').fetchone()[0]
    T.close()
    return {
        'update_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'kline': {'min': kmn, 'max': kmx, 'active_stocks': nact, 'last_update': upd},
        'fundamental': {'min': fmn, 'max': fmx, 'stocks': fdc},
        'paper': {'accounts': [{'id': a[0], 'name': a[1], 'balance': round(a[2], 2)} for a in accts],
                  'trades': ntrade, 'positions': npos},
    }

# 各阶段介入函数 (真实后端)
def _run_stage(stage):
    def wrap(st):
        try:
            _busy(st); t0 = time.time()
            if st == 'data':
                from data_manager import daily_update
                n = daily_update(catch_up_days=10)
                LAST[st] = {'status': 'ok', 'detail': f'daily_update 返回 {n}', 'sec': round(time.time()-t0,1)}
            elif st == 'research':
                from backend.strategy.factor_research import FactorResearchEngine
                eng = FactorResearchEngine()
                r = eng.run()
                LAST[st] = {'status': 'ok', 'detail': f'因子研究完成', 'sec': round(time.time()-t0,1)}
            elif st == 'backtest':
                from backend.strategy.portfolio_rebalance import composite_score, _xs_z
                LAST[st] = {'status': 'ok', 'detail': '组合分层回测函数已加载', 'sec': round(time.time()-t0,1)}
            elif st == 'paper':
                from backend.strategy.portfolio_rebalance import forward_paper_run
                r = forward_paper_run()
                LAST[st] = {'status': 'ok', 'detail': f'forward_paper_run 完成', 'sec': round(time.time()-t0,1)}
            elif st == 'compare':
                from backend.agent.decision_gate import market_breadth
                b = market_breadth() if callable(market_breadth) else None
                LAST[st] = {'status': 'ok', 'detail': f'市场宽度={b}', 'sec': round(time.time()-t0,1)}
            else:
                LAST[st] = {'status': 'unknown', 'detail': f'未识别阶段 {st}', 'sec': 0}
        except Exception as e:
            import traceback
            LAST[st] = {'status': 'error', 'detail': f'{repr(e)[:120]}', 'sec': round(time.time()-t0,1)}
        finally:
            RUNNING[st] = False
    threading.Thread(target=wrap, args=(stage,), daemon=True).start()
    return {'started': True, 'stage': stage}

def build_status():
    import copy
    st = _st(None)
    # 真实主干链结果(_chain_result.json)
    chain = {}
    try:
        chain = json.load(open(os.path.join(ROOT, '_chain_result.json'), encoding='utf-8'))
    except Exception:
        chain = {}
    r = chain.get('research') or {}
    b = chain.get('backtest') or {}
    p = (chain.get('paper') or {}).get('paper') or {}
    ps = (chain.get('paper') or {}).get('_summary') or {}
    stages = []
    def mk(sid, title, key, desc, **extra):
        l = LAST.get(sid)
        status = 'running' if RUNNING.get(sid) else (l['status'] if l else ('ok' if chain else 'idle'))
        stages.append({'id': sid, 'title': title, 'desc': desc, 'status': status,
                       'last': l, **extra})
    bp = r.get('BP') or {}
    mk('data', '数据管道', 'data', 'K线/基本面日更', kline_max=st['kline']['max'], active=st['kline']['active_stocks'])
    mk('research', '因子研究', 'research', '价值/动量/波动 IC',
       bp_ic=bp.get('ic'), bp_icir=bp.get('icir'), as_of=r.get('as_of'), pool=r.get('pool_size'))
    g = b.get('groups') or []
    top = g[0].get('net') if g and isinstance(g[0], dict) else None
    mk('backtest', '策略回测', 'backtest', 'BP 单因子截面', ic=b.get('ic'), icir=b.get('icir'), top_net=top)
    mk('paper', '纸面盘', 'paper', '保持分层+慢调仓',
       final_nav=ps.get('final_nav'), rebalances=ps.get('rebalances'), turnover=ps.get('turnover_avg'))
    mk('compare', '收益对比', 'compare', 'paper vs 买持',
       paper=ps.get('final_nav'), buyhold=ps.get('buyhold_final'), as_of=(chain.get('paper') or {}).get('as_of'))
    return {'meta': {'sec': chain.get('_sec'), 'updated': st['update_time']}, 'data': st, 'stages': stages}

class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def _json(self, obj, code=200):
        b = json.dumps(obj, ensure_ascii=False).encode('utf-8')
        self.send_response(code); self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(b))); self.end_headers(); self.wfile.write(b)
    def do_GET(self):
        if self.path == '/status':
            self._json(build_status())
        else:
            p = os.path.join(BASE, 'flow_cockpit.html')
            if os.path.isfile(p):
                b = open(p, 'rb').read()
                self.send_response(200); self.send_header('Content-Type', 'text/html; charset=utf-8')
                self.send_header('Content-Length', str(len(b))); self.end_headers(); self.wfile.write(b)
            else:
                self._json({'error': 'no html'}, 404)
    def do_POST(self):
        if self.path.startswith('/run/'):
            stage = self.path.split('/')[-1]
            self._json(_run_stage(stage))
        else:
            self._json({'error': 'bad'}, 404)

if __name__ == '__main__':
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8234
    srv = ThreadingHTTPServer(('127.0.0.1', port), H)
    print(f'flow server on http://127.0.0.1:{port}', flush=True)
    srv.serve_forever()
