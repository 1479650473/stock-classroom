# -*- coding: utf-8 -*-
"""update_daily.py — 每日数据自动更新(独立脚本, 供 Windows 任务计划调用).

完整链路共 9 步并保证 as_of 一致:
  ① 全市场/量化池 K线  ② 基本面 EP/BP/ROE  ③ 组合纸面盘  ④ regime
  ⑤ 事件驱动池        ⑥ 个股资讯深挖        ⑦ 持仓守护      ⑧ 净值快照
  ⑨ AI 操盘手决策

用法:  python update_daily.py [--pool-only] [--skip-paper]
结果写入 data/update_marker.json + logs/update_daily_YYYYMMDD.log
"""
import os, sys, json, time, logging
from datetime import datetime, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, 'backend'))

from backend.api.paths import DATA_DIR, PROJECT_DIR  # noqa: E402

ROOT = PROJECT_DIR
DATA = DATA_DIR
LOGDIR = os.path.join(DATA_DIR, 'logs')
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

    # ① K线 全市场增量(仅补最新缺口, 不重拉全量历史) —— 每日应覆盖全市场约5000只而非仅量化池
    from data_manager import update_codes, _log_update, get_kline_db
    def _plog(msg, code=None):
        lg.info(msg)
    # 全市场代码(优先本地 stock_list 稳定来源, akshare 实时接口常被反爬拉空 → 兜底池)
    all_codes = []
    try:
        _c = get_kline_db()
        _rows = _c.execute("SELECT code FROM stock_list WHERE status='active' OR status IS NULL").fetchall()
        _c.close()
        all_codes = [str(r[0]) for r in _rows]
        lg.info('全市场(本地stock_list) %d 只', len(all_codes))
    except Exception as e:
        lg.warning('本地stock_list读取失败(%s)', str(e)[:50])
    if not all_codes:
        try:
            from akshare_source import ak_get_all_stocks
            _st = ak_get_all_stocks() or []
            all_codes = [str(s["code"]) for s in _st]
            lg.info('全市场(akshare) %d 只', len(all_codes))
        except Exception as e:
            lg.warning('akshare获取全市场失败(%s), 回退量化池 %d 只', str(e)[:50], len(pool))
            all_codes = [str(c) for c in pool]
    # 只拉增量小窗口(3根bar≈当日+前2交易日, 覆盖跨周末/停牌当日无bar), 不重拉历史
    # 历史已存在DB, 因子计算读DB完整K线, 无需每次带warmup重拉60根
    rk = update_codes(all_codes, catch_up_days=3, workers=16, progress=_plog)
    out['steps']['kline'] = {k: rk[k] for k in ('updated', 'skipped', 'errors', 'rows_added', 'total', 'elapsed') if k in rk}
    lg.info('  K线全市场: %s', out['steps']['kline'])
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
            from backend.paper_worker import run_paper_multi
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

        # ⑦ 每日持仓守护(🅰️ 卖出条件: 保护优先于排名). 默认 dry_run 预览不真卖, 由用户确认.
        try:
            from backend.strategy.day_guard import run_day_guard
            _dg = run_day_guard(dry_run=True)   # 预览: 只判定+记录, 不真卖(防自动清仓误伤)
            out['steps']['day_guard'] = {'n_checked': _dg.get('n_checked'), 'n_sold_signal': _dg.get('n_sold')}
            lg.info('  持仓守护(预览): 检查 %d 只 · 保护卖出信号 %d 只(待确认)',
                    _dg.get('n_checked'), _dg.get('n_sold'))
        except Exception as e:
            out['steps']['day_guard'] = str(e)[:80]
            lg.warning('  持仓守护失败: %s', str(e)[:60])

        # ⑧ 账户净值快照(每日收盘记账, 累计真实净值曲线)
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

        # ⑨ AI 操盘手决策 (LLM 自主交易员: 读账户/持仓/新闻 → 思考 → 买卖/保持 → 记长期记忆)
        #    与策略进化闭环不同: 这里模型直接操作自己的专属账户, 不写策略/不跑回测.
        #    支持多个交易员: 对每个 enabled 档案逐个执行(同日幂等).
        try:
            from backend.trader import store as _tstore
            _profs = [p for p in _tstore.list_profiles() if p.get('enabled')]
            if _profs:
                from backend.trader.daily import run_daily_decision
                _tres = []
                for _p in _profs:
                    lg.info('  AI操盘手[%s] 决策中(账户 #%s)...', _p.get('name'), _p.get('account_id'))
                    _dec = run_daily_decision(
                        profile_id=int(_p['id']), trigger='auto',
                        progress=lambda m, _n=_p.get('name'): lg.info('   [操盘手·%s] %s', _n,
                                                                    (m.get('msg') if isinstance(m, dict) else str(m))))
                    _ex = _dec.get('executions') or []
                    _tres.append({
                        'name': _p.get('name'), 'status': _dec.get('status'),
                        'orders': len(_dec.get('plan') or []),
                        'filled': sum(1 for e in _ex if e.get('ok')),
                        'nav': _dec.get('nav_after'),
                    })
                    lg.info('  AI操盘手[%s]: status=%s 委托=%d 成交=%d 净值=%s',
                            _p.get('name'), _dec.get('status'), len(_dec.get('plan') or []),
                            sum(1 for e in _ex if e.get('ok')), _dec.get('nav_after'))
                out['steps']['trader'] = _tres
            else:
                out['steps']['trader'] = 'no_enabled'
                lg.info('  AI操盘手: 无启用的交易员, 跳过')
        except Exception as e:
            out['steps']['trader'] = str(e)[:120]
            lg.warning('  AI操盘手决策失败: %s', str(e)[:80])

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
