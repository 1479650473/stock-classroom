# -*- coding: utf-8 -*-
"""实盘策略（pali）决策源 —— 把 stock-ml 的策略产出暴露给软件。

## 为什么要这一层
软件里原本的「选股」是 `compute_factor_picks()` **全市场扫描**，那套东西与**实盘无关**。
董事长 2026-10-17 定调：*"现在开发软件要尽量为策略服务"* ——
所以软件的选股模块应当**展示实盘策略（pali）真正的决策结果**，而不是另跑一套。

## 数据来源（全部只读，不改策略侧任何文件）
| 文件 | 内容 |
| --- | --- |
| `output/sim/decision_<date>.csv` | 每日决策：`code, pred, ff20, ff_ok, rank` |
| `output/risk_check_<date>_<hhmm>.json` | 排雷结果：`level` = PASS / CAUTION / REJECT，附 `flags` / `reds` / `yels` |
| `data/test_pool100/pool_meta.json` | 100 池的 `code -> name / industry` |
| `output/sim/AUTO_LOG.md` | 人工可读的执行日志（原样透传摘要） |

## 纪律
1. **只读**：绝不写策略侧目录。
2. **不猜**：文件缺失/为空时如实返回 `available: false` 与原因，**不编造候选**。
3. **口径一致**：`pred` 一律取自 decision CSV 原值，软件侧**不做任何加工/换算**。
4. **如实标注风险**：排雷的 `REJECT` 必须在展示层可见 ——
   否则用户会看到一个"策略看好但实际不能买"的标的（如 688521 科创板无权限）。
"""
from __future__ import annotations

import csv
import glob
import json
import os
import re

# ── 路径解析（照 trade_bridge 的自检风格，不靠心算层数）────────────────
_HERE = os.path.dirname(os.path.abspath(__file__))          # backend/api
ROOT = os.path.dirname(os.path.dirname(_HERE))               # stock-classroom
if not os.path.isdir(os.path.join(ROOT, 'backend')):
    _alt = os.path.dirname(ROOT)
    if os.path.isdir(os.path.join(_alt, 'backend')):
        ROOT = _alt

# 与 classroom 同级：<projects>/stock-ml
DEFAULT_SM_DIR = os.path.join(os.path.dirname(ROOT), 'stock-ml')
SM_DIR = os.environ.get('SC_STOCKML_DIR') or DEFAULT_SM_DIR


def linglai_dir() -> str:
    return os.path.join(SM_DIR, 'project', 'linglai')


def output_dir() -> str:
    return os.path.join(linglai_dir(), 'output')


def pool_path() -> str:
    return os.path.join(SM_DIR, 'data', 'test_pool100', 'pool_meta.json')


def _read_json(path: str):
    try:
        with open(path, 'r', encoding='utf-8-sig') as f:
            return json.load(f)
    except Exception:
        return None


# ── 100 池：code -> {name, industry} ───────────────────────────────────
_pool_cache: dict | None = None


def load_pool() -> dict:
    """读 100 池元数据。失败返回空 dict（调用方按"无名称"降级展示）。"""
    global _pool_cache
    if _pool_cache is not None:
        return _pool_cache
    j = _read_json(pool_path())
    out: dict = {}
    if isinstance(j, dict) and isinstance(j.get('pool'), list):
        for it in j['pool']:
            c = str(it.get('code') or '').strip()
            if c:
                out[c] = {'name': it.get('name') or '', 'industry': it.get('industry') or ''}
    _pool_cache = out
    return out


# ── 决策 CSV ───────────────────────────────────────────────────────────

def list_decisions(limit: int = 30) -> list[str]:
    """列出可用的决策日期（降序）。文件名形如 decision_20261015.csv。"""
    pat = os.path.join(output_dir(), 'sim', 'decision_*.csv')
    out = []
    for p in glob.glob(pat):
        m = re.search(r'decision_(\d{8})\.csv$', os.path.basename(p))
        if m:
            out.append(m.group(1))
    return sorted(out, reverse=True)[:limit]


