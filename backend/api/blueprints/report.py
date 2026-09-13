# -*- coding: utf-8 -*-
"""Report blueprint — 回测/因子报告（自包含 HTML，浏览器可直接打开或另存）。

GET  /api/report/composite?date=     固定权重因子组合的验证报告（全期 + 10 折样本外）
GET  /api/report/factor-zoo          因子体检榜报告（Top 因子表）
POST /api/report/backtest            通用：提交 {title, dates, equity|returns, metrics, trades} → HTML
"""
from __future__ import annotations

import json
import os

from flask import Blueprint, Response, request

from ..envelope import ok, err, int_arg
from ..paths import DATA_DIR

bp = Blueprint("report", __name__, url_prefix="/api/report")


def _html(body: str, filename: str = "") -> Response:
    headers = {"Content-Type": "text/html; charset=utf-8"}
    if filename:
        headers["Content-Disposition"] = f'inline; filename="{filename}"'
    return Response(body, headers=headers)


@bp.route("/composite", methods=["GET"])
def composite_report():
    """因子组合验证报告（读 data/alpha_composite.json）。"""
    from backend.strategy.report import build_report
    path = os.path.join(str(DATA_DIR), "alpha_composite.json")
    if not os.path.exists(path):
        return err(404, "not_found", "尚未生成组合验证报告（先运行 composite_test.py）", retriable=False)
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    folds = data.get("folds") or []
    meta = data.get("meta") or {}
    full = data.get("full") or {}
    # 用每折样本外超额拼一条等权"组合净值曲线"（近似直观展示）
    eq, dates = [1.0], []
    for f in folds:
        eq.append(eq[-1] * (1.0 + float(f.get("oos_ex") or 0.0)))
        dates.append(str(f.get("test", "")).split("~")[-1])
    trades = [{"date": f.get("test"), "code": f"折{f.get('fold')}", "name": "样本外超额",
               "side": "", "qty": "", "price": "",
               "pnl": f"{float(f.get('oos_ex') or 0) * 100:+.1f}%",
               "pnl_pct": f"{float(f.get('oos_sortino') or 0):+.2f}",
               "reason": f"IC {float(f.get('oos_ic') or 0):+.4f} / 回撤 {float(f.get('oos_dd') or 0) * 100:.1f}%"}
              for f in folds]
    body = build_report(
        title="因子组合验证报告",
        subtitle=f"组合：{' '.join(meta.get('components') or [])} · 持有 {meta.get('hold')} 天 · "
                 f"Top{meta.get('top_k')} · 成本单边 5bp",
        series=eq, dates=dates, metrics=full, trades=trades,
        notes=("口径：等权 rank 合成，无搜索无挑选偏差；每折独立（训练窗口只用于选公式，"
               "测试窗口只用于评估）。曲线为各折样本外超额串起来，仅用于直观展示稳定性，"
               "不代表连续实盘净值。"))
    return _html(body, "alpha_composite_report.html")


@bp.route("/factor-zoo", methods=["GET"])
def factor_zoo_report():
    """因子体检榜报告（读 data/factor_zoo.json）。"""
    from backend.strategy.report import build_report
    path = os.path.join(str(DATA_DIR), "factor_zoo.json")
    if not os.path.exists(path):
        return err(404, "not_found", "尚未生成因子体检（先运行 factor_zoo.py）", retriable=False)
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    meta = data.get("meta") or {}
    rows = sorted(data.get("factors") or [], key=lambda r: -abs(float(r.get("ic_neutral") or 0)))
    top = int_arg(request.args.get("top"), 30, 1, 200)
    picks = rows[:top]
    trades = [{"date": r.get("factor"),
               "code": f"IC(中性) {float(r.get('ic_neutral') or 0):+.4f}",
               "name": f"IC(1日) {float(r.get('ic') or 0):+.4f}",
               "side": f"IC(20日) {float(r.get('ic20') or 0):+.4f}",
               "qty": f"{float(r.get('ex_ann') or 0) * 100:+.1f}%",
               "price": f"{float(r.get('ex_neutral') or 0) * 100:+.1f}%",
               "pnl": f"{float(r.get('ex_sortino') or 0):+.2f}",
               "pnl_pct": f"{float(r.get('maxdd') or 0) * 100:.1f}%",
               "reason": f"半年为正 {r.get('seg_pos')}/{int(r.get('n_seg') or 0) - 1}"}
              for r in picks]
    body = build_report(
        title="因子体检榜",
        subtitle=(f"{meta.get('codes')} 只 × {meta.get('days')} 日 · Top{top} · "
                  f"等权池年化 {(float(meta.get('pool_ann') or 0)) * 100:+.1f}%"
                  " · 列：因子 / IC(中性) / IC(1日) / IC(20日) / 超额年化 / 超额(中性) / Sortino / 回撤 / 半年为正"),
        series=[1.0] + [1.0 + float(r.get("ic_neutral") or 0) for r in picks[:60]],
        metrics={"days": float(meta.get("days") or 0)},
        trades=trades,
        notes=("判读：IC(中性) 是剥离市值/波动后的排序预测力，|IC| ≥ 0.005 才算有信号；"
               "「超额为正但多空价差为负」的因子（如低波动类）是风格 beta，不是选股能力。"))
    return _html(body, "factor_zoo_report.html")


