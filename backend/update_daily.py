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
from datetime import datetime, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, 'backend'))

DATA = os.path.join(ROOT, 'data')
LOGDIR = os.path.join(ROOT, 'logs')
os.makedirs(LOGDIR, exist_ok=True)

MARKER = os.path.join(DATA, 'update_marker.json')
CAL_FILE = os.path.join(DATA, 'trade_calendar.json')


def _trade_calendar(reload=False):
    """交易日集合(缓存到 data/trade_calendar.json, 离线可用). 失败返回 None."""
    import pandas as pd
    if os.path.exists(CAL_FILE) and not reload:
        try:
            with open(CAL_FILE, encoding='utf-8') as f:
                return set(json.load(f))
        except Exception:
            pass
    try:
        import akshare as ak
        df = ak.tool_trade_date_hist_sina()
        dates = {str(d)[:10] for d in df['trade_date']}
        with open(CAL_FILE, 'w', encoding='utf-8') as f:
            json.dump(sorted(dates), f, ensure_ascii=False)
        return dates
    except Exception as e:
        return None


def _is_trading_day(d=None, cal=None):
    """d(YYYY-MM-DD) 是否交易日; 无日历缓存时默认 True(不误跳过)."""
    d = d or datetime.now().strftime('%Y-%m-%d')
    if cal is None:
        cal = _trade_calendar()
    if cal is None:
        return True
    return d in cal


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

    # 交易日检查(节假日/周末空跑幂等, 但跳过更干净)
    cal = _trade_calendar()
    today = datetime.now().strftime('%Y-%m-%d')
    if cal is not None and today not in cal:
        lg.info('  今日 %s 非交易日 → 跳过(日历 %d 天)', today, len(cal))
        out['skipped'] = True
        out['finished'] = datetime.now().isoformat(timespec='seconds')
        out['elapsed'] = round(time.time() - t0, 1)
        out['ok'] = True
        with open(MARKER, 'w', encoding='utf-8') as f:
            json.dump(out, f, ensure_ascii=False, indent=2)
        return out

    from backend.strategy.factor_selector import build_wide_pool
    pool = build_wide_pool() or []
    lg.info('量化池 %d 只', len(pool))

    # ① K线池
    from data_manager import update_pool, _log_update, get_kline_db
    def _plog(msg, code=None):
        lg.info(msg)
    rk = update_pool(pool=pool, workers=16, progress=_plog)
    out['steps']['kline'] = {k: rk[k] for k in ('updated', 'skipped', 'errors', 'rows_added', 'total', 'elapsed') if k in rk}
    lg.info('  K线池: %s', out['steps']['kline'])
    try:
        _c = get_kline_db()
        _latest = _c.execute("SELECT MAX(date) FROM kline_daily").fetchone()[0]
        _c.close()
        if _latest and _latest < today.replace('-', ''):
            lg.warning('  ⚠ 源未覆盖最新交易日: DB max=%s, 今日=%s — 源可能尚未发布当日数据, 请稍后重跑', _latest, today.replace('-', ''))
        else:
            lg.info('  K线最新=%s ✓', _latest)
    except Exception as e:
        lg.warning('  最新日校验失败: %s', str(e)[:60])
    # 同步写 data_update_log(让数据管道面板'上次更新'对齐今日; 表里 update_date 用 YYYY-MM-DD)
    try:
        _log_update(datetime.now().strftime('%Y-%m-%d'),
                    rk.get('total', 0), rk.get('updated', 0), rk.get('rows_added', 0),
                    'ok' if rk.get('errors', 0) < rk.get('total', 0) * 0.5 else 'partial',
                    'update_daily 量化池 +%d 行, 失败 %d' % (rk.get('rows_added', 0), rk.get('errors', 0)))
    except Exception as e:
        lg.warning('  data_update_log 写入失败: %s', str(e)[:60])

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

        # ④ 市场环境 regime (牛/熊/震荡 + 系统风险, 供看盘页显示)
        try:
            from backend.strategy.regime import run as _run_regime
            _rr = _run_regime()
            out['steps']['regime'] = {'regime': _rr.get('regime_cn'), 'as_of': _rr.get('as_of')}
            lg.info('  市场环境: %s (as_of=%s) 建议=%s', _rr.get('regime_cn'), _rr.get('as_of'), _rr.get('suggest_strategy'))
        except Exception as e:
            out['steps']['regime'] = str(e)[:80]
            lg.warning('  市场环境 regime 失败: %s', str(e)[:60])

        # ⑤ 事件驱动候选池 (🅱️ 新闻调研 → 突发利好·短期观察, 不进长期策略)
        try:
            from backend.strategy.news_driven import build_event_pool
            _np = build_event_pool(use_news=True)
            out['steps']['news_driven'] = {'as_of': _np.get('as_of'), 'entries': len(_np.get('entries', []))}
            lg.info('  事件驱动池: as_of=%s 事件股=%d 热点板块=%d',
                    _np.get('as_of'), len(_np.get('entries', [])), len(_np.get('hot_sectors', [])))
        except Exception as e:
            out['steps']['news_driven'] = str(e)[:80]
            lg.warning('  事件驱动池失败: %s', str(e)[:60])

        # ⑥ 个股资讯深挖(🅰️ 选股前几只 → 豆包搜索+LLM主观判断补位)
        try:
            # 用当前选股 top_n 作为深挖候选
            from frontend.plugins.picks.panel import PicksPanel
            import os as _os
            _db = _os.path.join(ROOT, 'data', 'kline.db')
            from factor_engine import FactorScorer, DEFAULT_FILTERS
            _sc = FactorScorer()
            _picks = _sc.score_batch(_db, top_n=8, min_klines=10, filters=DEFAULT_FILTERS)
            _cands = [{"code": s.code, "name": s.name, "total_score": s.total_score,
                       "groups": [{"name": g.name, "weighted_score": g.weighted_score} for g in s.groups]}
                      for s in _picks]
            from backend.strategy.stock_deep import deep_analyze
            _sd = deep_analyze(_cands)
            out['steps']['stock_deep'] = {'as_of': _sd.get('as_of'), 'entries': len(_sd.get('entries', []))}
            lg.info('  个股深挖: as_of=%s 深挖%d只', _sd.get('as_of'), len(_sd.get('entries', [])))
        except Exception as e:
            out['steps']['stock_deep'] = str(e)[:80]
            lg.warning('  个股深挖失败: %s', str(e)[:60])

        # ⑦ 账户净值快照(每日收盘记账, 累计真实净值曲线)
        try:
            from trade_engine.engine import TradeEngine
            _eng = TradeEngine()
            for _a in _eng.list_accounts():
                _snap = _eng.snapshot_nav(_a['id'])
                if _snap:
                    lg.info('  账户净值快照 [%s] %s: nav=%s', _a['id'], _a['name'], _snap['nav'])
            out['steps']['nav_snapshot'] = 'ok'
        except Exception as e:
            out['steps']['nav_snapshot'] = str(e)[:80]
            lg.warning('  净值快照失败: %s', str(e)[:60])

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
