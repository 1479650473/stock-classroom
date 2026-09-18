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


def refresh_fundamentals(codes, workers=16, progress=None, budget_secs=1800):
    """并行刷新基本面(东财估值, 每code ~2s 全历史). 只刷已缓存/有盘的, 防误杀新股.

    东财反爬时接口挂起 → 加时间预算(默认30分钟) + 连续失败快速退出, 防阻塞后续步骤.
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed, wait, FIRST_COMPLETED
    import fundamental as fund
    updated = skipped = 0
    deadline = time.time() + budget_secs
    consec_fail = 0
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futs = {pool.submit(fund.fetch_fundamental, c): c for c in codes}
        done = 0
        pending = dict(futs)
        while pending:
            if time.time() > deadline:
                skipped += len(pending)
                log_budget = len(pending)
                print(f"  基本面: 时间预算 {budget_secs}s 用尽, 跳过剩余 {log_budget} 只", flush=True)
                pending.clear()
                break
            finished, _ = wait(list(pending), timeout=20, return_when=FIRST_COMPLETED)
            if not finished:
                skipped += len(pending)
                pending.clear()
                break
            for f in finished:
                done += 1
                c = pending.pop(f)
                try:
                    rows = f.result()
                    if rows:
                        updated += 1
                        consec_fail = 0
                    else:
                        skipped += 1
                        consec_fail += 1
                except Exception:
                    skipped += 1
                    consec_fail += 1
                if progress and (done % 40 == 0 or done == len(codes)):
                    progress(done, len(codes), updated, skipped)
                if consec_fail >= 30:
                    # 连续失败判定源故障(反爬), 放弃剩余
                    skipped += len(pending)
                    print(f"  基本面: 连续失败 {consec_fail} 只(源故障), 跳过剩余 {len(pending)} 只", flush=True)
                    pending.clear()
                    break
    return {'updated': updated, 'skipped': skipped}


def run(pool_only=False, skip_paper=False, skip_kline=False):
    """入口: 全局异常兜底, 任何一步崩溃都不让整个更新静默失败(9/8~9/9 曾 3 秒静默崩溃)."""
    lg = _log()
    t0 = time.time()
    lg.info('══ update_daily 开始 %s ══', datetime.now().isoformat(timespec='seconds'))
    out = {'started': datetime.now().isoformat(timespec='seconds'), 'steps': {}}
    try:
        return _run_inner(pool_only, skip_paper, skip_kline, lg, t0, out)
    except Exception as e:
        import traceback
        tb = traceback.format_exc()
        lg.error('update_daily 未捕获异常: %s\n%s', str(e)[:200], tb)
        out['error'] = '%s: %s' % (type(e).__name__, str(e)[:300])
        out['finished'] = datetime.now().isoformat(timespec='seconds')
        out['elapsed'] = round(time.time() - t0, 1)
        out['ok'] = False
        try:
            with open(MARKER, 'w', encoding='utf-8') as f:
                json.dump(out, f, ensure_ascii=False, indent=2)
        except Exception:
            pass
        return out


def _run_inner(pool_only, skip_paper, skip_kline, lg, t0, out):

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
    all_codes = []   # skip_kline 时仍供基本面轮换使用

    if not skip_kline:
        # ① K线 全市场增量(含历史缺口检测) —— 每日覆盖全市场约5000只而非仅量化池
        from data_manager import update_codes, _log_update, get_kline_db, update_stock_list
        def _plog(msg, code=None):
            lg.info(msg)
        # 先刷新股票名录(ak_get_all_stocks) → 新股进入 stock_list, 后续首拉全历史
        try:
            _n = update_stock_list()
            lg.info('股票名录刷新: %d 只', _n or 0)
        except Exception as e:
            lg.warning('股票名录刷新失败(%s)', str(e)[:60])
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
        # 新股(last_date 为空) 全历史首拉 — 否则新股永远只有增量窗口, 上市初期历史缺失
        try:
            _c = get_kline_db()
            _new = [str(r[0]) for r in _c.execute(
                "SELECT code FROM stock_list WHERE (last_date IS NULL OR last_date='') "
                "AND (status='active' OR status IS NULL)").fetchall()]
            _c.close()
            if _new:
                lg.info('新股首拉(全历史): %d 只', len(_new))
                rn = update_codes(_new, catch_up_days=4000, workers=8, progress=_plog)
                lg.info('  新股首拉: %s', {k: rn.get(k) for k in ('updated', 'errors', 'rows_added')})
        except Exception as e:
            lg.warning('新股首拉失败(%s)', str(e)[:80])
        # 全市场增量: `catch_up_days` 给安全下限(≥10 个自然日) ——
        # 只用“库内最新日期到今天”的全局缺口，会漏掉“某一天只有部分股票有数据”的情况
        #（2026-09-11 实测：全库最新已是 09-11，但 5194 只里只更新了 1689 只，
        #  gap=0 导致后续每天都不会补），所以固定回看 10 天保证补齐。
        try:
            rk = update_codes(all_codes, catch_up_days=10, workers=16, progress=_plog)
            out['steps']['kline'] = {k: rk[k] for k in ('updated', 'skipped', 'errors', 'rows_added', 'total', 'elapsed') if k in rk}
            lg.info('  K线全市场: %s', out['steps']['kline'])
        except Exception as e:
            import traceback
            out['steps']['kline'] = {'error': '%s: %s' % (type(e).__name__, str(e)[:200])}
            rk = {}
            lg.error('  K线全市场失败(不中断后续): %s\n%s', str(e)[:200], traceback.format_exc()[-1500:])
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

        # ①.5 指数日线(全历史) + hs300.json 重建 + regime 重算 —— 大盘走势/回测基准依赖
        try:
            from akshare_source import ak_fetch_index_kline
            from data_manager import _bulk_insert_kline
            _idx_rows = []
            for _idx in ('sh000001', 'sh000300', 'sh000016', 'sh000688', 'sz399001', 'sz399006'):
                _rows = ak_fetch_index_kline(_idx, days=10000)
                if _rows:
                    _idx_rows.extend(_rows)
            if _idx_rows:
                _c = get_kline_db()
                _bulk_insert_kline(_c, _idx_rows, replace=True)
                _c.commit(); _c.close()
            # 重建 hs300.json(沪深300 全历史, regime/trader 依赖)
            import json as _json
            _c = get_kline_db()
            _hs = _c.execute("SELECT date, close FROM kline_daily WHERE code='sh000300' ORDER BY date").fetchall()
            _c.close()
            if _hs:
                with open(os.path.join(DATA, 'hs300.json'), 'w', encoding='utf-8') as f:
                    _json.dump({'code': 'sh000300', 'name': '沪深300',
                                'dates': ['%s-%s-%s' % (r[0][:4], r[0][4:6], r[0][6:]) for r in _hs],
                                'closes': [float(r[1]) for r in _hs]}, f)
            out['steps']['index'] = {'rows': len(_idx_rows), 'hs300_days': len(_hs)}
            lg.info('  指数日线: %d 行, hs300 %d 天 ✓', len(_idx_rows), len(_hs))
        except Exception as e:
            out['steps']['index'] = str(e)[:100]
            lg.warning('  指数更新失败: %s', str(e)[:80])

    if not pool_only:
        # ② 基本面 (3日轮换: 量化池每日刷 + 全市场按 code%3 每日刷 1/3, 3 天覆盖全市场)
        def _fprog(done, tot, up, sk):
            lg.info('  基本面 [%d/%d] 刷新%d 跳过%d', done, tot, up, sk)
        _rot = datetime.now().day % 3
        _market_codes = [str(c) for c in all_codes if c[:2] in ('00', '30', '60', '68')]
        _pool_set = set(str(c) for c in pool)
        _rotate = [c for c in _market_codes if c not in _pool_set and int(c[-3:]) % 3 == _rot]
        _fund_codes = list(_pool_set) + _rotate
        lg.info('  基本面: 池 %d + 轮换组%d %d = %d 只', len(_pool_set), _rot, len(_rotate), len(_fund_codes))
        rp = refresh_fundamentals(_fund_codes, workers=16, progress=_fprog)
        out['steps']['fundamental'] = {**rp, 'rotate': _rot}
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

    # ⑩ 收盘后市场数据: 涨停(近5交易日回补)/北向/龙虎榜/创新高新低/板块快照/宏观 —— 全部纳入每日自动更新
    if not pool_only:
        try:
            from data_manager import (cache_north_flow_from_akshare, cache_high_low_from_akshare,
                                      cache_lhb_from_akshare, cache_limit_up_from_akshare,
                                      cache_sectors_from_akshare, cache_sector_board_from_akshare)
            _mkt = {}
            try:
                _mkt['north_flow'] = cache_north_flow_from_akshare()
            except Exception as e:
                _mkt['north_flow'] = 'err: %s' % str(e)[:50]
            try:
                _mkt['high_low'] = cache_high_low_from_akshare()
            except Exception as e:
                _mkt['high_low'] = 'err: %s' % str(e)[:50]
            try:
                _mkt['lhb'] = cache_lhb_from_akshare()
            except Exception as e:
                _mkt['lhb'] = 'err: %s' % str(e)[:50]
            # 涨停: 最近 5 个交易日逐个回补(东财按日查询)
            _limit_n = 0
            try:
                _cal = _trade_calendar()
                _today = datetime.now().strftime('%Y-%m-%d')   # 与日历同格式(YYYY-MM-DD)
                _last5 = sorted([d for d in (_cal or set()) if d <= _today])[-5:] or [_today]
                for _d in _last5:
                    _n = cache_limit_up_from_akshare(_d.replace('-', ''))
                    _limit_n += _n or 0
                _mkt['limit_up'] = _limit_n
            except Exception as e:
                _mkt['limit_up'] = 'err: %s' % str(e)[:50]
            try:
                _mkt['sectors'] = cache_sectors_from_akshare()
            except Exception as e:
                _mkt['sectors'] = 'err: %s' % str(e)[:50]
            try:
                _mkt['sector_board'] = cache_sector_board_from_akshare()
            except Exception as e:
                _mkt['sector_board'] = 'err: %s' % str(e)[:50]
            out['steps']['market_data'] = _mkt
            lg.info('  收盘后市场数据: %s', _mkt)
        except Exception as e:
            out['steps']['market_data'] = str(e)[:120]
            lg.warning('  收盘后市场数据失败: %s', str(e)[:80])
        # ⑪ 宏观数据(债券/商品/汇率/海外股指) → macro.db series+regime
        try:
            from backend.macro.snapshot import run as _run_macro
            _mr = _run_macro(verbose=False)
            out['steps']['macro'] = 'ok'
            lg.info('  宏观数据: ok')
        except Exception as e:
            out['steps']['macro'] = str(e)[:100]
            lg.warning('  宏观数据失败: %s', str(e)[:80])
        # ⑫ ETF 数据: 列表刷新 + 新 ETF 全历史首拉 + 存量增量补缺(全市场 ~1600 只)
        try:
            from data_manager import init_etf_tables, cache_etf_list_from_akshare, update_etf_kline
            init_etf_tables()
            _n_list = cache_etf_list_from_akshare()
            _rk = update_etf_kline(workers=10, progress=lambda m, p=None: lg.info('  ETF ' + str(m)))
            out['steps']['etf'] = {'list': _n_list, **{k: _rk.get(k) for k in ('updated', 'errors', 'rows_added', 'total', 'elapsed')}}
            lg.info('  ETF: 列表%d 更新%s 新增%d行 失败%d', _n_list, _rk.get('updated'), _rk.get('rows_added'), _rk.get('errors'))
        except Exception as e:
            out['steps']['etf'] = str(e)[:120]
            lg.warning('  ETF 数据失败: %s', str(e)[:80])
        # ⑬ 个股资金流(日频, 东财 daykline 全历史幂等重拉, ~5200 只)
        try:
            from data_manager import init_fund_flow_tables, update_fund_flow
            init_fund_flow_tables()
            _fk = update_fund_flow(workers=10, progress=lambda m, p=None: lg.info('  资金流 ' + str(m)))
            out['steps']['fund_flow'] = {k: _fk.get(k) for k in ('updated', 'errors', 'rows_added', 'total', 'elapsed')}
            lg.info('  资金流: 更新%s 新增%d行 失败%d', _fk.get('updated'), _fk.get('rows_added'), _fk.get('errors'))
        except Exception as e:
            out['steps']['fund_flow'] = str(e)[:120]
            lg.warning('  资金流失败: %s', str(e)[:80])
        # ⑭ 周K/月K (从日K聚合增量重建最近60天)
        try:
            from data_manager import rebuild_period_kline
            _pk = rebuild_period_kline(recent_days=60,
                                       progress=lambda m, p=None: lg.info('  ' + str(m)))
            out['steps']['period_kline'] = _pk
            lg.info('  周K/月K: weekly=%s monthly=%s (%ss)', _pk.get('weekly'), _pk.get('monthly'), _pk.get('elapsed'))
        except Exception as e:
            out['steps']['period_kline'] = str(e)[:120]
            lg.warning('  周K/月K失败: %s', str(e)[:80])
        # ⑮ 龙虎榜(近5交易日回补) + 融资融券(近5交易日回补, T+1发布)
        try:
            from data_manager import init_lhb_margin_tables, update_lhb_range, update_margin_dates
            init_lhb_margin_tables()
            _cal = _trade_calendar()
            _today = datetime.now().strftime('%Y-%m-%d')
            _last5 = sorted([d for d in (_cal or set()) if d <= _today])[-5:] or [_today]
            _lhb_n = 0
            for _d in _last5:
                _lhb_n += update_lhb_range(_d.replace('-', ''), _d.replace('-', '')) or 0
            _mg = update_margin_dates([d.replace('-', '') for d in _last5])
            out['steps']['lhb_margin'] = {'lhb_rows': _lhb_n, **{k: _mg.get(k) for k in ('ok', 'rows')}}
            lg.info('  龙虎榜+融资融券: lhb=%d行, margin=%s天/%s行', _lhb_n, _mg.get('ok'), _mg.get('rows'))
        except Exception as e:
            out['steps']['lhb_margin'] = str(e)[:120]
            lg.warning('  龙虎榜/融资融券失败: %s', str(e)[:80])
        # ⑯ 行业市盈率(巨潮证监会行业分类 120 行业, 日频)
        try:
            from data_manager import init_industry_pe_table, cache_industry_pe
            init_industry_pe_table()
            _ipe = cache_industry_pe()   # 默认今日
            out['steps']['industry_pe'] = {'rows': _ipe}
            lg.info('  行业PE: %d 行业', _ipe)
        except Exception as e:
            out['steps']['industry_pe'] = str(e)[:120]
            lg.warning('  行业PE失败: %s', str(e)[:80])
        # ⑰ 筹码分布全市场重算(最近250天, subprocess 多进程 — 独立进程避免 Flask job 内 mp 问题)
        try:
            import subprocess as _sp
            _chip_script = os.path.join(ROOT, 'scripts', 'rebuild_chip.py')
            _r = _sp.run([sys.executable, _chip_script, '--days', '250'],
                         cwd=ROOT, capture_output=True, text=True, timeout=5400)
            _tail = (_r.stdout or '')[-300:]
            out['steps']['chip'] = 'ok' if _r.returncode == 0 else 'rc=%s %s' % (_r.returncode, _tail[:150])
            lg.info('  筹码分布: %s', out['steps']['chip'] if _r.returncode == 0 else out['steps']['chip'])
        except Exception as e:
            out['steps']['chip'] = str(e)[:120]
            lg.warning('  筹码分布失败: %s', str(e)[:80])

    out['finished'] = datetime.now().isoformat(timespec='seconds')
    out['elapsed'] = round(time.time() - t0, 1)
    out['ok'] = True
    # 通知：整轮完成 / 有步骤失败（error 或含 'error' 字段的 step）
    try:
        from notify import push as _push_notify
        bad = {}
        for k, v in (out.get('steps') or {}).items():
            if isinstance(v, dict) and v.get('error'):
                bad[k] = str(v.get('error'))[:160]
            elif isinstance(v, str) and ('error' in v or '失败' in v):
                bad[k] = v[:160]
        if bad:
            _push_notify('daily', f'每日自动化有 {len(bad)} 个步骤异常', level='warn',
                         detail='；'.join(f'{k}: {msg}' for k, msg in bad.items()),
                         key='update_daily', throttle_seconds=1800)
        else:
            _push_notify('daily', f'每日自动化完成（{out["elapsed"]}s）', level='info',
                         detail='全部步骤正常', key='update_daily_ok', throttle_seconds=3600)
    except Exception:
        pass
    with open(MARKER, 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    lg.info('══ update_daily 完成 %.1fs → %s ══', out['elapsed'], MARKER)
    return out


if __name__ == '__main__':
    # stderr 重定向到当日日志: 9/8~9/9 静默崩溃根因之一是 traceback 只打 stderr 且无落盘
    try:
        os.makedirs(LOGDIR, exist_ok=True)
        sys.stderr = open(os.path.join(LOGDIR, 'update_daily_stderr_%s.log' % datetime.now().strftime('%Y%m%d')),
                          'a', encoding='utf-8', errors='replace')
    except Exception:
        pass
    po = '--pool-only' in sys.argv
    sp = '--skip-paper' in sys.argv
    sk = '--skip-kline' in sys.argv
    run(pool_only=po, skip_paper=sp, skip_kline=sk)
