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


def pool_from_decision_script() -> str | None:
    """读策略脚本里**声明的**池路径 —— 这是权威来源，优先级仅次于环境变量。

    ## 为什么必须这么做（踩坑记录）
    `data/` 下有 9 个 `test_pool100*` 变体（v2/v3/v4/fix/fix2…），
    **它们包含的 100 只代码完全相同**，只有特征/数据版本不同。
    所以"按代码匹配"会全部并列 100/100，退化成谁新选谁 ——
    实测就挑错了 `test_pool100_v4fix2`，而策略用的是 `test_pool100`。

    → 正确做法：**读 `daily_decision.py` 里 `POOL = os.path.join(ROOT, 'data', ...)` 的声明**。
      这是策略自己在说"我用哪个池"，比任何启发式都可靠。
      解析失败就返回 None（调用方退回代码匹配），**不猜**。

    只读脚本文本，不 import、不执行 —— 不触碰策略侧任何东西。
    """
    script = os.path.join(linglai_dir(), 'scripts', 'daily_decision.py')
    if not os.path.isfile(script):
        return None
    try:
        with open(script, 'r', encoding='utf-8') as f:
            src = f.read()
    except Exception:
        return None

    # 形如：POOL = os.path.join(ROOT, 'data', 'test_pool100', 'pool_meta.json')
    m = re.search(
        r"POOL\s*=\s*os\.path\.join\(\s*ROOT\s*,\s*['\"]data['\"]\s*,\s*['\"]([^'\"]+)['\"]\s*,\s*['\"]pool_meta\.json['\"]\s*\)",
        src,
    )
    if not m:
        return None
    p = os.path.join(SM_DIR, 'data', m.group(1), 'pool_meta.json')
    return p if os.path.isfile(p) else None


def list_pool_candidates() -> list[dict]:
    """列出所有候选池及各自规模（仅供诊断/UI 显示，不用于猜测）。"""
    data_dir = os.path.join(SM_DIR, 'data')
    out = []
    if not os.path.isdir(data_dir):
        return out
    cands = glob.glob(os.path.join(data_dir, 'test_pool*', 'pool_meta.json'))
    if not cands:
        cands = glob.glob(os.path.join(data_dir, '*', 'pool_meta.json'))
    for p in sorted(set(cands)):
        j = _read_json(p)
        codes = set()
        if isinstance(j, dict) and isinstance(j.get('pool'), list):
            codes = {str(it.get('code') or '').strip() for it in j['pool']}
            codes.discard('')
        out.append({
            'path': p,
            'name': os.path.basename(os.path.dirname(p)),
            'size': len(codes),
            'mtime': os.path.getmtime(p) if os.path.isfile(p) else 0,
        })
    return out


