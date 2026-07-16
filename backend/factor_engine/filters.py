# placeholder
"""选股前置过滤器 — 在评分前剔除不符合条件的股票"""
import sqlite3


DEFAULT_FILTERS = {
    "exclude_st": True,
    "exclude_bj": True,
    "exclude_kcb": False,
    "exclude_cyb": False,
    "min_price": 0.0,
    "max_price": 0.0,
}


def _get_code_prefix(code: str) -> str:
    return code[:2] if len(code) >= 2 else ""


def _check_board(code: str, name: str, filters: dict) -> bool:
    """板块过滤：返回 False 表示被过滤掉"""
    prefix = _get_code_prefix(code)
    if filters.get("exclude_st", False) and "ST" in name:
        return False
    if filters.get("exclude_bj", False) and prefix in ("83", "87", "43"):
        return False
    if filters.get("exclude_kcb", False) and code.startswith("688"):
        return False
    if filters.get("exclude_cyb", False) and prefix == "30":
        return False
    return True


def _get_price_map(db_path: str, codes: list[str]) -> dict[str, float]:
    """批量获取最新收盘价"""
    if not codes:
        return {}
    conn = sqlite3.connect(db_path)
    try:
        phs = ",".join("?" for _ in codes)
        sql = (
            "SELECT k.code, k.close FROM kline_daily k "
            "INNER JOIN ("
            "  SELECT code, MAX(date) md FROM kline_daily GROUP BY code"
            ") latest ON k.code = latest.code AND k.date = latest.md "
            "WHERE k.code IN (%s)" % phs
        )
        rows = conn.execute(sql, codes).fetchall()
        return {str(r[0]): float(r[1]) for r in rows if r[1] is not None}
    finally:
        conn.close()


def apply_filters(
    candidates: list[tuple[str, str]],
    filters: dict,
    db_path: str = None,
) -> list[tuple[str, str]]:
    if not filters:
        return candidates
    # 1. 板块过滤
    result = []
    for code, name in candidates:
        if _check_board(code, name, filters):
            result.append((code, name))
    # 2. 价格过滤
    min_p = filters.get("min_price", 0.0)
    max_p = filters.get("max_price", 0.0)
    if (min_p > 0 or max_p > 0) and db_path and result:
        codes = [c[0] for c in result]
        price_map = _get_price_map(db_path, codes)
        filtered = []
        for code, name in result:
            price = price_map.get(code)
            if price is None:
                filtered.append((code, name))
                continue
            if min_p > 0 and price < min_p:
                continue
            if max_p > 0 and price > max_p:
                continue
            filtered.append((code, name))
        result = filtered
    return result