@bp.route("/factor-analysis", methods=["GET"])
def factor_analysis_report():
    """单因子分析报告：分位组合柱状图 + 多空净值 + IC 衰减 + 成本敏感性。"""
    import urllib.parse
    import urllib.request as _u
    from backend.strategy.report import build_report, bar_chart
    factor = str(request.args.get("factor") or "RET20")
    sign = float(request.args.get("sign") or 1)
    q = int_arg(request.args.get("quantiles"), 10, 5, 20)
    base = os.environ.get("SC_SELF_URL", "http://127.0.0.1:5000")
    url = (f"{base}/api/alpha/factor-analysis?factor={urllib.parse.quote(factor)}"
           f"&sign={sign}&quantiles={q}")
    try:
        with _u.urlopen(url, timeout=180) as resp:
            payload = json.load(resp)
        data = payload.get("data") or {}
    except Exception as e:
        return err(502, "analysis_failed", f"取因子分析失败：{e}", retriable=False)
    if data.get("error"):
        return err(400, "bad_factor", data["error"], retriable=False)
    groups = data.get("groups") or []
    ls = data.get("long_short") or {}
    labels = [f"Q{g.get('group')}" for g in groups]
    values = [float(g.get("ann") or 0) * 100 for g in groups]
    eq = (data.get("equity") or {}).get("long_short") or []
    trades = [{"date": f"Q{g.get('group')}", "code": f"{float(g.get('ann') or 0) * 100:+.1f}%",
               "name": f"夏普 {float(g.get('sharpe') or 0):+.2f}",
               "side": "", "qty": "", "price": "",
               "pnl": f"{float(g.get('maxdd') or 0) * 100:.1f}%",
               "pnl_pct": f"{float(g.get('win') or 0) * 100:.1f}%", "reason": ""} for g in groups]
    ic = data.get("ic_decay") or {}
    cost = data.get("cost_curve") or []
    body = build_report(
        title=f"因子分析：{'-' if sign < 0 else ''}{factor}",
        subtitle=(f"{data.get('meta', {}).get('codes')} 只 × {data.get('meta', {}).get('days')} 日 · "
                  f"{q} 分位 · 多空年化 {float(ls.get('ann') or 0) * 100:+.1f}%"
                  f"（夏普 {float(ls.get('sharpe') or 0):+.2f}，回撤 {float(ls.get('maxdd') or 0) * 100:.1f}%）"
                  f" · 单调性 {float(data.get('monotonicity') or 0):+.2f}"),
        series=[1.0] + list(eq) if eq else [1.0, 1.0],
        metrics={"days": float(data.get("meta", {}).get("days") or 0)},
        trades=trades,
        notes=("表列：分位组 / 年化 / 夏普 / 回撤% / 日胜率%。"
               "IC 衰减：" + " ".join(f"{h}日 {float(v.get('ic') or 0):+.4f}" for h, v in ic.items()) +
               "。成本/持有期：" + " ".join(
                   f"hold{int(c.get('hold') or 0)} 净{float(c.get('ann') or 0) * 100:+.1f}%（换手 {float(c.get('turnover') or 0):.2f}）"
                   for c in cost)))
    body = body.replace('<h2>净值曲线</h2>', '<h2>分位组年化收益</h2>' + bar_chart(labels, values)
                        + '<h2>多空净值（Q1−Q最高）</h2>')
    return _html(body, f"factor_{factor}.html")


