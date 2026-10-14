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


# ── 关键步骤判定（2026-10-12）────────────────────────────────────────
# 背景：原来顶层 ok 只由"整轮有没有抛到最外层"决定，步骤内部异常被 try/except 吞掉后
# 只写进 steps{}、从不参与 ok 判定 → 2026-10-12 那次 run 里「3 个 AI 交易员全挂 +
# 5205 只资金流全失败 + 1624 只 ETF 全失败」仍被打成 ok=true，故障潜伏一个多月。
# 另一方面原通知只看 dict 的 'error' 单数键，漏掉了 'errors'>0(fund_flow/etf)
# 与 trader 的 list[{'status':'error'}]，所以连告警都没发。
CRITICAL_STEPS = ('kline', 'fund_flow', 'etf', 'trader', 'catchup', 'freshness_recheck')
# 特意不含 market_data：north_flow 等指标常年为 0，设成 critical 会天天 ok=false（狼来了）
# catchup 的触发面很窄：只有 run_catchup 抛异常时才写成 {'error': ...}（整体失败）；
# 正常/部分补全的结果字典没有 'error' 键 → 不误报。但"停机后补全失败"意味着数据会
# **静默陈旧**，正是 T-DATA-01 那类问题，必须 ok=false。
# freshness_recheck（T-DATA-01，2026-10-13）：跑完后复核 DAILY_TABLES 的缺口，有缺口即 ok=false。
# 注意：这**确实会让当前状态报 ok=false** —— 因为 limit_up(10-09)/margin_daily(10-08)/
# industry_pe(10-09) 现在就是陈旧的；这正是该机制要暴露的事实，不是误报。
# T+1 表已由 catchup.DAILY_TABLES 的 grace 处理，不会"提前一天"乱报。


def _step_bad(key, v):
    """判定单个步骤是否异常。返回 (描述 or None, 是否整体失败)。

    步骤值约定（update_daily 全篇一致）：字符串只可能是
      'ok' / 'no_enabled' / 'skipped' / 'disabled'（正常：该步没跑或无需跑）、
      'rc=N ...'（子进程非零退出=失败）、或异常消息 str(e)。
    所以「不在上面这个白名单里的字符串」一律算异常 —— 这样才盖得住
      lhb_margin 的 'HTTPSConnectionPool... Max retries exceeded'（不含 error 字样）
      和 chip/market_daily 的 'rc=1 ...'（同样不含 error 字样）。

    设计约束（PM 2026-10-12 裁决）：
      (a) **每步最多返回一条描述** → 通知里"一步一行"，不刷屏；
      (b) 返回 `total_fail=False` 的命中一律是 **warn 级、不影响 ok**（只有
          `total_fail=True` 且 key ∈ CRITICAL_STEPS 才会把 ok 置 false）；
      (c) `fundamental` 的轮换空跑形状 `{updated:0, skipped:N, rotate:0}` 里没有
          errors/rows/error/rc 键 → 天然不命中，**不会周期性假告警**。这里刻意**不**
          按步骤名拉白名单：那样会把 fundamental 真正的 `{'error': ...}` 也一起藏掉。
    """
    if isinstance(v, str):
        # 'skipped'/'disabled' 于 2026-10-13 加入：董事长决定**停用 AI 操盘手**（配置层、可逆），
        # 停用后 ⑨ 步写成 'skipped'，必须不算失败、不告警。
        if v in ('ok', 'no_enabled', 'skipped', 'disabled'):
            return None, False
        return v[:160], True
    if isinstance(v, dict):
        if v.get('error'):
            return str(v['error'])[:160], True
        rc = v.get('rc')
        if isinstance(rc, int) and rc != 0:
            return '子进程非零退出 rc=%d' % rc, True
        errs = v.get('errors')
        if isinstance(errs, int) and errs > 0:
            total, updated = v.get('total'), v.get('updated')
            msg = '%d 只失败%s, 成功 %s' % (errs, '/%d' % total if total else '', updated)
            # T-DATA-02：带上第一条异常样例，让告警本身就能定位（不再只能猜"源挂了"）
            samples = v.get('err_samples')
            if isinstance(samples, list) and samples:
                msg += ' | 样例: %s' % str(samples[0])[:110]
            # 只有"有总量且成功数为 0"才算整体失败；部分失败只告警（warn，不影响 ok）
            if isinstance(total, int) and total > 0 and not updated:
                return msg, True
            return msg, False
        rows = v.get('rows')
        if isinstance(rows, int) and rows == 0:
            return '本次入库 0 行', False
        # 其它 dict（如 market_data）：扫一层值里的 'err:' / '失败'
        inner = ['%s=%s' % (kk, vv[:60]) for kk, vv in v.items()
                 if isinstance(vv, str) and (vv.startswith('err') or '失败' in vv
                                             or 'error' in vv.lower())]
        if inner:
            return '; '.join(inner)[:160], False
        return None, False
    if isinstance(v, list):
        # trader: [{'name','status','orders','filled','nav'}]
        failed = [e for e in v if isinstance(e, dict) and e.get('status') == 'error']
        if not failed:
            return None, False
        names = ','.join(str(e.get('name')) for e in failed)
        if len(failed) == len(v):
            return '启用的 %d 个交易员全部失败: %s' % (len(v), names), True
        return '%d/%d 个交易员失败: %s' % (len(failed), len(v), names), False
    return None, False