def load_decision(date8: str | None = None) -> dict:
    """读某日决策。date8 为空则取最新。

    返回：
      { available, date, source, items: [{code,name,industry,pred,ff20,ff_ok,rank}], reason }
    """
    dates = list_decisions(1)
    d = date8 or (dates[0] if dates else None)
    if not d:
        return {'available': False, 'date': None, 'items': [],
                'reason': f'未找到任何 decision_*.csv（期望目录 {os.path.join(output_dir(), "sim")}）'}

    path = os.path.join(output_dir(), 'sim', f'decision_{d}.csv')
    if not os.path.isfile(path):
        return {'available': False, 'date': d, 'items': [], 'reason': f'文件不存在: {path}'}

    pool = load_pool()
    items = []
    try:
        with open(path, 'r', encoding='utf-8-sig', newline='') as f:
            for row in csv.DictReader(f):
                code = str(row.get('code') or '').strip()
                if not code:
                    continue
                meta = pool.get(code, {})

                def _f(k):
                    v = row.get(k)
                    try:
                        return float(v) if v not in (None, '') else None
                    except (TypeError, ValueError):
                        return None

                ff_ok_raw = str(row.get('ff_ok') or '').strip().lower()
                items.append({
                    'code': code,
                    'name': meta.get('name') or '',
                    'industry': meta.get('industry') or '',
                    'pred': _f('pred'),
                    'ff20': _f('ff20'),
                    'ff_ok': ff_ok_raw in ('true', '1', 'yes'),
                    'rank': _f('rank'),
                })
    except Exception as e:
        return {'available': False, 'date': d, 'items': [], 'reason': f'解析失败: {type(e).__name__}: {e}'}

    items.sort(key=lambda x: (x['rank'] is None, x['rank'] or 0))
    return {
        'available': True, 'date': d, 'items': items,
        'source': os.path.relpath(path, SM_DIR).replace('\\', '/'),
        'total': len(items),
    }


# ── 排雷（risk_check） ─────────────────────────────────────────────────

def latest_risk_check() -> dict:
    """取最新一份排雷结果。

    返回 { available, ts, file, by_code: {code: {level, flags, reds, yels, ann_total, fin}}, reason }
    """
    files = glob.glob(os.path.join(output_dir(), 'risk_check_*.json'))
    if not files:
        return {'available': False, 'by_code': {},
                'reason': f'未找到 risk_check_*.json（期望目录 {output_dir()}）'}
    path = max(files, key=os.path.getmtime)
    j = _read_json(path)
    if not isinstance(j, list):
        return {'available': False, 'by_code': {}, 'reason': f'内容不是数组: {os.path.basename(path)}'}

    by_code = {}
    for it in j:
        c = str(it.get('code') or '').strip()
        if c:
            by_code[c] = {
                'level': it.get('level') or 'UNKNOWN',
                'flags': it.get('flags') or [],
                'reds': it.get('reds') or [],
                'yels': it.get('yels') or [],
                'ann_total': it.get('ann_total'),
                'fin': it.get('fin'),
                'name': it.get('name') or '',
            }
    m = re.search(r'risk_check_(\d{8})_(\d{4})\.json$', os.path.basename(path))
    ts = f'{m.group(1)} {m.group(2)[:2]}:{m.group(2)[2:]}' if m else None
    return {'available': True, 'ts': ts, 'file': os.path.basename(path), 'by_code': by_code}


# 排雷深度：pali 用 `risk_check.py --from-decision --top N`，默认 N=15。
# ⚠️ 不要用"已检查记录里的最大 rank"反推深度：若一次运行只成功返回 1 条，
#    会把深度算成 1，导致其余 14 条本该"未知"的显示成"未排雷"。
#    这里用**显式配置**（与 pali 的 --top 默认值一致），并允许环境变量覆盖。
try:
    RISK_TOP_N = int(os.environ.get('SC_RISK_TOP_N') or 15)
except ValueError:
    RISK_TOP_N = 15


# ── 战略硬约束（写在这里，避免散落）──────────────────────────────────
# 来自 AUTO_LOG 头部：「单笔≤4000元 | 每日≤1买1卖 | 只主板 | 只买PASS | 不融资融券」
def is_main_board(code: str) -> bool:
    """是否主板。主板 = 沪 600/601/603/605、深 000/001/002/003。

    科创板(688/689)、创业板(300/301)、北交所(8xx/4xx) 都**不是**主板 ——
    实测 688521 芯原股份 曾因"账户无权限"实际不可买，故必须在界面上标出来。
    """
    c = str(code or '').strip()
    if len(c) != 6 or not c.isdigit():
        return False
    return c[:3] in ('600', '601', '603', '605', '000', '001', '002', '003')