def pool_path(codes: set[str] | None = None) -> str | None:
    """定位策略池的 pool_meta.json —— **池无关**，且**以策略实际使用的为准**。

    董事长 2026-10-17：「我下一步会做**扩池**」，所以不能写死 `test_pool100`、不能假设规模 100。

    ## ⚠️ 这里踩过一个坑（必须记下来）
    第一版做法是"取池最大、并列取最新" —— 结果挑中了 `test_pool100_v4fix2`，
    而策略实际用的是 `test_pool100`（`daily_decision.py` 里写死的）。
    **"猜一个更新/更大的池"会静默用错池**，名称/行业全部对不上，且很难发现。

    ## 现在的做法：**用决策结果反查匹配（自校验）**
    传入 `codes`（来自 decision CSV 的实际打分代码），选**代码交集最大**的池。
    这样"策略用哪个池"由策略自己的产出来证明，而不是靠猜：
      · 扩池后新池自然包含新代码 → 自动匹配到新池，软件零改动
      · 匹配度过低说明池文件与决策不一致 → 由 `pool_info.matched` 暴露给界面

    查找顺序（**权威优先，猜测垫底**）：
      1. 环境变量 `SC_STRATEGY_POOL` —— 显式指定，最高优先级
      2. **策略脚本 `daily_decision.py` 里声明的 POOL** —— 权威来源（见下方踩坑记录）
      3. 按 `codes` 交集最大挑选（并列时偏好更大池）
      4. 无 `codes` 时：池最大 → 最新（仅兜底，调用方应视为"推断"）

    ## ⚠️ 这里踩过一个坑（必须记下来）
    第一版做法是"取池最大、并列取最新" —— 挑中了 `test_pool100_v4fix2`，
    而策略实际用的是 `test_pool100`（`daily_decision.py` 里写死的）。
    **9 个 `test_pool100*` 变体的 100 只代码完全相同**，所以"按代码匹配"也全并列，
    仍会退化成谁新选谁 → **仍然选错**。
    最终解法：**读策略脚本里的声明**（`pool_from_decision_script()`），那是策略自己说的。
    """
    explicit = os.environ.get('SC_STRATEGY_POOL')
    if explicit and os.path.isfile(explicit):
        return explicit

    # 权威：策略脚本声明的池
    declared = pool_from_decision_script()
    if declared:
        return declared

    cands = [c for c in list_pool_candidates() if os.path.isfile(c['path'])]
    if not cands:
        return None

    if codes:
        def _overlap(c: dict) -> tuple[int, int, float]:
            j = _read_json(c['path'])
            pset = set()
            if isinstance(j, dict) and isinstance(j.get('pool'), list):
                pset = {str(it.get('code') or '').strip() for it in j['pool']}
            return (len(pset & codes), c['size'], c['mtime'])
        return max(cands, key=_overlap)['path']

    return max(cands, key=lambda c: (c['size'], c['mtime']))['path']


def _read_json(path: str):
    try:
        with open(path, 'r', encoding='utf-8-sig') as f:
            return json.load(f)
    except Exception:
        return None


# ── 策略池：code -> {name, industry} ───────────────────────────────────
# 缓存按「池文件路径」建键 —— 池的选择依赖决策代码（自校验），
# 不同日期/不同池之间不能共用一份缓存。
_pool_cache: dict[str, dict] = {}


def load_pool(codes: set[str] | None = None) -> dict:
    """读策略池元数据（code -> {name, industry}）。**池无关**：路径由 pool_path(codes) 决定。

    失败返回空 dict（调用方按"无名称"降级展示，绝不编造名称）。
    """
    p = pool_path(codes)
    if not p:
        return {}
    if p in _pool_cache:
        return _pool_cache[p]
    j = _read_json(p)
    out: dict = {}
    if isinstance(j, dict) and isinstance(j.get('pool'), list):
        for it in j['pool']:
            c = str(it.get('code') or '').strip()
            if c:
                out[c] = {'name': it.get('name') or '', 'industry': it.get('industry') or ''}
    _pool_cache[p] = out
    return out


def pool_info(codes: set[str] | None = None) -> dict:
    """池的元信息，供界面显示"池有多大、叫什么、匹配度如何"。

    扩池后 `size` 会自动变化 —— 前端**不要写死 100**。
    `matched` = 池与决策代码的交集数，用于暴露"池文件与决策不一致"。
    """
    pool = load_pool(codes)
    p = pool_path(codes)
    j = _read_json(p) if p else None
    meta = {}
    if isinstance(j, dict):
        for k in ('total_samples', 'n_sectors', 'test_start'):
            if k in j:
                meta[k] = j[k]
    pset = set(pool.keys())
    return {
        'path': p,
        'name': os.path.basename(os.path.dirname(p)) if p else None,
        'size': len(pset),
        'meta': meta,
        # 自校验：决策里有多少只能在这个池里找到（< size 说明可能选错了池）
        'matched': (len(pset & codes) if codes else None),
        'candidates': list_pool_candidates(),
    }


