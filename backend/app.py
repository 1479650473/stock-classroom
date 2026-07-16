# -*- coding: utf-8 -*-
"""叶瞬光量化选股系统 - Flask API
Flask + SQLite + AKShare（主）+ 新浪（fallback）
12 个路由，数据源架构：AKShare -> 新浪兜底 -> SQLite缓存
"""

from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS
import sqlite3
import os
from datetime import datetime, date

# 清除代理环境变量（避免 AKShare 走代理失败）
for k in ["HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy",
          "ALL_PROXY", "all_proxy", "NO_PROXY", "no_proxy"]:
    os.environ.pop(k, None)

from factor_engine import FactorScorer
from indicators import enrich_kline

app = Flask(__name__)
CORS(app)

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "stock_cache.db")

KLINE_DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'data', 'kline.db')


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def get_kline_db():
    conn = sqlite3.connect(KLINE_DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn

def init_db():
    """Initialize cache tables in stock_cache.db only.
    kline.db tables are managed by data_manager.init_tables() and cache functions.
    """
    conn = get_db()
    conn.execute("""CREATE TABLE IF NOT EXISTS stock_spot (
        code TEXT PRIMARY KEY, name TEXT, price REAL, open REAL,
        high REAL, low REAL, volume INTEGER, amount REAL, change_pct REAL,
        change_amount REAL, turnover REAL, pe REAL, pb REAL,
        total_mv REAL, circ_mv REAL, updated_at TEXT)""")
    conn.commit()
    conn.close()

init_db()

from data_manager import get_kline_data, get_stock_list, get_update_logs, show_status


# ════════════════════════════════════════════════════════
#  股票数据 API
# ════════════════════════════════════════════════════════

@app.route("/api/stock/list")
def api_stock_list():
    status = request.args.get("status", "all")
    stocks = get_stock_list(status)
    return jsonify({"code": 0, "data": stocks, "total": len(stocks)})

@app.route("/api/stock/stats")
def api_stock_stats():
    stats = show_status()
    return jsonify({"code": 0, "data": stats})

@app.route("/api/stock/update-logs")
def api_update_logs():
    limit = int(request.args.get("limit", 20))
    logs = get_update_logs(limit)
    return jsonify({"code": 0, "data": logs})

@app.route("/api/stock/search")
def api_stock_search():
    q = request.args.get("q", "").strip()
    if not q:
        return jsonify({"code": -1, "error": "请输入搜索关键词"})
    conn = get_kline_db()
    rows = conn.execute("SELECT * FROM stock_list WHERE code LIKE ? OR name LIKE ? ORDER BY code LIMIT 50",
                        (f"%{q}%", f"%{q}%")).fetchall()
    conn.close()
    return jsonify({"code": 0, "data": [dict(r) for r in rows]})

@app.route("/api/stock/delisted")
def api_delisted_stocks():
    stocks = get_stock_list("delisted")
    return jsonify({"code": 0, "data": stocks})


# ════════════════════════════════════════════════════════
#  市场行情 API（AKShare 主 + 新浪 fallback）
# ════════════════════════════════════════════════════════

@app.route("/api/market")
def api_market():
    """三大指数实时行情：AKShare -> 新浪直连 fallback"""
    from akshare_source import ak_get_index_spot
    data = ak_get_index_spot()
    # 只返回三个主要指数
    main_ids = {"sh000001", "sz399001", "sz399006"}
    main_data = [d for d in data if d.get("code") in main_ids]
    if not main_data:
        # fallback 也挂了就用旧的新浪直接
        from data_manager import fetch_index_prices
        main_data = fetch_index_prices()
    return jsonify({"code": 0, "data": main_data, "source": main_data[0].get("source", "sina") if main_data else "none"})

@app.route("/api/market/all-index")
def api_all_index():
    """全部指数实时行情"""
    from akshare_source import ak_get_index_spot
    data = ak_get_index_spot()
    return jsonify({"code": 0, "data": data})

@app.route("/api/market/sectors")
def api_sectors():
    """行业/概念板块行情"""
    sector_type = request.args.get("type", "industry")
    from akshare_source import ak_get_sectors
    data = ak_get_sectors(sector_type)
    return jsonify({"code": 0, "data": data, "type": sector_type})

@app.route("/api/market/north-flow")
def api_north_flow():
    """北向资金净流入"""
    days = int(request.args.get("days", 30))
    from akshare_source import ak_get_north_flow
    data = ak_get_north_flow(days)
    return jsonify({"code": 0, "data": data})

@app.route("/api/market/etf")
def api_etf_list():
    """ETF实时行情"""
    from akshare_source import ak_get_etf_list
    data = ak_get_etf_list()
    return jsonify({"code": 0, "data": data})


# ════════════════════════════════════════════════════════
#  选股 & K线 API
# ════════════════════════════════════════════════════════

@app.route("/api/picks")
def api_picks():
    """AI 选股 Top 20：多因子评分引擎 (factor_engine)"""
    from data_manager import get_kline_data
    conn = get_kline_db()
    rows = conn.execute(
        "SELECT code, name FROM stock_list WHERE status='active' ORDER BY code"
    ).fetchall()
    conn.close()
    candidates = []
    for r in rows:
        code, name = str(r[0]), str(r[1])
        if code[:2] not in ("60","00","30","68"): continue
        if "ST" in name: continue
        candidates.append((code, name))
    scorer = FactorScorer()
    results = []
    kline_cache = {}
    for code, name in candidates:
        if code not in kline_cache:
            kline_cache[code] = get_kline_data(code, 60)
        kd = kline_cache[code]
        if not kd or len(kd) < 2: continue
        last, prev = kd[-1], kd[-2]
        close, pv = last["close"], prev["close"]
        vol = int(last.get("volume", 0))
        chg = round((close - pv) / pv * 100, 2) if pv else 0.0
        if vol <= 0: continue
        try:
            s = scorer.score_stock(code, name, kd)
            d = s.to_api_dict()
            results.append({
                "code": code, "name": name,
                "price": close, "change_pct": chg, "volume": vol,
                "score": round(d["total_score"], 1),
                "groups": d["groups"],
            })
        except Exception:
            continue
    results.sort(key=lambda x: x["score"], reverse=True)
    return jsonify({"code": 0, "data": results[:20], "total_scanned": len(results)})

@app.route("/api/kline")
def api_kline():
    code = request.args.get("code", "")
    days = int(request.args.get("days", 180))
    if not code:
        return jsonify({"code": -1, "error": "no code"})
    from data_manager import get_kline_data
    kd = get_kline_data(code, days)
    enriched = enrich_kline(kd)  # from indicators import
    return jsonify({"code": 0, "data": enriched})


# ════════════════════════════════════════════════════════
#  持仓 & 新闻 API
# ════════════════════════════════════════════════════════

@app.route("/api/holdings")
def api_holdings():
    return jsonify({
        "code": 0,
        "data": [
            {"code": "600519", "name": "贵州茅台", "cost": 1680.0, "shares": 100, "current": 1725.5},
            {"code": "000858", "name": "五粮液", "cost": 145.0, "shares": 1000, "current": 152.3},
        ],
    })

@app.route("/api/news")
def api_news():
    """个股新闻（AKShare）"""
    code = request.args.get("code", "000001")
    limit = int(request.args.get("limit", 20))
    from akshare_source import ak_get_stock_news
    data = ak_get_stock_news(code, limit)
    return jsonify({"code": 0, "data": data})


# ════════════════════════════════════════════════════════
#  缓存查询 API（优先读缓存，降低实时查询压力）
# ════════════════════════════════════════════════════════

@app.route("/api/cache/spot")
def api_cached_spot():
    """从 stock_cache.db 读取缓存行情（比实时接口快 10x+）"""
    from data_manager import get_cached_spot, cache_spot_from_akshare
    data = get_cached_spot()
    if not data:
        # 缓存空则自动刷新
        n = cache_spot_from_akshare()
        data = get_cached_spot()
    return jsonify({"code": 0, "data": data, "cached": len(data)})

@app.route("/api/cache/sectors")
def api_cached_sectors():
    """从 kline.db 读板块行情"""
    import sqlite3, os
    cache_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "kline.db")
    conn = sqlite3.connect(cache_path, timeout=10)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT * FROM sector_data ORDER BY type, change_pct DESC").fetchall()
    conn.close()
    return jsonify({"code": 0, "data": [dict(r) for r in rows], "cached": len(rows)})