class Board:
    MAIN = 'main'
    STAR = 'star'      # 科创板
    GEM = 'gem'        # 创业板
    BSE = 'bse'        # 北交所
    OTHER = 'other'


def board_of(code: str) -> str:
    c = str(code or '').strip()
    if len(c) != 6 or not c.isdigit():
        return Board.OTHER
    p = c[:3]
    if p in ('600', '601', '603', '605', '000', '001', '002', '003'):
        return Board.MAIN
    if p in ('688', '689'):
        return Board.STAR
    if p in ('300', '301'):
        return Board.GEM
    if c[0] in ('4', '8'):
        return Board.BSE
    return Board.OTHER


BOARD_CN = {Board.MAIN: '主板', Board.STAR: '科创板', Board.GEM: '创业板',
            Board.BSE: '北交所', Board.OTHER: '其它'}


# ── 策略执行摘要（AUTO_LOG.md，人工可读，只把结论段摘出来）─────────────

def strategy_summary(max_lines: int = 40) -> dict:
    """从 AUTO_LOG.md 摘出"最近一个交易日"的要点段（只读、不改写）。

    目的：让界面能回答"策略今天到底做了什么决定"，而不只是列一堆候选。
    找不到就如实返回 available=False，不编造。
    """
    path = os.path.join(output_dir(), 'sim', 'AUTO_LOG.md')
    if not os.path.isfile(path):
        return {'available': False, 'reason': f'未找到 AUTO_LOG.md（{path}）'}
    try:
        with open(path, 'r', encoding='utf-8') as f:
            lines = f.read().splitlines()
    except Exception as e:
        return {'available': False, 'reason': f'读取失败: {type(e).__name__}'}

    # 找最近的 "## YYYY-MM-DD" 段
    heads = [i for i, l in enumerate(lines) if re.match(r'^##\s+\d{4}-\d{2}-\d{2}', l)]
    if not heads:
        return {'available': False, 'reason': '未找到日期章节'}
    start = heads[-1]
    title = lines[start].lstrip('# ').strip()
    body = [l for l in lines[start + 1:] if not re.match(r'^##\s', l)]
    picked = [l for l in body if l.strip().startswith('-')][:max_lines]
    return {'available': True, 'date': title, 'lines': picked}


POSITION_FILE = 'pali_position.json'


def load_position() -> dict | None:
    """读 pali 当前持仓。

    ## 为什么从 AUTO_LOG 解析而不是读某个 JSON
    策略侧**没有**持仓 JSON —— 持仓的事实记录在 `output/sim/AUTO_LOG.md` 的
    「持仓/资金」行里（人工可读）。`live.db` 只有 `kline_sim/update_log/signals`，无持仓表。
    所以这里解析 AUTO_LOG 中**最后一次出现**的持仓行，并如实标注来源。

    优先仍读可选约定文件 `pali_position.json`（策略侧若将来写了就用它，更结构化）。

    返回 { code, qty, source, raw } 或 None（**读不到就返回 None，绝不猜**）。
    """
    j = _read_json(os.path.join(output_dir(), POSITION_FILE))
    if isinstance(j, dict) and j.get('code'):
        return {**j, 'source': POSITION_FILE}

    path = os.path.join(output_dir(), 'sim', 'AUTO_LOG.md')
    if not os.path.isfile(path):
        return None
    try:
        with open(path, 'r', encoding='utf-8') as f:
            lines = f.read().splitlines()
    except Exception:
        return None

    # 从后往前找第一条能解析出「持仓 <代码> <名称> <数量> 股」的行
    # 实测样例：- 持仓/资金：… 持仓 002659×700、可用 262.54（沿用晨间核对值）
    #           - 持仓：002659 凯文教育 700 股 | 成本 4.6775 | 收盘 4.79 …
    pat_a = re.compile(r'持仓\s*(\d{6})\s*[×x*]\s*([\d,]+)')
    pat_b = re.compile(r'持仓[：:]\s*(\d{6})\s+(\S+)\s+([\d,]+)\s*股')
    for line in reversed(lines):
        m = pat_b.search(line)
        if m:
            return {'code': m.group(1), 'name': m.group(2),
                    'qty': int(m.group(3).replace(',', '')),
                    'source': 'AUTO_LOG.md', 'raw': line.strip()}
        m = pat_a.search(line)
        if m:
            return {'code': m.group(1), 'qty': int(m.group(2).replace(',', '')),
                    'source': 'AUTO_LOG.md', 'raw': line.strip()}
        if '空仓' in line and '持仓' in line:
            return {'code': None, 'qty': 0, 'source': 'AUTO_LOG.md', 'raw': line.strip()}
    return None


