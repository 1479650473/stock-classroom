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
PROGRESS = {}    # stage -> {status, msg, pct, started}  实时进度
def _busy(stage): RUNNING.setdefault(stage, False)

def _set_progress(stage, status, msg='', pct=None):
    p = PROGRESS.setdefault(stage, {})
    p['status'] = status; p['msg'] = msg; p['pct'] = pct
    p['started'] = p.get('started') or time.time()

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

# 各阶段介入函数 (真实后端 + 实时进度回调 progress(msg,pct))
def _progress_cb(stage):
    def cb(msg, pct):
        _set_progress(stage, 'running', msg, pct)
    return cb

def _run_one(stage):
    """执行单个阶段, 回填 LAST + PROGRESS."""
    _busy(stage); t0 = time.time()
    _set_progress(stage, 'running', '启动...', 0.0)
    cb = _progress_cb(stage)
    try:
        if stage == 'data':
            from data_manager import daily_update
            _set_progress(stage, 'running', '日更 K线/基本面...', 0.1)
            # 全市场日更(慢, ~20min); 优先用量化池定向刷新(快, ~100s, 驱动 as_of)
            try:
                from data_manager import update_pool
                rp = update_pool(workers=15, progress=lambda m, p=None: _set_progress(stage, 'running', m, None))
                detail = f'量化池刷新 {rp.get("updated")} 只 +{rp.get("rows_added")} 行'
            except Exception as e:
                n = daily_update(catch_up_days=10)
                detail = f'daily_update 返回 {n} ({str(e)[:40]})'
        elif stage == 'research':
            from frontend.plugins.research.worker import study_factors
            r = study_factors('2022-01-01', progress=cb)
            detail = f"BP ICIR {((r.get('BP') or {}).get('icir'))}"
        elif stage == 'backtest':
            from frontend.plugins.research.worker import run_backtest
            r = run_backtest('BP', 20, '2022-01-01', progress=cb)
            detail = f"BP HP20 IC {r.get('ic')} ICIR {r.get('icir')}"
        elif stage == 'paper':
            from frontend.plugins.research.worker import run_paper_multi
            r = run_paper_multi(hp=20, fwd_start='2024-01-01', progress=cb)
            sp = (r.get('selected') if isinstance(r, dict) else None) or 'F价值Tilt'
            pr = ((r.get('runs') or {}).get(sp) if isinstance(r, dict) else None) or {}
            naw = pr.get('nav') or []
            detail = f"final_nav {(naw[-1] if naw else None)}"
        elif stage == 'compare':
            from backend.agent.decision_gate import market_breadth
            _set_progress(stage, 'running', '计算市场宽度...', 0.5)
            b = market_breadth()
            detail = f'市场宽度={b}'
        else:
            detail = f'未识别阶段 {stage}'
        LAST[stage] = {'status': 'ok', 'detail': detail, 'sec': round(time.time()-t0,1)}
        _set_progress(stage, 'ok', detail, 100.0)
    except Exception as e:
        import traceback
        LAST[stage] = {'status': 'error', 'detail': repr(e)[:140], 'sec': round(time.time()-t0,1)}
        _set_progress(stage, 'error', repr(e)[:80], None)
    finally:
        RUNNING[stage] = False

def _run_stage(stage):
    threading.Thread(target=_run_one, args=(stage,), daemon=True).start()
    return {'started': True, 'stage': stage}

def _run_all():
    """顺序跑完整条链 data→research→backtest→paper→compare, 报告整链进度."""
    chain = ['data', 'research', 'backtest', 'paper', 'compare']
    def wrap():
        _set_progress('_chain', 'running', '整链运行中...', 0.0)
        for i, st in enumerate(chain):
            _set_progress('_chain', 'running', f'第 {i+1}/{len(chain)} 步 · {st}', round(i/len(chain)*100, 0))
            _run_one(st)
        _set_progress('_chain', 'ok', '整链完成', 100.0)
        _run_one('compare')
    threading.Thread(target=wrap, daemon=True).start()
    return {'started': True, 'chain': chain}

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
        p = PROGRESS.get(sid)
        if RUNNING.get(sid) or (p and p.get('status') == 'running'):
            status = 'running'
        else:
            status = (l['status'] if l else ('ok' if chain else 'idle'))
        prog = None
        if status == 'running' and p:
            prog = {'msg': p.get('msg'), 'pct': p.get('pct'),
                    'elapsed': round(time.time() - p.get('started', time.time()), 1)}
        stages.append({'id': sid, 'title': title, 'desc': desc, 'status': status,
                       'last': l, 'progress': prog, **extra})
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
    cp = PROGRESS.get('_chain')
    chain_prog = None
    if cp and cp.get('status') == 'running':
        chain_prog = {'msg': cp.get('msg'), 'pct': cp.get('pct'),
                      'elapsed': round(time.time() - cp.get('started', time.time()), 1)}
    return {'meta': {'sec': chain.get('_sec'), 'updated': st['update_time'], 'chain_progress': chain_prog},
            'data': st, 'stages': stages}

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
        if self.path == '/run-all':
            self._json(_run_all())
        elif self.path.startswith('/run/'):
            stage = self.path.split('/')[-1]
            self._json(_run_stage(stage))
        else:
            self._json({'error': 'bad'}, 404)

if __name__ == '__main__':
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8234
    srv = ThreadingHTTPServer(('127.0.0.1', port), H)
    print(f'flow server on http://127.0.0.1:{port}', flush=True)
    srv.serve_forever()