@bp.route("/smb", methods=["GET"])
def smb_report():
    """规模因子（SMB）策略报告：小盘−大盘 + 最小 N 只月度策略 + 成本敏感性。"""
    import json as _json
    from backend.strategy.report import build_report
    path = os.path.join(str(DATA_DIR), "smb_result.json")
    if not os.path.exists(path):
        return err(404, "not_found", "尚未生成 SMB 报告（先运行 python -m backend.alpha.smb）",
                   retriable=False)
    with open(path, encoding="utf-8") as f:
        d = _json.load(f)
    st = d.get("strategy") or {}
    meta = d.get("meta") or {}
    smb = d.get("smb") or {}
    eq = [1.0] + [round(1.0 * x, 4) for x in (st.get("equity") or [])]
    months = (st.get("picks") or [])
    trades = [{"date": p.get("month"), "code": f"{p.get('next_ret', 0) * 100:+.1f}%",
               "name": "、".join(p.get("names") or [])[:40],
               "side": f"平均市值 {p.get('avg_mv_yi', 0)} 亿",
               "qty": "", "price": "", "pnl": "", "pnl_pct": "", "reason": ""}
              for p in months[-36:]]
    cost = d.get("cost_curve") or []
    variants = d.get("variants") or []
    dl = d.get("delay_one_day") or {}
    notes = (f"规则：{meta.get('rule', '')}；每月最后一个交易日按流通市值升序取最小的 {meta.get('top')} 只"
             f"（叠加 {meta.get('mom_key')} 权重 {meta.get('mom_weight')}），等权持有一个月。<br>"
             f"SMB（小盘 {meta.get('smb_group')} 只 − 大盘 {meta.get('smb_group')} 只）：月均 "
             f"{float(smb.get('mean_month') or 0) * 100:+.2f}%（年化 {float(smb.get('ann') or 0) * 100:+.1f}%，"
             f"t={float(smb.get('t_stat') or 0):+.2f}）。<br>"
             f"宽度对照：" + "、".join(f"Top{v.get('top')} {float(v.get('ann') or 0) * 100:+.1f}%" for v in variants) +
             f"。<br>成本敏感性：" + "、".join(
                 f"单边{float(c.get('cost_one_way') or 0) * 100:.1f}%→{float(c.get('ann') or 0) * 100:+.1f}%"
                 for c in cost) +
             f"。<br>延后一天成交（买下月首个交易日、卖下下月首个交易日）：年化 "
             f"{float(dl.get('ann') or 0) * 100:+.1f}%、回撤 {float(dl.get('maxdd') or 0) * 100:.1f}%。<br>"
             f"⚠️ 平均持仓流通市值仅 {sum(float(p.get('avg_mv_yi') or 0) for p in months) / max(1, len(months)):.1f} 亿元，"
             "实盘冲击成本与成交难度远高于常规股票；回测用月末收盘价、未建模涨跌停/停牌与冲击成本，"
             "结论应以成本敏感性表为准。")
    body = build_report(
        title="规模因子（SMB）月度策略报告",
        subtitle=(f"{meta.get('start')}~{meta.get('end')} · {meta.get('months')} 个月 · "
                  f"股票池 {meta.get('universe_codes')} 只 · 可选中位数 "
                  f"{float((d.get('mask_stats') or {}).get('avg_selectable') or 0) * 100:.0f}%"),
        series=eq, metrics={**st, "days": float(meta.get("months") or 0) * 20.3},
        trades=trades, notes=notes)
    return _html(body, "smb_report.html")