# ── 组装给前端的一份完整视图 ───────────────────────────────────────────

def strategy_picks(date8: str | None = None) -> dict:
    """把「决策 + 排雷 + 持仓上下文」合成一份前端可直接渲染的数据。

    关键：**每条候选都带上排雷结论**，并给出 `buyable` ——
    否则用户会看到"策略 Rank1 看好、但实际不可买"的标的（如科创板无权限、REJECT）。
    """
    dec = load_decision(date8)
    risk = latest_risk_check()
    pos = load_position()

    if not dec.get('available'):
        return {
            'available': False,
            'reason': dec.get('reason'),
            'date': dec.get('date'),
            'risk': {'available': risk.get('available'), 'ts': risk.get('ts'), 'reason': risk.get('reason')},
            'items': [],
            'position': pos,
        }

    by_code = risk.get('by_code') or {}
    items = []
    for it in dec['items']:
        r = by_code.get(it['code'])
        # ⚠️ 关键语义区分（这里踩过一次）：
        #   排雷只跑 TopN（实测 --from-decision --top 15），**不是全 100 池**。
        #   所以对未覆盖的标的：
        #     · 若在"被排雷深度"之内 → 真的没记录 = UNKNOWN（异常，值得注意）
        #     · 若在深度之外       → **未排雷**（正常，程序根本没跑它）
        #   把两者都写成 UNKNOWN 会让 100 条里 97 条显示"未知"，既噪音又误导。
        level = (r or {}).get('level')
        bb = board_of(it['code'])
        item = {
            **it,
            'board': bb,
            'board_cn': BOARD_CN[bb],
            'is_main_board': bb == Board.MAIN,
            'risk_level': level or None,
            'risk_flags': (r or {}).get('flags') or [],
            'risk_reds': (r or {}).get('reds') or [],
            'risk_yels': (r or {}).get('yels') or [],
            'ann_total': (r or {}).get('ann_total'),
        }
        items.append(item)

    # 被排雷的深度：pali 的 `--from-decision --top N`，用显式配置（见 RISK_TOP_N）
    depth = RISK_TOP_N

    for it in items:
        ranked_in_depth = isinstance(it.get('rank'), (int, float)) and it['rank'] <= depth
        if not it['risk_level']:
            it['risk_level'] = 'UNKNOWN' if ranked_in_depth else 'NOT_CHECKED'
            it['risk_level_cn'] = '未知（该查却没记录）' if ranked_in_depth else '未排雷'
        else:
            it['risk_level_cn'] = {'PASS': '通过', 'CAUTION': '警示', 'REJECT': '否决'}.get(it['risk_level'], it['risk_level'])
        # 策略硬约束：只主板 + 只买 PASS（其它一律不可买）
        reasons = []
        if it['risk_level'] != 'PASS':
            reasons.append(it['risk_level_cn'])
        if not it['is_main_board']:
            reasons.append(f"非主板（{it['board_cn']}）")
        it['blocked_by'] = reasons
        it['buyable'] = not reasons

    # 持仓的池内排名（用同一份决策即可得出，无需再查库）
    position_ctx = None
    if pos:
        code = pos.get('code')
        if code:
            hit = next((x for x in items if x['code'] == code), None)
            position_ctx = {
                **pos,
                'name': pos.get('name') or ((hit or {}).get('name') or ''),
                'rank': (hit or {}).get('rank'),
                'pred': (hit or {}).get('pred'),
                # 策略卖出条件：跌出 Top20%（rank > 20）或 FF 转好
                'in_top20': (isinstance((hit or {}).get('rank'), (int, float))
                             and (hit or {})['rank'] <= max(1, int(len(items) * 0.2))),
            }
        else:
            position_ctx = {**pos, 'rank': None, 'pred': None, 'in_top20': None}

    return {
        'available': True,
        'date': dec['date'],
        'source': dec.get('source'),
        'total': dec.get('total'),
        'risk': {'available': risk.get('available'), 'ts': risk.get('ts'),
                 'reason': risk.get('reason'), 'checked': len(by_code), 'depth': depth},
        'items': items,
        'buyable_count': sum(1 for x in items if x['buyable']),
        'position': position_ctx,
        'summary': strategy_summary(),
    }
