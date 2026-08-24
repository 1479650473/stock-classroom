# -*- coding: utf-8 -*-
"""A股证券目录 / 可查询标的池 — 参照 FinanceDatabase 的 select() 架构，但数据源自本地库。

数据源(kline.db，两套板块体系，命名不对齐，代码里已注明)：
  - stock_list     5211 只证券: code/name/board(sh|sz)/status(active|delisted)/listed_date/total_days
  - stock_sector   code -> 粗赛道板块(25个，如 银行/医药/医疗/AI/人工智能)，仅约 1158 只有成分
  - sector_board   东财 granular 行业/概念(991个，BK####码，含 leader/涨跌)，无成分股关联

用途：让研究代理能用『板块/交易所/状态/关键词』声明式地选出标的池，
而不是硬编码一只只代码；同时为策略/报告提供板块上下文。
"""
import os, sqlite3, threading

_PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DB_PATH = os.path.join(_PROJECT_DIR, "data", "kline.db")

_lock = threading.Lock()
_loaded = False
_STOCKS = {}        # code -> {code,name,board,status,listed_date,total_days}
_SECTOR_OF = {}     # code -> [sectors...]
_SECTOR_CODES = {}  # sector -> [codes...]
_BOARDS = []        # [{code,name,type,rank,latest_price,change_pct,leader,leader_chg}]
_BOARD_BY_NAME = {} # name -> board dict


def _load():
    global _loaded, _STOCKS, _SECTOR_OF, _SECTOR_CODES, _BOARDS, _BOARD_BY_NAME
    if _loaded:
        return
    with _lock:
        if _loaded:
            return
        con = sqlite3.connect(DB_PATH)
        con.row_factory = sqlite3.Row
        for r in con.execute(
                "SELECT code,name,board,status,listed_date,total_days FROM stock_list"):
            _STOCKS[r["code"]] = dict(r)
        for r in con.execute("SELECT code,sector FROM stock_sector"):
            _SECTOR_OF.setdefault(r["code"], []).append(r["sector"])
            _SECTOR_CODES.setdefault(r["sector"], []).append(r["code"])
        for r in con.execute(
                "SELECT * FROM sector_board WHERE name IS NOT NULL AND name!='' "):
            d = dict(r)
            _BOARDS.append(d)
            if d.get("name"):
                _BOARD_BY_NAME.setdefault(d["name"], d)
        con.close()
        _loaded = True


# ── 基础查询 ─────────────────────────────────────────────────
def stats() -> dict:
    _load()
    return {
        "total_stocks": len(_STOCKS),
        "active_stocks": sum(1 for s in _STOCKS.values() if s["status"] == "active"),
        "sectors": len(_SECTOR_CODES),
        "stocks_with_sector": len(_SECTOR_OF),
        "boards": len(_BOARDS),
    }


def sectors() -> list:
    _load()
    return sorted(_SECTOR_CODES.keys())


def sector_codes(sector: str) -> list:
    _load()
    return list(_SECTOR_CODES.get(sector, []))


def describe(code: str) -> dict:
    _load()
    s = _STOCKS.get(code)
    if not s:
        return None
    return {
        **s,
        "sectors": _SECTOR_OF.get(code, []),
        "name": s.get("name", code),
        "board": s.get("board", ""),
        "status": s.get("status", ""),
    }


def select(sector=None, board=None, status="active", exclude_st=True,
           name_kw=None, codes=None) -> list:
    """按条件筛选标的池。

    sector: 粗赛道名(stock_sector)；board: sh|sz；status: active|delisted|None(不过滤)；
    exclude_st: 剔除 ST/*ST/退；name_kw: 名称模糊含；codes: 显式给定一组 code 作范围。
    返回 [{code,name,board,status,sectors}]
    """
    _load()
    # —— FinanceDatabase 式入参校验：先 show_options 枚举，非法即报错 ——
    if sector is not None and sector not in _SECTOR_CODES:
        raise ValueError(
            f"板块 '{sector}' 不在目录中。可用板块: {', '.join(sorted(_SECTOR_CODES.keys()))}")
    if board is not None and board not in ("sh", "sz"):
        raise ValueError(f"交易所 board 仅支持 'sh' / 'sz'，收到 '{board}'")
    if status is not None and status not in ("active", "delisted"):
        raise ValueError(f"状态 status 仅支持 'active' / 'delisted'，收到 '{status}'")

    pool = codes if codes is not None else list(_STOCKS.keys())
    out = []
    for c in pool:
        s = _STOCKS.get(c)
        if not s:
            continue
        if status and s.get("status") != status:
            continue
        if board and s.get("board") != board:
            continue
        nm = s.get("name", c)
        if exclude_st and ("ST" in nm.upper() or "退" in nm):
            continue
        if name_kw and name_kw not in nm:
            continue
        if sector:
            if sector not in _SECTOR_OF.get(c, []):
                continue
        out.append({
            "code": c, "name": nm,
            "board": s.get("board", ""), "status": s.get("status", ""),
            "sectors": _SECTOR_OF.get(c, []),
        })
    out.sort(key=lambda x: x["code"])
    return out


def search(name_kw, limit=30) -> list:
    _load()
    if not name_kw:
        return []
    res = [{"code": c, "name": s["name"], "board": s["board"], "status": s["status"]}
           for c, s in _STOCKS.items() if name_kw in s.get("name", "")]
    res.sort(key=lambda x: x["code"])
    return res[:limit]


# ── 东财板块(另有体系) ─────────────────────────────────────
def board_overview(limit=20, btype=None) -> list:
    """东财行业/概念板块热力(含龙头、涨跌)。btype: industry|concept。"""
    _load()
    rows = [b for b in _BOARDS if (not btype or b.get("type") == btype)]
    rows.sort(key=lambda b: (b.get("change_pct") or 0), reverse=True)
    return rows[:limit]


def leader_of(sector: str) -> dict:
    """按板块名找东财板块龙头(尽力匹配，板块命名跨体系不一定对齐)。"""
    _load()
    d = _BOARD_BY_NAME.get(sector)
    if d:
        return {"board": d["name"], "code": d.get("code"), "type": d.get("type"),
                "leader": d.get("leader"), "leader_chg": d.get("leader_chg"),
                "change_pct": d.get("change_pct")}
    # 模糊回退
    for name, d in _BOARD_BY_NAME.items():
        if sector in name:
            return {"board": name, "code": d.get("code"), "type": d.get("type"),
                    "leader": d.get("leader"), "leader_chg": d.get("leader_chg"),
                    "change_pct": d.get("change_pct")}
    return None


# ── 策略契约 universe 解析 ──────────────────────────────────
def resolve_universe(universe: dict) -> dict:
    """把策略契约的 universe 解析成具体代码列表。

    universe 支持两态：
      {code:'600036', name:'招商银行'}                    -> 单标的
      {selector:{sector:'银行', board:'sh', status:'active'}} -> 按目录筛选
    返回 {'codes':[...], 'name':str, 'selector':bool}
    """
    _load()
    sel = universe.get("selector")
    if sel:
        items = select(**{k: v for k, v in sel.items() if v not in (None, "")})
        return {"codes": [i["code"] for i in items], "name": "目录筛选", "selector": True}
    code = universe.get("code", "")
    if code:
        return {"codes": [code], "name": universe.get("name", code), "selector": False}
    return {"codes": [], "name": "", "selector": False}
