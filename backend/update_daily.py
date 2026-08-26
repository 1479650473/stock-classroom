# -*- coding: utf-8 -*-
"""update_daily.py — 每日数据自动更新(独立脚本, 供 Windows 任务计划调用).

刷新三层并保证 as_of 一致:
  ① 量化池 K线 (update_pool, ~100s)          —— as_of 前进的关键
  ② 基本面 EP/BP/ROE (fetch_fundamental)     —— 价值因子对齐(点时间)
  ③ 组合纸面盘 paper_runs.json               —— 曲线/持仓台账刷新

用法:  python update_daily.py [--pool-only] [--skip-paper]
结果写入 data/update_marker.json + logs/update_daily_YYYYMMDD.log
"""
import os, sys, json, time, logging
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, 'backend'))

DATA = os.path.join(ROOT, 'data')
LOGDIR = os.path.join(ROOT, 'logs')
os.makedirs(LOGDIR, exist_ok=True)

MARKER = os.path.join(DATA, 'update_marker.json')


def _log():
    lg = logging.getLogger('update_daily')
    if lg.handlers:
        return lg
    lg.setLevel(logging.INFO)
    h = logging.StreamHandler()
    h.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(message)s', '%H:%M:%S'))
    lg.addHandler(h)
    fh = logging.FileHandler(os.path.join(LOGDIR, 'update_daily_%s.log' % datetime.now().strftime('%Y%m%d')),
                             encoding='utf-8')
    fh.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(message)s'))
    lg.addHandler(fh)
    return lg


def refresh_fundamentals(codes, workers=16, progress=None):
    """并行刷新基本面(东财估值, 每code ~2s 全历史). 只刷已缓存/有盘的, 防误杀新股. 返回 {updated, skipped}."""
    from concurrent.futures import ThreadPoolExecutor, as_completed
    import fundamental as fund
    updated = skipped = 0
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futs = {pool.submit(fund.fetch_fundamental, c): c for c in codes}
        done = 0
        for f in as_completed(futs):
            done += 1
            c = futs[f]
            try:
                rows = f.result()
                if rows:
                    updated += 1
                else:
                    skipped += 1
            except Exception:
                skipped += 1
            if progress and (done % 40 == 0 or done == len(codes)):
                progress(done, len(codes), updated, skipped)
    return {'updated': updated, 'skipped': skipped}


def run(pool_only=False, skip_paper=False):
    lg = _log()
    t0 = time.time()
    lg.info('══ update_daily 开始 %s ══', datetime.now().isoformat(timespec='seconds'))
    out = {'started': datetime.now().isoformat(timespec='seconds'), 'steps': {}}

    from backend.strategy.factor_selector import build_wide_pool
    pool = build_wide_pool() or []
    lg.info('量化池 %d 只', len(pool))

    # ① K线池
    from data_manager import update_pool
    def _plog(msg, code=None):
        lg.info(msg)
    rk = update_pool(pool=pool, workers=16, progress=_plog)
    out['steps']['kline'] = {k: rk[k] for k in ('updated', 'skipped', 'errors', 'rows_added', 'total', 'elapsed') if k in rk}
    lg.info('  K线池: %s', out['steps']['kline'])

    if not pool_only:
        # ② 基本面
        def _fprog(done, tot, up, sk):
            lg.info('  基本面 [%d/%d] 刷新%d 跳过%d', done, tot, up, sk)
        rp = refresh_fundamentals([str(c) for c in pool if c[:2] in ('00', '30', '60', '68')], progress=_fprog)
        out['steps']['fundamental'] = rp
        lg.info('  基本面: %s', rp)

        # ③ 纸面盘
        if not skip_paper:
            from frontend.plugins.research.worker import run_paper_multi
            lg.info('  纸面盘重算中(约5-8min)...')
            rr = run_paper_multi(hp=20, progress=lambda m, p=None: lg.info('   ' + str(m)))
            if isinstance(rr, dict) and not rr.get('error'):
                out['steps']['paper'] = {'as_of': rr.get('as_of'), 'selected': rr.get('selected')}
                lg.info('  纸面盘: as_of=%s selected=%s', rr.get('as_of'), rr.get('selected'))
            else:
                err = (rr or {}).get('error') if isinstance(rr, dict) else 'unknown'
                out['steps']['paper'] = {'error': str(err)[:120]}
                lg.warning('  纸面盘失败: %s', str(err)[:120])

    out['finished'] = datetime.now().isoformat(timespec='seconds')
    out['elapsed'] = round(time.time() - t0, 1)
    out['ok'] = True
    with open(MARKER, 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    lg.info('══ update_daily 完成 %.1fs → %s ══', out['elapsed'], MARKER)
    return out


if __name__ == '__main__':
    po = '--pool-only' in sys.argv
    sp = '--skip-paper' in sys.argv
    run(pool_only=po, skip_paper=sp)