@bp.route("/allocation", methods=["GET"])
def allocation_report():
    """组合构建报告：单腿统计 + 相关矩阵 + 配比表 + 最优组合净值。"""
    from backend.alpha import allocation as AL
    from backend.strategy.report import build_report
    legs = str(request.args.get("legs") or "smb,etf:511010")
    specs = [x.strip() for x in legs.split(",") if x.strip()]
    window = int_arg(request.args.get("window"), 36, 12, 120)
    rolling = str(request.args.get("rolling") or "1") not in ("0", "false", "no")
    try:
        res = AL.build(specs, rolling=rolling, window=window)
    except Exception as e:
        return err(400, "bad_legs", str(e)[:200], retriable=False)
    legs_html = "".join(
        f"<tr><td>{l.get('spec')}</td><td>{l.get('label')}</td>"
        f"<td>{float(l.get('ann') or 0) * 100:+.1f}%</td><td>{float(l.get('vol') or 0) * 100:.1f}%</td>"
        f"<td>{float(l.get('sharpe') or 0):.2f}</td><td>{float(l.get('maxdd') or 0) * 100:.1f}%</td>"
        f"<td>{float(l.get('month_win') or 0) * 100:.1f}%</td></tr>" for l in res["legs"])
    mixes_html = "".join(
        f"<tr><td>{m.get('name') or '网格'}</td>"
        f"<td>{'/'.join(f'{x:.2f}' for x in (m.get('weights') or []))}</td>"
        f"<td>{float(m.get('ann') or 0) * 100:+.1f}%</td><td>{float(m.get('vol') or 0) * 100:.1f}%</td>"
        f"<td>{float(m.get('sharpe') or 0):.2f}</td><td>{float(m.get('maxdd') or 0) * 100:.1f}%</td>"
        f"<td>{float(m.get('month_win') or 0) * 100:.1f}%</td></tr>" for m in res["mixes"][-14:])
    best = res.get("best") or {}
    ros = res.get("rolling_os") or {}
    ros_html = ""
    if ros.get("methods"):
        rows = "".join(
            f"<tr><td>{m}</td><td>{'/'.join(f'{x:.2f}' for x in (st.get('weights_last') or []))}</td>"
            f"<td>{float(st.get('ann') or 0) * 100:+.1f}%</td><td>{float(st.get('vol') or 0) * 100:.1f}%</td>"
            f"<td>{float(st.get('sharpe') or 0):.2f}</td><td>{float(st.get('maxdd') or 0) * 100:.1f}%</td>"
            f"<td>{float(st.get('month_win') or 0) * 100:.1f}%</td></tr>"
            for m, st in ros["methods"].items())
        bench = ros.get("bench") or {}
        bleg = "；".join(f"{specs[int(k[4:])]} 夏普 {float(v.get('sharpe') or 0):.2f}"
                         for k, v in bench.items() if k.startswith("leg_"))
        ros_html = ("<h2>滚动样本外（每月只用过去 " + str(ros.get("window")) + " 个月估权重）</h2>"
                    "<table class='grid'><thead><tr><th>方法</th><th>最新权重</th><th>年化</th><th>波动</th>"
                    "<th>夏普</th><th>回撤</th><th>月胜率</th></tr></thead><tbody>" + rows + "</tbody></table>"
                    f"<p style='color:#a9aeb6;font-size:12px'>同期单腿对照：{bleg}"
                    f"（区间 {bench.get('from')}~{bench.get('to')}，比全样本短且更靠后）</p>")
    notes = ("<b>腿</b>：每条腿都是月末取值、每月再平衡；<br><b>相关矩阵</b>："
             + "；".join(f"{specs[i]}–{specs[j]} {res['corr'][i][j]:+.2f}"
                         for i in range(len(specs)) for j in range(i + 1, len(specs)))
             + f"<br><b>最优（按夏普）</b>：{'/'.join(f'{x:.2f}' for x in (best.get('weights') or []))} → "
               f"年化 {float(best.get('ann') or 0) * 100:+.1f}%、夏普 {float(best.get('sharpe') or 0):.2f}、"
               f"回撤 {float(best.get('maxdd') or 0) * 100:.1f}%"
             + "<br>注意：最优权重是**样本内**结果，按历史表现反推，实盘会衰减；"
               "逆波动/最小方差（不用预期收益）比最大夏普稳健。")
    body = build_report(
        title="组合构建报告", subtitle=f"{' + '.join(specs)}｜重合 {res['meta']['n_months']} 个月"
                                       f"（{res['meta']['start']}~{res['meta']['end']}）",
        series=[1.0] + list(res.get("best_equity") or [1.0]),
        dates=res.get("months"),          # 传月份标签：模板里的替换锚点才会存在
        metrics={}, notes=notes)
    body = body.replace('<h2>净值曲线</h2>', '<h2>最优组合净值（样本内）</h2>')
    body = body.replace('<h2>月度收益</h2>', '<h2>单腿统计</h2>'
                        '<table class="grid"><thead><tr><th>腿</th><th>说明</th><th>年化</th><th>波动</th>'
                        '<th>夏普</th><th>回撤</th><th>月胜率</th></tr></thead><tbody>'
                        + legs_html + '</tbody></table><h2>配比对比（样本内）</h2>'
                        '<table class="grid"><thead><tr><th>方案</th><th>权重</th><th>年化</th><th>波动</th>'
                        '<th>夏普</th><th>回撤</th><th>月胜率</th></tr></thead><tbody>'
                        + mixes_html + '</tbody></table>' + ros_html)
    return _html(body, "allocation_report.html")


@bp.route("/backtest", methods=["POST"])
def backtest_report():
    """通用报告：前端把回测结果 POST 上来，直接返回可打开的 HTML。"""
    from backend.strategy.report import build_report
    body = request.get_json(force=True, silent=True) or {}
    series = body.get("equity") or body.get("returns") or body.get("series")
    if not series:
        return err(400, "bad_request", "缺少 equity / returns 序列", retriable=False)
    html_body = build_report(
        title=str(body.get("title") or "回测报告"),
        subtitle=str(body.get("subtitle") or ""),
        series=series, dates=body.get("dates"), metrics=body.get("metrics") or {},
        trades=body.get("trades"), notes=body.get("notes"))
    return _html(html_body, "backtest_report.html")