@app.route("/api/cache/north-flow")
def api_cached_north_flow():
    """从 kline.db 读北向资金"""
    import sqlite3, os
    cache_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "kline.db")
    conn = sqlite3.connect(cache_path, timeout=10)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT * FROM north_flow ORDER BY date DESC LIMIT 30").fetchall()
    conn.close()
    return jsonify({"code": 0, "data": [dict(r) for r in rows], "cached": len(rows)})


# ════════════════════════════════════════════════════════
#  健康检查
# ════════════════════════════════════════════════════════

@app.route("/api/cyq")
def api_cyq():
    """筹码分布数据"""
    code = request.args.get("code", "")
    if not code:
        return jsonify({"error": "missing code"}), 400
    try:
        from data_manager import get_kline_db
        conn = get_kline_db()
        rows = conn.execute(
            "SELECT code, date, [获利比例], [平均成本], [90成本_低], [90成本_高], [90集中度], [70成本_低], [70成本_高], [70集中度], updated_at FROM chip_distribution WHERE code=? ORDER BY date DESC",
            (code,)
        ).fetchall()
        conn.close()
        if not rows:
            return jsonify({"error": "no cyq data"}), 404
        result = []
        for r in rows:
            result.append({
                "code": r[0], "date": r[1],
                "获利比例": r[2], "平均成本": r[3],
                "90成本_低": r[4], "90成本_高": r[5], "90集中度": r[6],
                "70成本_低": r[7], "70成本_高": r[8], "70集中度": r[9],
            })
        return jsonify({"data": result, "count": len(result)})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/cyq/refresh")