def _finalize_run(out, lg, t0):
    """收尾：判定 ok / 汇总异常步骤 / 发通知 / 写 marker。抽成函数便于单独测试。"""
    out['finished'] = datetime.now().isoformat(timespec='seconds')
    out['elapsed'] = round(time.time() - t0, 1)
    out['ok'] = True

    # ── T-DATA-01（2026-10-13）：跑完后**复核**关键表新鲜度（只查不拉，重拉交给 catchup）──
    # 原来 audit() 只在 _run_inner 开头跑一次，而 run_catchup() 只在**非交易日**起补全作用
    # → 交易日跑完**没有任何事后复核**，于是 2026-10-12 跑完后
    #   limit_up / margin_daily / industry_pe / lhb_daily 仍然陈旧，却没有任何人知道。
    # 这里复用同一个 audit()：它是**纯查询**（读 kline 覆盖 + 各表 MAX(date)），不会拉数据。
    _fresh = None
    try:
        from backend import catchup as _cuf
        _cal = _trade_calendar()
        # 参考日锚定到**本轮 run 的开始日**（out['started']），而不是 datetime.now()：
        # 长跑会跨零点（10-12 那次 17:00→21:20；计划任务的 StartWhenAvailable 补跑
        # 甚至可能 23:00 起跑），若用 now() 会把"第二天"当成参考日 → 所有表都被判缺失
        # → 天天 ok=false（狼来了）。锚定开始日才与 _run_inner 开头那次 audit 口径一致。
        _today = str(out.get('started') or datetime.now().isoformat(timespec='seconds'))[:10]
        if _cal is None:
            out['freshness_recheck'] = {'status': 'skip', 'reason': '无交易日历'}
        else:
            _a = _cuf.audit(_cal, _today, MARKER)
            _miss = {t: (v.get('missing') or [])
                     for t, v in (_a.get('tables') or {}).items() if v.get('missing')}
            # 幽灵日期体检（T-DATA-01b，2026-10-13）：任何表的 MAX(date) 不得 > kline 的
            # MAX(date)。起因：回补把 46 行 20261013 写进了 limit_up（数据源对未发生的
            # 交易日静默回落到最近交易日），那张表随后"看起来最新" → **掩盖了它缺 10-12 的事实**。
            # 成本极低（11 次 MAX 查询），作为常规体检项常驻。
            _ghosts = {}
            try:
                _ghosts = _cuf.ghost_dates()
            except Exception as _ge:
                lg.warning('  幽灵日期体检失败(不影响其余判定): %s', str(_ge)[:100])
            out['freshness_recheck'] = {
                'ref': _a.get('ref'),
                'ref_capped_to_kline': _a.get('ref_capped_to_kline'),
                'stale_tables': _miss,
                'ghost_dates': _ghosts,
                'kline_missing': (_a.get('kline') or {}).get('missing') or [],
                'summary': _cuf.audit_text(_a),
            }
            _parts = []
            if _miss:
                _parts.append('关键表陈旧: ' + '; '.join(
                    '%s 缺 %s' % (t, ','.join(v[:3])) for t, v in sorted(_miss.items())))
            if _ghosts:
                _parts.append('幽灵日期(>kline最后交易日): ' + '; '.join(
                    '%s MAX=%s(%d行)' % (t, v['max'], v['rows']) for t, v in sorted(_ghosts.items())))
            if _parts:
                _fresh = ' | '.join(_parts)
                lg.warning('  跑后复核：%s', _fresh[:240])
            if _miss:
                lg.warning('  跑后新鲜度复核：%d 张关键表仍陈旧 -> %s', len(_miss), _fresh[:200])
    except Exception as e:
        lg.warning('跑后新鲜度复核失败(不影响其余判定): %s', str(e)[:120])

    bad, critical = {}, []
    try:
        # 把 catchup 也纳入健康判定（T-DATA-03）：非交易日的早退分支只跑补全，
        # 若补全抛错会写 out['catchup'] = {'error': ...}，必须能被识别。
        candidates = dict(out.get('steps') or {})
        if out.get('catchup') is not None:
            candidates['catchup'] = out['catchup']
        # T-DATA-01：复核结果用「字符串步骤」的既有约定表达（'ok' / 失败描述），
        # 这样 _step_bad 天然能识别，不必再为它加一种值形状。
        if _fresh is not None:
            candidates['freshness_recheck'] = _fresh
        for k, v in candidates.items():
            msg, total_fail = _step_bad(k, v)
            if msg:
                bad[k] = msg
                if total_fail and k in CRITICAL_STEPS:
                    critical.append(k)
    except Exception as e:
        lg.warning('步骤健康判定失败: %s', str(e)[:100])
    out['bad_steps'] = bad
    out['critical_failed'] = critical
    if critical:
        out['ok'] = False
    try:
        # 必须写成 `from backend import notify`：notify.py 内部用相对导入
        # (`from .api.paths import DATA_DIR`)，而本脚本会把 ROOT/backend 都塞进 sys.path，
        # 于是 `from notify import push` 会把 notify.py 当成**顶层模块**导入 →
        # ImportError: attempted relative import with no known parent package。
        # 旧代码正是这么写的，且被 `except Exception: pass` 吞掉 →
        # **update_daily 的通知通道从来没发出过任何一条**（2026-10-12 才发现）。
        from backend import notify as _notify
        if critical:
            _notify.push('daily', '每日自动化关键步骤失败：' + '、'.join(critical),
                         level='error',
                         detail='；'.join('%s: %s' % (k, bad[k]) for k in critical),
                         key='update_daily_critical', throttle_seconds=600)
        elif bad:
            _notify.push('daily', '每日自动化有 %d 个步骤异常' % len(bad), level='warn',
                         detail='；'.join('%s: %s' % (k, msg) for k, msg in bad.items()),
                         key='update_daily', throttle_seconds=1800)
        else:
            _notify.push('daily', '每日自动化完成（%ss）' % out['elapsed'], level='info',
                         detail='全部步骤正常', key='update_daily_ok', throttle_seconds=3600)
    except Exception as e:
        # 不再静默：通知失败本身也要留痕（静默 pass 是上面那个 bug 潜伏一个月的原因）
        lg.warning('通知发送失败(不影响数据更新): %s', str(e)[:150])
    out['_run_state'] = 'done'   # 明确收尾标记（与开局心跳的 'running' 相对）
    with open(MARKER, 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    if critical:
        lg.error('══ update_daily 完成 %.1fs 但**关键步骤失败** %s（ok=false）→ %s ══',
                 out['elapsed'], ','.join(critical), MARKER)
    else:
        lg.info('══ update_daily 完成 %.1fs → %s ══', out['elapsed'], MARKER)
    return out


def run(pool_only=False, skip_paper=False, skip_kline=False):
    """入口: 全局异常兜底, 任何一步崩溃都不让整个更新静默失败(9/8~9/9 曾 3 秒静默崩溃)."""
    lg = _log()
    t0 = time.time()
    lg.info('══ update_daily 开始 %s ══', datetime.now().isoformat(timespec='seconds'))
    out = {'started': datetime.now().isoformat(timespec='seconds'), 'steps': {}}

    # 开局心跳（2026-10-14 新增）─────────────────────────────────────────
    # 事故：2026-10-14 的 run 17:00:01 启动、19:22 仍在写日志，随后进程被
    # STATUS_CONTROL_C_EXIT(0xC000013A) 终止于**收尾之前** —— 而 marker 只在
    # _finalize_run 里写，于是"没有 marker、没有通知、没有 ok 值"，整套失败告警不触发。
    # 这是比"跑失败"更隐蔽的一类：**静默死亡**。
    # 修法：开局先落一个 _run_state=running 的 marker（含 pid），收尾时被完整结果覆盖。
    # 于是"marker 里还是 running 但进程已不存在" = 铁证级静默死亡，可被看门狗发现。
    # 字段名用 _run_state 而非 status：marker 会被 /api/pipeline/status 原样转发给前端，
    # 用 status 可能与 UI 语义冲突（该接口自身的 status 表示"未更新/读取失败"）。
    out['_run_state'] = 'running'
    out['_pid'] = os.getpid()
    try:
        with open(MARKER, 'w', encoding='utf-8') as f:
            json.dump(out, f, ensure_ascii=False, indent=2)
    except Exception as e:
        lg.warning('开局心跳写入失败(不阻断主流程): %s', str(e)[:150])

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
        out['_run_state'] = 'error'  # 未捕获异常也走收尾（与静默死亡的 'running' 区分开）
        try:
            with open(MARKER, 'w', encoding='utf-8') as f:
                json.dump(out, f, ensure_ascii=False, indent=2)
        except Exception as e:
            # 不再静默 pass：这里吞掉异常就等于又制造一个"静默死亡"盲区
            lg.error('收尾 marker 写入失败(将以 running 状态残留，看门狗会报): %s', str(e)[:200])
        return out


def _run_inner(pool_only, skip_paper, skip_kline, lg, t0, out):

    # 交易日检查(节假日/周末空跑幂等, 但跳过更干净)
    cal = _trade_calendar()
    today = datetime.now().strftime('%Y-%m-%d')

    # ── 数据补全审计: 检测停机期间遗留缺口(某日缺数据/某日只有部分股票/整日缺失) ──
    #    主流程据此动态放大拉取窗口; 非交易日检测到缺口也会执行补全(平时跳过)
    _cu, _audit = None, None
    try:
        from backend import catchup as _cu
        _audit = _cu.audit(cal, today, MARKER)
        _win = _audit.get('window') or ['-', '-']
        out['audit'] = {'last_run': _audit.get('last_run'), 'gap_days': _audit.get('gap_days'),
                        'ref': _audit.get('ref'), 'summary': _cu.audit_text(_audit)}
        lg.info('补全审计: 上次运行=%s (%s天前), 窗口 %s~%s → %s',
                _audit.get('last_run'), _audit.get('gap_days'), _win[0], _win[1],
                _cu.audit_text(_audit))
    except Exception as e:
        lg.warning('补全审计失败(不影响正常更新): %s', str(e)[:100])
    _gap_cal = int((_audit or {}).get('gap_days') or 0)   # 距上次运行的自然日数(动态窗口用)

    if cal is not None and today not in cal:
        lg.info('  今日 %s 非交易日 → 跳过(日历 %d 天)', today, len(cal))
        if _cu is not None and _audit and _audit.get('missing_total'):
            lg.info('  非交易日但检测到数据缺口 → 执行补全 ...')
            try:
                out['catchup'] = _cu.run_catchup(_audit, cal, today, lg=lg)
                lg.info('  非交易日补全完成: %s', out['catchup'])
            except Exception as e:
                out['catchup'] = {'error': str(e)[:150]}
                lg.warning('  非交易日补全失败: %s', str(e)[:100])
        out['skipped'] = True
        # T-DATA-03（2026-10-12）：原来这里自行写 out['ok']=True 并直接落盘，
        # **绕过了 _finalize_run** → 非交易日的补全失败同样会被记成成功
        # （与授权 2 修的是同一类"假 ok"）。改走同一套收尾逻辑。
        return _finalize_run(out, lg, t0)

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
            _ck = 10   # 默认回看 10 条: 修复"某天只有部分股票"的残缺
            if _cu is not None and _audit:
                _w = _cu.kline_window_days(_audit, cal, today)
                if _w:
                    _ck = max(_ck, _w)
                    lg.info('  K线窗口因缺口放大: %d 条 (审计: %s)', _ck, _cu.audit_text(_audit))
            rk = update_codes(all_codes, catch_up_days=_ck, workers=16, progress=_plog)
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

        # ⑨-0 LLM 余额体检（2026-10-13，发现 2）—— 在跑 LLM 重活之前先看余额。
        #   库里真实出现过 3 条 `402 Insufficient Balance`；402 与网络故障性质不同，
        #   不该混进重试策略（对 402 重试 6 次 = 白等 127s）。这里只做**只读查询 + 低余额告警**。
        #   用「字符串步骤」的既有约定：正常/不可用都写 'ok'（不误报），只有确实偏低才写失败串。
        try:
            from backend.agent.llm_client import get_balance_status
            _bs = get_balance_status()
            if _bs is None:
                out['steps']['llm_balance'] = 'ok'          # 查询不可用 → 不告警，只记日志
                lg.info('  LLM 余额: 查询不可用(跳过)')
            elif _bs.get('low'):
                out['steps']['llm_balance'] = (
                    '余额偏低: %.2f %s < 阈值 %.2f（402 Insufficient Balance 风险，需充值）'
                    % (_bs['total'], _bs['currency'], _bs['warn_below']))
                lg.warning('  LLM 余额偏低: %.2f %s（阈值 %.2f）—— 有 402 风险',
                           _bs['total'], _bs['currency'], _bs['warn_below'])
            else:
                out['steps']['llm_balance'] = 'ok'
                lg.info('  LLM 余额: %.2f %s（阈值 %.2f）',
                        _bs['total'], _bs['currency'], _bs['warn_below'])
        except Exception as e:
            out['steps']['llm_balance'] = 'ok'
            lg.info('  LLM 余额体检失败(忽略): %s', str(e)[:80])

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
                # 无 enabled 档案 → 该步**跳过**，不算失败、不告警（2026-10-13 董事长决定停用 AI 操盘手：
                # "LLM 逐天推理，收益太低了"。这是**配置层停用**，代码/数据/历史决策全部保留，随时可逆）。
                # ⚠️ 未削弱原判定：将来重新启用后若"有 enabled 档案却全部失败"，
                #    仍走上面的 list 分支 → _step_bad 判为整体失败 → ok=false + error 告警。
                out['steps']['trader'] = 'skipped'
                lg.info('  AI操盘手: 无启用的交易员(已停用), 跳过该步')
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
            # 涨停: 最近 5 个交易日 + 审计缺口日, 逐个回补(东财按日查询)
            _limit_n = 0
            try:
                _cal = _trade_calendar()
                _today = datetime.now().strftime('%Y-%m-%d')   # 与日历同格式(YYYY-MM-DD)
                _last5 = sorted([d for d in (_cal or set()) if d <= _today])[-5:] or [_today]
                _lud = set(_last5)
                if _cu is not None and _audit:
                    _lud |= {_cu._dash(x) for x in
                             (_audit.get('tables', {}).get('limit_up', {}).get('missing') or [])[:40]}
                for _d in sorted(_lud):
                    _n = cache_limit_up_from_akshare(_d.replace('-', ''))
                    _limit_n += _n or 0
                _mkt['limit_up'] = _limit_n
                if len(_lud) > 5:
                    _mkt['limit_up_days'] = len(_lud)
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
            # 实时快照缓存(stock_cache.db stock_spot, 前端实时行情回退用)
            try:
                from data_manager import cache_spot_from_akshare
                _mkt['spot'] = cache_spot_from_akshare()
            except Exception as e:
                _mkt['spot'] = 'err: %s' % str(e)[:50]
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
            out['steps']['etf'] = {'list': _n_list, **{k: _rk.get(k) for k in ('updated', 'errors', 'rows_added', 'total', 'elapsed', 'err_samples')}}
            lg.info('  ETF: 列表%d 更新%s 新增%d行 失败%d', _n_list, _rk.get('updated'), _rk.get('rows_added'), _rk.get('errors'))
        except Exception as e:
            out['steps']['etf'] = str(e)[:120]
            lg.warning('  ETF 数据失败: %s', str(e)[:80])
        # ⑬ 个股资金流(日频, 东财 daykline 全历史幂等重拉, ~5200 只)
        try:
            from data_manager import init_fund_flow_tables, update_fund_flow
            init_fund_flow_tables()
            _fk = update_fund_flow(workers=10, progress=lambda m, p=None: lg.info('  资金流 ' + str(m)))
            out['steps']['fund_flow'] = {k: _fk.get(k) for k in ('updated', 'errors', 'rows_added', 'total', 'elapsed', 'err_samples')}
            lg.info('  资金流: 更新%s 新增%d行 失败%d', _fk.get('updated'), _fk.get('rows_added'), _fk.get('errors'))
        except Exception as e:
            out['steps']['fund_flow'] = str(e)[:120]
            lg.warning('  资金流失败: %s', str(e)[:80])
        # ⑭ 周K/月K (从日K聚合增量重建最近 60 天; 停机后按 gap 放大)
        try:
            from data_manager import rebuild_period_kline
            _pk_days = max(60, _gap_cal + 5)
            _pk = rebuild_period_kline(recent_days=min(_pk_days, 400),
                                       progress=lambda m, p=None: lg.info('  ' + str(m)))
            out['steps']['period_kline'] = _pk
            lg.info('  周K/月K: weekly=%s monthly=%s (%ss)', _pk.get('weekly'), _pk.get('monthly'), _pk.get('elapsed'))
        except Exception as e:
            out['steps']['period_kline'] = str(e)[:120]
            lg.warning('  周K/月K失败: %s', str(e)[:80])
        # ⑮ 龙虎榜 + 融资融券(近5交易日 + 审计缺口日, T+1发布)
        try:
            from data_manager import init_lhb_margin_tables, update_lhb_range, update_margin_dates
            init_lhb_margin_tables()
            _cal = _trade_calendar()
            _today = datetime.now().strftime('%Y-%m-%d')
            _last5 = sorted([d for d in (_cal or set()) if d <= _today])[-5:] or [_today]
            _lhbd = set(_last5)
            _mgd = set(_last5)
            if _cu is not None and _audit:
                _lhbd |= {_cu._dash(x) for x in
                          (_audit.get('tables', {}).get('lhb_daily', {}).get('missing') or [])[:40]}
                _mgd |= {_cu._dash(x) for x in
                         (_audit.get('tables', {}).get('margin_daily', {}).get('missing') or [])[:40]}
            _lhb_n = 0
            for _d in sorted(_lhbd):
                _lhb_n += update_lhb_range(_d.replace('-', ''), _d.replace('-', '')) or 0
            _mg = update_margin_dates([d.replace('-', '') for d in sorted(_mgd)])
            out['steps']['lhb_margin'] = {'lhb_rows': _lhb_n, 'lhb_days': len(_lhbd),
                                          **{k: _mg.get(k) for k in ('ok', 'rows')}}
            lg.info('  龙虎榜+融资融券: lhb=%d行/%d天, margin=%s天/%s行', _lhb_n, len(_lhbd), _mg.get('ok'), _mg.get('rows'))
        except Exception as e:
            out['steps']['lhb_margin'] = str(e)[:120]
            lg.warning('  龙虎榜/融资融券失败: %s', str(e)[:80])
        # ⑯ 行业市盈率(巨潮证监会行业分类 120 行业, 日频; 含审计缺口日)
        try:
            from data_manager import init_industry_pe_table, cache_industry_pe
            init_industry_pe_table()
            _ipe_dates = [datetime.now().strftime('%Y%m%d')]
            if _cu is not None and _audit:
                _ipe_dates += (_audit.get('tables', {}).get('industry_pe', {}).get('missing') or [])[:40]
            _ipe = sum(cache_industry_pe(_d) or 0 for _d in dict.fromkeys(_ipe_dates))
            out['steps']['industry_pe'] = {'rows': _ipe, 'days': len(set(_ipe_dates))}
            lg.info('  行业PE: %d 行业 / %d 天', _ipe, len(set(_ipe_dates)))
        except Exception as e:
            out['steps']['industry_pe'] = str(e)[:120]
            lg.warning('  行业PE失败: %s', str(e)[:80])
        # ⑰ 筹码分布全市场重算(最近250天, subprocess 多进程 — 独立进程避免 Flask job 内 mp 问题)
        try:
            import subprocess as _sp
            _chip_script = os.path.join(ROOT, 'scripts', 'rebuild_chip.py')
            _chip_log = os.path.join(LOGDIR, 'step_chip.log')
            with open(_chip_log, 'w', encoding='utf-8', errors='replace') as _lf:
                _r = _sp.run([sys.executable, _chip_script, '--days', '250'],
                             cwd=ROOT, stdout=_lf, stderr=_sp.STDOUT, timeout=5400)
            _tail = ''
            out['steps']['chip'] = 'ok' if _r.returncode == 0 else 'rc=%s %s' % (_r.returncode, _tail[:150])
            lg.info('  筹码分布: %s', out['steps']['chip'] if _r.returncode == 0 else out['steps']['chip'])
        except Exception as e:
            out['steps']['chip'] = str(e)[:120]
            lg.warning('  筹码分布失败: %s', str(e)[:80])
        # ⑱ 大盘情绪(涨停/跌停家数, 本地K线派生 — 覆盖审计缺口)
        try:
            import subprocess as _sp
            _md_script = os.path.join(ROOT, 'scripts', 'rebuild_market_daily.py')
            _md_log = os.path.join(LOGDIR, 'step_market_daily.log')
            _md_days = max(5, _gap_cal + 2)
            with open(_md_log, 'w', encoding='utf-8', errors='replace') as _lf:
                _r = _sp.run([sys.executable, _md_script, '--days', str(_md_days)],
                             cwd=ROOT, stdout=_lf, stderr=_sp.STDOUT, timeout=900)
            out['steps']['market_daily'] = 'ok' if _r.returncode == 0 else 'rc=%s' % _r.returncode
            lg.info('  大盘情绪(涨停/跌停家数): %s', out['steps']['market_daily'])
        except Exception as e:
            out['steps']['market_daily'] = str(e)[:120]
            lg.warning('  大盘情绪失败: %s', str(e)[:80])
        # ⑲ 股东户数/基金持仓(季度, 最近2期幂等 — 新报告期自动拉取)
        try:
            import subprocess as _sp
            _h_script = os.path.join(ROOT, 'scripts', 'rebuild_holder.py')
            _h_log = os.path.join(LOGDIR, 'step_holder.log')
            with open(_h_log, 'w', encoding='utf-8', errors='replace') as _lf:
                _r = _sp.run([sys.executable, _h_script, '--recent', '2'],
                             cwd=ROOT, stdout=_lf, stderr=_sp.STDOUT, timeout=1800)
            out['steps']['holder'] = 'ok' if _r.returncode == 0 else 'rc=%s' % _r.returncode
            lg.info('  股东户数/基金持仓: %s', out['steps']['holder'])
        except Exception as e:
            out['steps']['holder'] = str(e)[:120]
            lg.warning('  股东/基金持仓失败: %s', str(e)[:80])
        # ⑳ 概念/行业板块指数增量(THS 375概念+90行业; 停机后按 gap 放大)
        try:
            from data_manager import init_board_tables, cache_board_list, update_board_daily
            init_board_tables()
            cache_board_list()
            _bd = update_board_daily(recent_days=max(10, _gap_cal + 2), workers=8,
                                     progress=lambda m, p=None: None)
            out['steps']['board'] = {k: _bd.get(k) for k in ('updated', 'errors', 'rows_added', 'total', 'elapsed')}
            lg.info('  板块指数: 更新%s 失败%s 新增%d行', _bd.get('updated'), _bd.get('errors'), _bd.get('rows_added'))
        except Exception as e:
            out['steps']['board'] = str(e)[:120]
            lg.warning('  板块指数失败: %s', str(e)[:80])

        # ㉑ 组合纸面盘（K=20/H=10 中盘域，每日 1/H 分仓）—— 前瞻记录，同日幂等;
        #    停机错过的交易日由 heal_paper_portfolio 逐日回放补齐
        try:
            from backend.alpha.paper_portfolio import _load_state as _pp_state, check_staleness as _pp_stale
            from backend import catchup as _cu2
            _pp_info = {}
            for _tag in ('', 'rank2'):     # v1 等权 / v2 rank2 加权（两条独立的前瞻记录）
                try:
                    _cu2.heal_paper_portfolio(_tag, lg=lg)
                except Exception as _e:
                    lg.warning('  纸面盘回放补缺失败[%s]: %s', _tag or 'v1', str(_e)[:80])
                _st = _pp_state(_tag) or {}
                _stale = _pp_stale(tag=_tag)
                _nav = (_st.get('nav_history') or [{}])[-1].get('nav')
                _pp_info[_tag or 'v1'] = {'nav': _nav,
                                          'positions': len(_st.get('holdings') or {}),
                                          'date': _st.get('last_date'),
                                          'stale': _stale.get('stale')}
                lg.info('  组合纸面盘[%s]: %s 净值 %s 持仓 %s（落后 %s 天）', _tag or 'v1',
                        _st.get('last_date'), _nav, len(_st.get('holdings') or {}),
                        _stale.get('gap_days'))
            out['steps']['paper_portfolio'] = _pp_info
        except Exception as e:
            out['steps']['paper_portfolio'] = {'error': str(e)[:120]}
            lg.warning('  组合纸面盘失败: %s', str(e)[:80])

        # ㉒ 基金套利（LOF 折溢价）：名单/申购门槛/日线增量/净值增量 + 费率轮换
        try:
            from backend.fund import sync as _fa_sync
            _fa = _fa_sync.run_daily(workers=4)
            try:
                _fee = _fa_sync.refresh_fees(workers=2)
            except Exception as _e:  # noqa: BLE001
                _fee = {'error': str(_e)[:80]}
            out['steps']['fund_arb'] = {
                'stats': _fa.get('stats'),
                'daily': {k: _fa.get('daily', {}).get(k) for k in ('ok', 'fail', 'rows')},
                'nav': {k: _fa.get('nav', {}).get(k) for k in ('ok', 'fail', 'rows')},
                'fees': {k: _fee.get(k) for k in ('ok', 'fail')},
                'elapsed': _fa.get('elapsed'),
            }
            lg.info('  基金套利: LOF %s 只 | 日线 +%s 净值 +%s | %ss',
                    (_fa.get('stats') or {}).get('lof_count'),
                    (_fa.get('daily') or {}).get('rows'), (_fa.get('nav') or {}).get('rows'),
                    _fa.get('elapsed'))
        except Exception as e:
            out['steps']['fund_arb'] = {'error': str(e)[:120]}
            lg.warning('  基金套利同步失败: %s', str(e)[:80])

        # ㉓ 分钟线(5min)每日增量: baostock 低并发(3进程), 只拉最近窗口; 停机缺口按 gap 放大
        try:
            import subprocess as _sp
            _min_script = os.path.join(ROOT, 'scripts', 'rebuild_minute_baostock.py')
            _min_log = os.path.join(LOGDIR, 'step_minute.log')
            _min_days = min(60, max(12, _gap_cal + 5))
            _t0m = time.time()
            with open(_min_log, 'w', encoding='utf-8', errors='replace') as _lf:
                _r = _sp.run([sys.executable, _min_script, '--freq', '5', '--source', 'minute',
                              '--recent-days', str(_min_days), '--procs', '3',
                              '--wait-max-min', '120'],
                             cwd=ROOT, stdout=_lf, stderr=_sp.STDOUT, timeout=7200)
            out['steps']['minute'] = {'rc': _r.returncode, 'days': _min_days,
                                      'elapsed': round(time.time() - _t0m, 1)}
            lg.info('  分钟线(5min): %s', out['steps']['minute'])
        except Exception as e:
            out['steps']['minute'] = str(e)[:120]
            lg.warning('  分钟线增量失败: %s', str(e)[:80])

    return _finalize_run(out, lg, t0)


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