def recount_pool() -> None:
    """清池缓存（扩池后若策略侧换了 pool_meta.json，重载时用）。"""
    _pool_cache.clear()


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

    # 两遍：先解析 CSV 拿到真实代码集合，再用它**自校验**出正确的池
    # （池路径依赖决策代码，不能先猜池、再解析决策 —— 那样会静默用错池）
    raw = []
    try:
        with open(path, 'r', encoding='utf-8-sig', newline='') as f:
            for row in csv.DictReader(f):
                code = str(row.get('code') or '').strip()
                if not code:
                    continue

                def _f(k):
                    v = row.get(k)
                    try:
                        return float(v) if v not in (None, '') else None
                    except (TypeError, ValueError):
                        return None

                ff_ok_raw = str(row.get('ff_ok') or '').strip().lower()
                raw.append({
                    'code': code,
                    'pred': _f('pred'),
                    'ff20': _f('ff20'),
                    'ff_ok': ff_ok_raw in ('true', '1', 'yes'),
                    'rank': _f('rank'),
                })
    except Exception as e:
        return {'available': False, 'date': d, 'items': [], 'reason': f'解析失败: {type(e).__name__}: {e}'}

    codes = {r['code'] for r in raw}
    pool = load_pool(codes)
    items = [{
        **r,
        'name': (pool.get(r['code']) or {}).get('name') or '',
        'industry': (pool.get(r['code']) or {}).get('industry') or '',
    } for r in raw]

    items.sort(key=lambda x: (x['rank'] is None, x['rank'] or 0))
    return {
        'available': True, 'date': d, 'items': items,
        'source': os.path.relpath(path, SM_DIR).replace('\\', '/'),
        'total': len(items),
        'codes': codes,
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


# ── 账户读数（AUTO_LOG，人工核对过的干净文本）────────────────────────────

def log_section_dates() -> list[str]:
    """AUTO_LOG.md 里所有日期的章节（**文件顺序，新→旧**）。"""
    path = os.path.join(output_dir(), 'sim', 'AUTO_LOG.md')
    if not os.path.isfile(path):
        return []
    try:
        with open(path, 'r', encoding='utf-8') as f:
            src = f.read()
    except Exception:
        return []
    return re.findall(r'^##\s+(\d{4}-\d{2}-\d{2})', src, flags=re.M)


def account_estimate(upto: str | None = None) -> dict:
    """从 AUTO_LOG.md 解析**账户读数**（持仓/可用资金/总资产/市值/浮盈/当日盈亏）。

    ## 为什么这里可以解析，而快照的 OCR 文本不行
    AUTO_LOG 是**人工核对后写的**结构化文本，字段带明确标签、数字干净：
      · `资金：可用 262.54（vs 昨日 262.34）| 持仓 002659×700 @4.6772 现价 4.80 市值 3367 浮盈 +92.97`
      · `持仓：700 股 @成本 4.6775 | 可用 262.34 | 市值 3248`
      · `当日盈亏：… | 市值 3339 | 持仓浮盈 +64.75 | 总资产 ≈3601.5`

    而快照里的 `positions_text` 是**屏幕 OCR 原文**（`証 券 代 码 L` 逐字空格、`訕里` 错字、
    全角句点连写），解析必然出错 —— 在交易软件里**输出错数字比不输出更危险**，故弃用 OCR 解析。

    ## 做法
    文件是**新→旧**排列（`## 2026-10-16` 在最前），所以**按章节解析、优先取最新**。
    ⚠️ 踩过的坑：第一版用 `reversed(lines)` 从后往前扫，结果从**最旧**的章节开始，
    解出了 10-13 的数据却当成最新 —— **方向错了，数字就错**。
    现在：把文件切成 {日期: [行]}，按文件顺序（新→旧）逐章节解析，
    取**第一个字段足够完整**的章节。
    解析不到的字段**留 None，绝不臆造**。

    ## 参数
    `upto`：只考虑该日期及更早的章节（YYYY-MM-DD）。
    用于 `account_history()` 逐日回放 —— **同一段解析逻辑，不重复实现**。
    """
    path = os.path.join(output_dir(), 'sim', 'AUTO_LOG.md')
    if not os.path.isfile(path):
        return {'available': False, 'reason': f'未找到 AUTO_LOG.md（{path}）'}
    try:
        with open(path, 'r', encoding='utf-8') as f:
            lines = f.read().splitlines()
    except Exception as e:
        return {'available': False, 'reason': f'读取失败: {type(e).__name__}'}

    # 切章节：保持文件顺序（新 → 旧）
    sections: list[tuple[str | None, list[str]]] = []
    cur_date: str | None = None
    cur_lines: list[str] = []
    for ln in lines:
        m = re.match(r'^##\s+(\d{4}-\d{2}-\d{2})', ln)
        if m:
            if cur_lines or cur_date:
                sections.append((cur_date, cur_lines))
            cur_date, cur_lines = m.group(1), []
            continue
        if re.match(r'^##\s', ln):      # 非日期章节（如「日志规范」）→ 结束当前
            sections.append((cur_date, cur_lines))
            cur_date, cur_lines = None, []
            continue
        cur_lines.append(ln)
    if cur_lines or cur_date:
        sections.append((cur_date, cur_lines))

    P = {
        # 注意：这里的键名用 `cash` 表示「可用资金」，**不能叫 available** ——
        # 外层还有个布尔 `available`（本条读数是否解析成功），两者同名会互相覆盖
        # （踩过：布尔 True 把 262.54 覆盖成了 1，自洽校验直接炸）。
        'cash': re.compile(r'可用[资金]*\s*([\d,]+\.?\d*)'),
        'total_assets': re.compile(r'总资产\s*[≈~]?\s*([\d,]+\.?\d*)'),
        'market_value': re.compile(r'市值\s*([\d,]+\.?\d*)'),
        'float_pnl': re.compile(r'浮盈\s*([-−+]?[\d,]+\.?\d*)'),
        'price': re.compile(r'现价\s*([\d.]+)'),
        'code_qty': re.compile(r'(\d{6})\s*[×xX*]\s*([\d,]+)'),
        'qty_only': re.compile(r'持仓[：:]\s*([\d,]+)\s*股'),
        'assets_only': re.compile(r'(?<!总)资产\s*([\d,]+\.?\d*)'),
        # 「（当日 +7）」这种写法。注意 `当日盈亏：002659` 里「当日」后接「盈亏」不是数字，不会误匹配
        'day_pnl': re.compile(r'当日\s*([+-]?[\d,]+\.?\d*)\s*[)）]'),
        # 「账户 3510.54」（周报基线写法）
        'account_total': re.compile(r'账户\s*([\d,]+\.?\d*)'),
        'cost_hold': re.compile(r'@\s*(?:成本\s*)?([\d.]+)'),
        'stale': re.compile(r'沿用.*核对值'),
    }

    def _num(s: str) -> float | None:
        try:
            # 归一：去掉 markdown 粗体星号与千分位；全角/Unicode 负号 → ASCII '-'
            t = str(s).replace('*', '').replace(',', '').replace('−', '-').replace('－', '-')
            return float(t)
        except (TypeError, ValueError):
            return None

    def _clean(line: str) -> str:
        """把 AUTO_LOG 的行归一成便于正则的形态。

        AUTO_LOG 里到处是 markdown 格式：`总资产 ≈**3510.5**`、`持仓浮盈 **−26.25**`。
        星号会把数字和标签隔开，导致 `总资产\\s*[≈~]?\\s*(\\d+)` 匹配不到
        （踩过：收盘那行整条解析失败，`close` 返回 null）。
        所以先去掉 `*`、把 Unicode 负号换成 ASCII `-`。
        """
        return line.replace('*', '').replace('−', '-').replace('－', '-')

    def parse_section(date: str | None, body: list[str]) -> dict:
        """解析一个交易日的账户状态，**以"最新一处提到"为准**。

        ## ⚠️ 这里推翻了前两版的设计（两次都是因为"选取依据"错了）

        **第一版**：逐字段填充（缺哪个补哪个）→ 把同一天不同时点的数字混在一起
        （`市值 3248` 收盘配 `总资产 3566.54` 盘前，差 262.54），数字不自洽。
        当时的结论是"不能跨行拼"，改成了——

        **第二版**：**一行 = 一条完整读数**，挑"字段最多"的那行。
        结果挑中了 09:35 的盘中核对行（6 个字段），
        于是界面显示 `浮盈 +29.97 / 市值 3304` ——
        **但当天收盘实际是 `浮盈 −26.25 / 市值 3248`**（董事长一眼看出不对）。
        教训：**账户总览要的是"最新状态"，不是"字段最全的那条"**。

        **这一版**：**每个字段取当天最后一次出现的值**（从后往前扫，先到先得）。
        各字段各自来自"它最近一次被记录的那一行"，并且**记录 provenance**。
        跨行是必要的（收盘行常缺「可用」，周报行常缺「市值」），
        但只要每项都取"最新一次记录"，拼出来就是**当前真实状态**，
        而且能用恒等式验证（实测拼出来仍完全自洽）。
        """
        cands = []
        for idx, raw_ln in enumerate(x.strip() for x in body):
            if not raw_ln.startswith('-'):
                continue
            s = _clean(raw_ln)      # 去 markdown 星号 / Unicode 负号
            c = {'idx': idx, 'code': None, 'qty': None, 'cost': None, 'price': None,
                 'market_value': None, 'float_pnl': None, 'day_pnl': None,
                 'cash': None, 'total_assets': None, 'raw': raw_ln[:200],
                 'carried_over': bool(P['stale'].search(s))}

            m = P['code_qty'].search(s)
            if m:
                c['code'], c['qty'] = m.group(1), _num(m.group(2))
            if c['qty'] is None:
                m = P['qty_only'].search(s)
                if m:
                    c['qty'] = _num(m.group(1))
            # 成本只从「持仓」行取，别拿成交行的「买入 700@4.67」当成本
            if '持仓' in s:
                m = P['cost_hold'].search(s)
                if m:
                    c['cost'] = _num(m.group(1))
            for key in ('cash', 'total_assets', 'market_value', 'float_pnl',
                        'price', 'day_pnl'):
                m = P[key].search(s)
                if m:
                    c[key] = _num(m.group(1))
            if c['total_assets'] is None:
                m = P['assets_only'].search(s)
                if m:
                    c['total_assets'] = _num(m.group(1))
            # 「账户 3510.54」这种周报基线写法
            if c['total_assets'] is None:
                m = P['account_total'].search(s)
                if m:
                    c['total_assets'] = _num(m.group(1))

            c['n_fields'] = sum(1 for k in ('code', 'qty', 'cash', 'total_assets',
                                            'market_value', 'price')
                                if c[k] is not None)
            cands.append(c)

        if not cands:
            return {'as_of': date, 'available': False, 'raw': []}

        # ── 主读数：每个字段取「当天最后一次出现」 ──
        latest: dict = {}
        src: dict = {}
        FIELDS = ('code', 'qty', 'cost', 'cash', 'total_assets',
                  'market_value', 'float_pnl', 'day_pnl')
        for c in reversed(cands):           # 从最晚的行开始
            for k in FIELDS:
                if latest.get(k) is None and c.get(k) is not None:
                    latest[k] = c[k]
                    src[k] = c['idx']

        # 现价必须与「市值」来自**同一行** —— 否则会出现"盘中价 4.72 配收盘市值 3248"
        # 这种自相矛盾的组合（踩过：界面显示现价 4.72 但 3248/700 = 4.64）。
        # 取市值来源那一行；该行没有现价就用 市值/数量 推导（整股场景下精确）。
        mv_src_idx = src.get('market_value')
        price_src = next((c for c in cands if c['idx'] == mv_src_idx), None) if mv_src_idx is not None else None
        if price_src is not None and price_src['price'] is not None:
            latest['price'] = price_src['price']
            src['price'] = price_src['idx']
        elif latest.get('market_value') is not None and latest.get('qty'):
            latest['price'] = round(latest['market_value'] / latest['qty'], 4)
            src['price'] = mv_src_idx
        else:
            latest['price'] = None

        # 盘中参照：字段最多的那条（通常就是 09:35 的「核对」行），供界面做对照
        intraday = None
        strongest = max(cands, key=lambda c: (c['n_fields'], c['idx']))
        if strongest['n_fields'] >= 3 and strongest['idx'] != max(src.values() or [0]):
            intraday = {
                'market_value': strongest['market_value'],
                'float_pnl': strongest['float_pnl'],
                'total_assets': strongest['total_assets'],
                'price': strongest['price'],
                'cash': strongest['cash'],
                'raw': strongest['raw'],
            }

        out = {**latest, 'as_of': date, 'intraday': intraday,
               'candidates': len(cands), 'field_sources': src,
               'has_reading': sum(1 for k in ('cash', 'total_assets', 'market_value')
                                  if latest.get(k) is not None) >= 2}
        return out

    best = None
    for date, body in sections:
        if not date:
            continue
        # 只考虑 upto 及更早（历史回放用）
        if upto and date > upto:
            continue
        got = parse_section(date, body)
        # 文件是新→旧：**第一个有读数的章节就是最新的**，直接用它
        if got.get('has_reading'):
            best = got
            break
        if best is None and got.get('candidates'):
            best = got

    if not best or not best.get('has_reading'):
        return {'available': False, 'reason': 'AUTO_LOG.md 里未解析到账户读数'}

    if best.get('code'):
        pool = load_pool({best['code']})
        best['name'] = (pool.get(best['code']) or {}).get('name') or None

    # ── 算术自校验：把"能不能对上账"这件事显式算出来，别让用户自己去核 ──
    # 恒等式：持仓市值 + 可用资金 == 总资产
    # 若不等，说明这条读数本身有问题（多半是跨时点拼）→ 界面必须警示。
    mv, cash, ta = best.get('market_value'), best.get('cash'), best.get('total_assets')
    checks = {}
    if mv is not None and cash is not None and ta is not None:
        left = mv + cash
        diff = abs(left - ta)
        checks['assets_identity'] = {
            'ok': diff <= 1.0,          # 容忍 1 元内的四舍五入
            'left': round(left, 2),
            'right': round(ta, 2),
            'diff': round(diff, 2),
            'formula': '持仓市值 + 可用资金 = 总资产',
        }

    # 浮盈自校验：成本额 = 市值 - 浮盈，应约等于 数量 × 成本价
    qty, cost, pnl = best.get('qty'), best.get('cost'), best.get('float_pnl')
    if mv is not None and qty and cost and pnl is not None:
        cost_amount = mv - pnl
        implied = cost_amount / qty
        checks['pnl_identity'] = {
            'ok': abs(implied - cost) <= 0.01,
            'cost_amount': round(cost_amount, 2),
            'implied_cost': round(implied, 4),
            'stated_cost': round(cost, 4),
            'formula': '市值 − 浮盈 = 成本额 = 数量 × 成本价',
        }

    best['checks'] = checks
    best['available'] = True
    best['source'] = 'AUTO_LOG.md（策略侧人工核对记录）'
    return best


def account_history() -> dict:
    """账户历史：AUTO_LOG 每天一条「当日最终读数」，按日期**升序**返回。

    ## 只输出真实存在的记录，不插值、不补齐
    AUTO_LOG 目前只有 5 个交易日（2026-10-12 ~ 10-16）。**没有的日子就是没有**，
    不能拿前一天的值补上 —— 那是编造数据。
    所以返回里带 `days` 与 `range`，界面必须如实说明"共 N 天"。

    ## 复用
    逐日调用 `account_estimate(upto=date)`，**同一套解析逻辑**，避免两份实现漂移。
    每个日期拿到的是"截至当天为止的最新读数"，即当天最终状态。
    """
    dates = log_section_dates()
    if not dates:
        return {'available': False, 'reason': 'AUTO_LOG.md 里没有日期章节', 'items': []}

    items = []
    for d in sorted(dates):          # 升序：最旧 → 最新
        e = account_estimate(upto=d)
        if not e.get('available'):
            continue
        items.append({
            'date': e.get('as_of') or d,
            'total_assets': e.get('total_assets'),
            'market_value': e.get('market_value'),
            'cash': e.get('cash'),
            'float_pnl': e.get('float_pnl'),
            'day_pnl': e.get('day_pnl'),
            'price': e.get('price'),
            'qty': e.get('qty'),
            'code': e.get('code'),
            'checks_ok': all((v or {}).get('ok') for v in (e.get('checks') or {}).values())
                         if e.get('checks') else None,
        })

    return {
        'available': bool(items),
        'items': items,
        'days': len(items),
        'range': [items[0]['date'], items[-1]['date']] if items else None,
        'source': 'AUTO_LOG.md（策略侧每日核对记录，非逐笔实时）',
        # 说明：这是"有记录的天数"，不是连续交易日 —— 中间可能有缺失
        'note': '仅包含 AUTO_LOG 中有核对记录的日期，未做插值补齐',
    }


# ── 多日决策追踪 ───────────────────────────────────────────────────────

def decision_trend(days: int = 5) -> dict:
    """跨多日汇总每只股票的 rank / pred / FF 变化 —— 看"策略在看什么、在变什么"。

    ## 为什么需要这个
    选股页原来只能看**单日快照**。但策略的续持/卖出判断恰恰依赖**跨日变化**：
      · 卖出条件之一：**跌出 Top20%**（rank > 阈值）
      · 卖出条件之二：**FF 转好**
    只看一天，看不出"它正在逼近门槛"还是"刚掉出去"，也就看不出风险。

    ## 口径
    · 每天一份 `decision_<date>.csv`；**只汇总真实存在的日期**，缺的日子留空，
      不插值、不填补（与 account_history 同一纪律）
    · `rank` 原样透传；`delta` = 最新 rank − 最早 rank（负数 = 排名上升/更靠前）
    · Top20% 阈值按**当日实际打分只数**算（`max(1, round(n*0.2))`），逐日各自计算
    """
    dates = list_decisions(max(1, min(30, days)))
    if not dates:
        return {'available': False, 'reason': '未找到任何 decision_*.csv', 'dates': [], 'items': []}

    dates_asc = sorted(dates)          # 升序：旧 → 新
    pool = load_pool()
    # code -> {date: {rank,pred,ff_ok}}
    series: dict[str, dict[str, dict]] = {}
    thresholds: dict[str, int] = {}

    for d in dates_asc:
        dec = load_decision(d)
        if not dec.get('available'):
            continue
        items = dec.get('items') or []
        thresholds[d] = max(1, int(round(len(items) * 0.2)))
        for it in items:
            c = it['code']
            series.setdefault(c, {})[d] = {
                'rank': it.get('rank'),
                'pred': it.get('pred'),
                'ff_ok': it.get('ff_ok'),
            }

    if not series:
        return {'available': False, 'reason': '决策文件都解析失败', 'dates': dates_asc, 'items': []}

    rows = []
    for code, by_date in series.items():
        meta = pool.get(code) or {}
        # 最新一天有数据的那天
        latest_date = max(by_date.keys())
        # 最早一天有数据的那天
        first_date = min(by_date.keys())
        r_latest = by_date[latest_date].get('rank')
        r_first = by_date[first_date].get('rank')
        p_latest = by_date[latest_date].get('pred')
        p_first = by_date[first_date].get('pred')
        thr_latest = thresholds.get(latest_date)
        rows.append({
            'code': code,
            'name': meta.get('name') or '',
            'industry': meta.get('industry') or '',
            # 每日 rank（缺的日子为 None，界面留空）
            'ranks': {d: (by_date.get(d) or {}).get('rank') for d in dates_asc},
            'preds': {d: (by_date.get(d) or {}).get('pred') for d in dates_asc},
            'ff_ok': {d: (by_date.get(d) or {}).get('ff_ok') for d in dates_asc},
            'rank_latest': r_latest,
            'rank_first': r_first,
            # 负数 = 排名上升（更靠前），正数 = 下滑
            'delta': (r_latest - r_first) if (r_latest is not None and r_first is not None) else None,
            'pred_latest': p_latest,
            'pred_delta': (p_latest - p_first) if (p_latest is not None and p_first is not None) else None,
            'days_present': len(by_date),
            'in_top20': (r_latest is not None and thr_latest is not None and r_latest <= thr_latest),
            'threshold_latest': thr_latest,
        })

    # 排序：最新 rank 为准（缺失的排最后）
    rows.sort(key=lambda x: (x['rank_latest'] is None, x['rank_latest'] or 0))

    return {
        'available': True,
        'dates': dates_asc,
        'thresholds': thresholds,
        'items': rows,
        'total': len(rows),
        'note': '仅包含真实存在的决策日期，缺的日期留空（未插值）',
        'source': 'output/sim/decision_*.csv',
    }


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
            'pool': {**pool_info(None), 'ranked': 0, 'scope_note': 'rank 为策略池内排名，非全市场排名'},
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
    #
    # Top20% 门槛必须**显式算出来并返回**，不要只在两边各写一遍：
    #   · 分母用 `len(items)`（实际被打分的只数），**不是池大小** ——
    #     因为数据不全的票会被 daily_decision 跳过，两者可能不等（扩池后更明显）
    #   · 扩池后门槛会自动变大（200 池 → 40），前端据此显示即可，**不要写死 20**
    top20_threshold = max(1, int(round(len(items) * 0.2)))

    position_ctx = None
    if pos:
        code = pos.get('code')
        if code:
            hit = next((x for x in items if x['code'] == code), None)
            rk = (hit or {}).get('rank')
            position_ctx = {
                **pos,
                'name': pos.get('name') or ((hit or {}).get('name') or ''),
                'rank': rk,
                'pred': (hit or {}).get('pred'),
                # 策略卖出条件：跌出 Top20%（rank > 门槛）或 FF 转好
                'in_top20': (isinstance(rk, (int, float)) and rk <= top20_threshold),
                'top20_threshold': top20_threshold,
                # 持仓不在当日决策里（例如已清仓或数据缺失）→ 明确区分
                'in_decision': hit is not None,
            }
        else:
            position_ctx = {**pos, 'rank': None, 'pred': None,
                            'in_top20': None, 'top20_threshold': top20_threshold,
                            'in_decision': None}

    pinfo = pool_info(dec.get('codes'))
    return {
        'available': True,
        'date': dec['date'],
        'source': dec.get('source'),
        'total': dec.get('total'),
        # ── 池边界（扩池后自动变化，前端不得写死）──
        'pool': {
            **pinfo,
            # 池大小 vs 实际被打分的只数：两者可能不等（数据不全的票会被跳过）
            'pool_size': pinfo.get('size'),
            'ranked': len(items),
            'skipped': max(0, (pinfo.get('size') or 0) - len(items)),
            # rank 是**池内排名**，不是全市场排名 —— 必须让界面能说清楚
            'scope_note': 'rank 为策略池内排名，非全市场排名',
        },
        'top20_threshold': top20_threshold,
        'risk': {'available': risk.get('available'), 'ts': risk.get('ts'),
                 'reason': risk.get('reason'), 'checked': len(by_code), 'depth': depth},
        'items': items,
        'buyable_count': sum(1 for x in items if x['buyable']),
        'position': position_ctx,
        'summary': strategy_summary(),
    }