def api_cyq_refresh():
    """刷新筹码分布缓存"""
    code = request.args.get("code", "")
    if not code:
        return jsonify({"error": "missing code"}), 400
    try:
        from data_manager import cache_cyq_chip_data
        count = cache_cyq_chip_data(code)
        return jsonify({"cached": count})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/health")
def api_health():
    from data_manager import check_health
    base = check_health()
    return jsonify(base)

@app.route("/api/diagnose")
def api_diagnose():
    """AKShare 数据源完整诊断"""
    return jsonify({"code": 0, "data": diagnose_akshare()})


# ════════════════════════════════════════════════════════
#  前端 & 静态文件
# ════════════════════════════════════════════════════════

FRONTEND_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "frontend")

@app.route("/")
def index():
    return send_from_directory(FRONTEND_DIR, "index.html")

@app.route("/css/<path:filename>")
def static_css(filename):
    return send_from_directory(os.path.join(FRONTEND_DIR, "css"), filename)

@app.route("/js/<path:filename>")
def static_js(filename):
    return send_from_directory(os.path.join(FRONTEND_DIR, "js"), filename)

@app.route("/architecture")
def architecture():
    arch_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "docs", "architecture.html")
    with open(arch_path, "rb") as f:
        return f.read()

@app.route("/db-monitor")
def db_monitor():
    return send_from_directory(FRONTEND_DIR, "db-monitor.html")


# ════════════════════════════════════════════════════════
#  启动
# ════════════════════════════════════════════════════════



@app.route("/api/db/monitor")
def api_db_monitor():
    """DB monitor - queries kline.db for main tables, stock_cache.db for cache tables"""
    import os as _os
    # Main DB tables
    conn = get_kline_db()
    ts = {}
    for t in ["kline_daily", "market_daily", "stock_list", "data_update_log"]:
        try:
            r = conn.execute("SELECT COUNT(*) FROM " + t).fetchone()
            ts[t] = r[0]
        except:
            ts[t] = 0
    conn.close()
    # Cache DB tables
    conn2 = get_db()
    for t in ["stock_spot", "sector_data", "north_flow", "fund_flow", "limit_up"]:
        try:
            r = conn2.execute("SELECT COUNT(*) FROM " + t).fetchone()
            ts[t] = r[0]
        except:
            ts[t] = 0
    spot_u = conn2.execute("SELECT MAX(updated_at) FROM stock_spot").fetchone()
    sec_u = conn2.execute("SELECT MAX(updated_at) FROM sector_data").fetchone()
    north_u = conn2.execute("SELECT MAX(date) FROM north_flow").fetchone()
    conn2.close()
    dbp = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", "data", "kline.db")
    cbp = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", "data", "stock_cache.db")
    ks = _os.path.getsize(dbp) / 1048576
    cs = _os.path.getsize(cbp) / 1048576 if _os.path.exists(cbp) else 0
    return jsonify({"code":0,"data":{"table_stats":ts,"db_sizes":{"kline_db_mb":round(ks,1),"cache_db_mb":round(cs,1)},"cache":{"spot_count":ts.get("stock_spot",0),"spot_updated":spot_u[0] if spot_u and spot_u[0] else None,"sector_count":ts.get("sector_data",0),"sector_updated":sec_u[0] if sec_u and sec_u[0] else None,"north_count":ts.get("north_flow",0),"north_updated":north_u[0] if north_u and north_u[0] else None}}})
if __name__ == "__main__":
    print("[Backend] 叶瞬光量化选股系统 v2 启动...")
    print("[Backend] 数据源: AKShare (主) + 新浪 (fallback)")
    print("[Backend] 地址: http://127.0.0.1:5000")
    print("[Backend] 新增路由: /api/market/all-index /api/market/sectors /api/market/north-flow /api/market/etf /api/news /api/diagnose")
    print("ROUTES:", [r.rule for r in app.url_map.iter_rules()])
    app.run(host="127.0.0.1", port=5000, debug=False)








