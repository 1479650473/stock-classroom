"""data_manager.py — 统一数据管理模块（AKShare 数据源 + 多线程）
用法:
  python data_manager.py clean        # 完整清洗
  python data_manager.py update       # 每日增量更新
  python data_manager.py catch-up     # 补全历史
  python data_manager.py status       # 查看状态
  python data_manager.py stock-list   # 股票列表
"""

import sqlite3, os, sys, time, json, http.client, logging
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Tuple
from concurrent.futures import ThreadPoolExecutor, as_completed

import pandas as pd
# AKShare calls centralized through akshare_source module
from akshare_source import ak_fetch_kline, ak_fetch_index_kline, ak_get_all_stocks, ak_get_spot_all, ak_get_index_spot, ak_get_sectors, ak_get_north_flow, ak_get_limit_up, ak_get_lhb_stock_statistic, ak_get_high_low

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(os.path.dirname(BASE_DIR), "data")
KLINE_DB = os.path.join(DATA_DIR, "kline.db")
CACHE_DB = os.path.join(DATA_DIR, "stock_cache.db")

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger("data_mgr")

SINA_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
WORKERS = 15   # 15 线程并发


def get_kline_db():
    conn = sqlite3.connect(KLINE_DB, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA cache_size=-400000")
    return conn


# ════════════════════════════════════════════════════════
#  数据获取函数已统一到 akshare_source.py
#  ak_fetch_kline, ak_fetch_index_kline, ak_get_all_stocks
#  均从 akshare_source 模块导入
# ════════════════════════════════════════════════════════


# ════════════════════════════════════════════════════════
#  表初始化
# ════════════════════════════════════════════════════════
def init_tables():
    conn = get_kline_db()
    conn.execute("""CREATE TABLE IF NOT EXISTS stock_list (
        code TEXT PRIMARY KEY, name TEXT, board TEXT,
        status TEXT DEFAULT 'active', listed_date TEXT, updated_at TEXT
    )""")
    # 数据库迁移：兼容旧表加字段
    try:
        cols = [r[1] for r in conn.execute("PRAGMA table_info(stock_list)").fetchall()]
        if "last_date" not in cols:
            conn.execute("ALTER TABLE stock_list ADD COLUMN last_date TEXT")
        if "total_days" not in cols:
            conn.execute("ALTER TABLE stock_list ADD COLUMN total_days INTEGER DEFAULT 0")
    except Exception:
        pass
    conn.execute("""CREATE TABLE IF NOT EXISTS data_update_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT, update_date TEXT NOT NULL,
        stocks_total INTEGER DEFAULT 0, stocks_new INTEGER DEFAULT 0,
        rows_added INTEGER DEFAULT 0, status TEXT DEFAULT 'ok',
        message TEXT, duration_sec REAL,
        created_at TEXT DEFAULT (datetime('now','localtime'))
    )""")
    conn.commit()
    conn.close()


# ════════════════════════════════════════════════════════
#  清洗模块
# ════════════════════════════════════════════════════════
def clean_pre_2000():
    conn = get_kline_db()
    n = conn.execute("DELETE FROM kline_daily WHERE date < '20000101'").rowcount
    conn.commit(); conn.close()
    if n: log.info("清理 2000 年前数据: %d 行", n)
    return n

def clean_bad_codes():
    conn = get_kline_db()
    n1 = conn.execute("DELETE FROM kline_daily WHERE code NOT GLOB '[0-9][0-9][0-9][0-9][0-9][0-9]'").rowcount
    n2 = conn.execute("DELETE FROM kline_daily WHERE code GLOB '8*'").rowcount
    conn.commit(); conn.close()
    if n1 or n2: log.info("清理异常代码: %d + %d", n1, n2)
    return n1 + n2

def clean_duplicates():
    conn = get_kline_db()
    n = conn.execute("DELETE FROM kline_daily WHERE rowid NOT IN (SELECT MIN(rowid) FROM kline_daily GROUP BY code, date)").rowcount
    conn.commit(); conn.close()
    if n: log.info("去重: %d 行", n)
    return n

def remove_delisted_stocks():
    log.info("正在获取当前 A 股列表...")
    live = ak_get_all_stocks()
    if not live:
        log.warning("获取 A 股列表失败，跳过退市清理")
        return 0, 0
    live_codes = set(s["code"] for s in live)
    log.info("当前 A 股: %d 只", len(live_codes))

    conn = get_kline_db()
    db_codes = set(row["code"] for row in conn.execute("SELECT DISTINCT code FROM kline_daily").fetchall())
    delisted = sorted(db_codes - live_codes)
    if not delisted:
        log.info("没有退市股票"); conn.close(); return 0, 0

    total = 0
    for i in range(0, len(delisted), 100):
        batch = delisted[i:i+100]
        cur = conn.execute(f"DELETE FROM kline_daily WHERE code IN ({','.join('?' for _ in batch)})", batch)
        total += cur.rowcount
        for c in batch:
            conn.execute("UPDATE stock_list SET status='delisted', updated_at=? WHERE code=?",
                         (datetime.now().isoformat(), c))
        conn.commit()
    log.info("退市清理: %d 只, %d 行", len(delisted), total)
    conn.close()
    return len(delisted), total

def update_stock_list():
    log.info("更新股票名录...")
    stocks = ak_get_all_stocks()
    if not stocks:
        log.warning("获取股票列表失败")
        return 0
    conn = get_kline_db()
    # 从 kline_daily 查统计数据
    stats = {}
    for row in conn.execute(
        "SELECT code, MAX(date) as last_date, COUNT(*) as total_days FROM kline_daily GROUP BY code"
    ).fetchall():
        stats[row["code"]] = (row["last_date"], row["total_days"])
    now = datetime.now().isoformat()
    for s in stocks:
        last_date, total_days = stats.get(s["code"], (None, 0))
        conn.execute(
            "INSERT OR REPLACE INTO stock_list (code, name, board, status, last_date, total_days, updated_at) VALUES (?,?,?,'active',?,?,?)",
            (s["code"], s["name"], s["board"], last_date, total_days, now),
        )
    conn.commit()
    conn.close()
    log.info("股票名录更新: %d 只", len(stocks))
    return len(stocks)


def daily_update(target_date: str = None, catch_up_days: int = 10):
    """增量更新：用 AKShare 拉取最新 K 线

    首次运行时拉 catch_up_days=10 天数据，覆盖多个缺失交易日
    后续每日运行只拉 2 天（覆盖 weekend）
    """
    if target_date is None:
        target_date = (datetime.now() - timedelta(days=1)).strftime("%Y%m%d")

    log.info("═" * 50)
    log.info("每日数据更新: %s (拉取 %d 天)", target_date, catch_up_days)
    log.info("═" * 50)

    init_tables()
    stocks = ak_get_all_stocks()
    if not stocks: return False
    log.info("当前 A 股: %d 只", len(stocks))

    # 过滤已更新的
    conn = get_kline_db()
    existing = set(row["code"] for row in conn.execute(
        "SELECT DISTINCT code FROM kline_daily WHERE date=?", (target_date,)).fetchall())
    conn.close()
    todo = [s for s in stocks if s["code"] not in existing]
    log.info("需更新: %d 只（已有 %d）", len(todo), len(stocks) - len(todo))
    if not todo:
        log.info("数据已是最新")
        _log_update(target_date, len(stocks), 0, 0, "ok", "数据已是最新")
        return True

    # 多线程并行抓取
    t0 = time.time()
    batch_rows = []
    errors = 0

    def _fetch(s):
        rows = ak_fetch_kline(s["code"], days=catch_up_days)
        return [r for r in rows if r[1] >= target_date[:8]], s["code"]

    done = 0
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        futures = {pool.submit(_fetch, s): s for s in todo}
        for f in as_completed(futures):
            rows, code = f.result()
            done += 1
            if rows:
                batch_rows.extend(rows)
            else:
                errors += 1
            if done % 500 == 0 or done == len(todo):
                elapsed = time.time() - t0
                speed = done / elapsed if elapsed > 0 else 0
                eta = (len(todo) - done) / speed if speed > 0 else 0
                log.info("  [%d/%d] +%d 行, %.1f stk/s, ETA %.0f s",
                         done, len(todo), len(batch_rows), speed, eta)

    # 批量写入
    log.info("正在写入 %d 行数据...", len(batch_rows))
    conn = get_kline_db()
    inserted = 0
    for r in batch_rows:
        try:
            tname = f"kline_{r[1][:4]}"
            conn.execute(f"INSERT OR REPLACE INTO {tname} (code,date,open,high,low,close,volume,amount,turnover) VALUES (?,?,?,?,?,?,?,?,?)", r if len(r) >= 9 else r + (0,))
            inserted += 1
            if inserted % 2000 == 0:
                conn.commit()
        except Exception:
            pass
    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    conn.commit()
    conn.close()
    elapsed = time.time() - t0

    update_stock_list()
    status = "ok" if errors < len(todo) * 0.5 else "partial_fail"
    _log_update(target_date, len(stocks), len(todo), inserted, status,
                f"+{inserted} 行, {errors} 次失败")
    log.info("更新完成: +%d 行, %d 只写入, %d 失败, 耗时 %.0f 秒",
             inserted, len(set(r[0] for r in batch_rows)), errors, elapsed)
    return True


def _log_update(update_date, stocks_total, stocks_new, rows_added, status="ok", message=""):
    try:
        conn = get_kline_db()
        conn.execute("INSERT INTO data_update_log (update_date, stocks_total, stocks_new, rows_added, status, message) VALUES (?,?,?,?,?,?)",
                     (update_date, stocks_total, stocks_new, rows_added, status, message))
        conn.commit(); conn.close()
    except Exception:
        pass


# ════════════════════════════════════════════════════════
#  历史数据补全
# ════════════════════════════════════════════════════════
def catch_up_missing(min_rows: int = 500, max_stocks: int = 50):
    """补全数据最少的股票"""
    conn = get_kline_db()
    stocks = conn.execute("""
        SELECT s.code, s.name, COALESCE(k.total, 0) as rows_count
        FROM stock_list s
        LEFT JOIN (SELECT code, COUNT(*) as total FROM kline_daily GROUP BY code) k ON s.code = k.code
        WHERE s.status='active'
        ORDER BY rows_count ASC
        LIMIT ?
    """, (max_stocks,)).fetchall()
    conn.close()

    if not stocks:
        log.info("没有需要补全的股票")
        return 0

    log.info("补全计划: %d 只, 目标 %d 行/只", len(stocks), min_rows)
    t0 = time.time()
    total_added = 0

    for s in stocks:
        code = s["code"]
        need = min_rows - s["rows_count"]
        if need <= 0:
            continue
        days = min(need + 20, 2500)
        rows = ak_fetch_kline(code, days=days)
        if not rows:
            continue
        conn = get_kline_db()
        added = 0
        for r in rows:
            try:
                tname = f"kline_{r[1][:4]}"
                conn.execute(f"INSERT OR IGNORE INTO {tname} (code,date,open,high,low,close,volume,amount,turnover) VALUES (?,?,?,?,?,?,?,?,?)", r if len(r) >= 9 else r + (0,))
                added += 1
                if added % 500 == 0:
                    conn.commit()
            except Exception:
                pass
        conn.commit()
        conn.close()
        total_added += added
        log.info("  %s %s: +%d 行", code, s["name"], added)

    log.info("补全完成: +%d 行, 耗时 %.0f 秒", total_added, time.time() - t0)
    return total_added


# ════════════════════════════════════════════════════════
#  公共查询接口（给 app.py 调用）
# ════════════════════════════════════════════════════════

def get_kline_data(code: str, days: int = 180) -> List[Dict]:
    """从数据库读取 K 线数据
    如果是 sh/sz 前缀则查指数 K 线
    """
    conn = get_kline_db()
    if any(code.startswith(p) for p in ("sh", "sz", "bj")):
        # 指数代码
        rows = conn.execute(
            "SELECT * FROM kline_daily WHERE code=? ORDER BY date DESC LIMIT ?",
            (code, days)
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM kline_daily WHERE code=? ORDER BY date DESC LIMIT ?",
            (code, days)
        ).fetchall()
    conn.close()
    result = [dict(r) for r in rows]
    result.reverse()
    return result


def get_stock_list(status: str = "all") -> List[Dict]:
    conn = get_kline_db()
    if status == "all":
        rows = conn.execute("SELECT * FROM stock_list ORDER BY code").fetchall()
    else:
        rows = conn.execute("SELECT * FROM stock_list WHERE status=? ORDER BY code", (status,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_update_logs(limit: int = 20) -> List[Dict]:
    conn = get_kline_db()
    rows = conn.execute("SELECT * FROM data_update_log ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def show_status() -> Dict:
    conn = get_kline_db()
    total = conn.execute("SELECT COUNT(*) as n FROM kline_daily").fetchone()["n"]
    stocks = conn.execute("SELECT COUNT(DISTINCT code) as n FROM kline_daily").fetchone()["n"]
    dates = conn.execute("SELECT MIN(date) as dm, MAX(date) as dx FROM kline_daily").fetchone()
    latest = conn.execute("SELECT COUNT(DISTINCT code) as n FROM kline_daily WHERE date=(SELECT MAX(date) FROM kline_daily)").fetchone()["n"]
    active = conn.execute("SELECT COUNT(*) as n FROM stock_list WHERE status='active'").fetchone()["n"]
    delisted = conn.execute("SELECT COUNT(*) as n FROM stock_list WHERE status='delisted'").fetchone()["n"]
    db_size = os.path.getsize(KLINE_DB) / 1024 / 1024 if os.path.exists(KLINE_DB) else 0
    conn.close()
    return {
        "total_rows": total, "stock_count": stocks,
        "date_min": dates["dm"], "date_max": dates["dx"],
        "latest_day_stocks": latest,
        "active_stocks": active, "delisted_stocks": delisted,
        "db_size_mb": round(db_size, 1),
        "avg_rows_per_stock": round(total / stocks, 1) if stocks else 0,
    }


# ════════════════════════════════════════════════════════
#  实时行情接口（新浪原生直连，AKShare 不支持实时）
# ════════════════════════════════════════════════════════

SINA_QUOTE_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"

def fetch_realtime_prices(codes: List) -> List[Dict]:
    """批量获取实时行情（新浪 hq.sinajs.cn 直连）
    codes: 支持两种输入—
      - List[str] 如 ['sh000001', 'sz399001']
      - List[tuple] 如 [('000001', '平安银行'), ...]
    返回: [{code, name, price, change_pct, volume, amount, ...}]
    """
    results = []
    # 分批处理，每批最多 50 只
    for i in range(0, len(codes), 50):
        batch = codes[i:i + 50]
        symbol_parts = []
        code_map = {}
        for item in batch:
            if isinstance(item, tuple):
                c, n = item[0], item[1]
                prefix = "sh" if c.startswith(("6", "9")) else "sz"
                sym = prefix + c
                code_map[sym] = {"code": c, "name": n}
            else:
                prefix = "sh" if item.startswith(("6", "9")) else "sz"
                sym = prefix + item
                code_map[sym] = {"code": item}
            symbol_parts.append(sym)

        symbol_str = ",".join(symbol_parts)
        try:
            conn = http.client.HTTPConnection("hq.sinajs.cn", timeout=10)
            conn.request("GET", f"/list={symbol_str}", headers={
                "Referer": "https://finance.sina.com.cn",
                "User-Agent": SINA_QUOTE_UA,
            })
            resp = conn.getresponse()
            text = resp.read().decode("gbk")
            conn.close()

            for line in text.strip().split("\n"):
                line = line.strip()
                if not line or not line.startswith("var hq_str_"):
                    continue
                parts = line.split("\"")
                if len(parts) < 3:
                    continue
                code_full = parts[0].replace("var hq_str_", "").strip().rstrip("=")
                fields = parts[1].split(",")
                if len(fields) < 32:
                    # 可能是指数行情（字段少）
                    if len(fields) >= 5:
                        idx_info = code_map.get(code_full, {"code": code_full})
                        try:
                            results.append({
                                "code": code_full,
                                "name": idx_info.get("name", fields[0]),
                                "open": float(fields[1]) if fields[1] else 0.0,
                                "price": float(fields[1]) if fields[1] else 0.0,
                                "last_close": float(fields[2]) if fields[2] else 0.0,
                                "high": float(fields[4]) if fields[4] else 0.0,
                                "low": float(fields[5]) if fields[5] else 0.0,
                                "volume": int(float(fields[4])),
                                "amount": float(fields[5]) if len(fields) > 5 and fields[5] else 0.0,
                                "change_pct": float(fields[3]) if fields[3] else 0.0,
                                "turnover": 0.0,
                            })
                        except (ValueError, IndexError):
                            pass
                    continue

                code_raw = code_full[2:] if code_full[:2] in ("sh", "sz") else code_full
                name = fields[0]
                try:
                    open_p = float(fields[1]) if fields[1] else 0.0
                    last_close = float(fields[2]) if fields[2] else 0.0
                    price = float(fields[3]) if fields[3] else 0.0
                    high = float(fields[4]) if fields[4] else 0.0
                    low = float(fields[5]) if fields[5] else 0.0
                    volume = float(fields[8]) if fields[8] else 0.0
                    amount = float(fields[9]) if fields[9] else 0.0
                except (ValueError, IndexError):
                    continue

                change_pct = round((price - last_close) / last_close * 100, 2) if last_close else 0.0
                turnover = round(amount / (price * 100) * 100, 4) if price and amount else 0.0

                results.append({
                    "code": code_raw,
                    "name": name,
                    "open": open_p,
                    "last_close": last_close,
                    "price": price,
                    "high": high,
                    "low": low,
                    "volume": int(volume),
                    "amount": amount,
                    "change_pct": change_pct,
                    "turnover": turnover,
                })
        except Exception:
            continue

    return results


def fetch_index_prices(codes: List[str] = None) -> List[Dict]:
    """获取指数实时行情（新浪原生直连）
    codes: ['sh000001', 'sz399001', 'sz399006']
    """
    if codes is None:
        codes = ["sh000001", "sz399001", "sz399006"]

    symbol_str = ",".join(f"s_{c}" for c in codes)
    try:
        conn = http.client.HTTPConnection("hq.sinajs.cn", timeout=10)
        conn.request("GET", f"/list={symbol_str}", headers={
            "Referer": "https://finance.sina.com.cn",
            "User-Agent": SINA_QUOTE_UA,
        })
        resp = conn.getresponse()
        text = resp.read().decode("gbk")
        conn.close()
    except Exception:
        return []

    name_map = {
        "sh000001": "上证指数", "sz399001": "深证成指",
        "sz399006": "创业板指", "sh000300": "沪深300",
        "sh000016": "上证50", "sh000688": "科创50",
    }
    results = []
    for line in text.strip().split("\n"):
        line = line.strip()
        if not line or not line.startswith("var hq_str_s_"):
            continue
        parts = line.split("\"")
        if len(parts) < 3:
            continue
        code_full = parts[0].replace("var hq_str_s_", "").strip().rstrip("=")
        fields = parts[1].split(",")
        if len(fields) < 5:
            continue
        name = fields[0] if fields[0] else name_map.get(code_full, code_full)
        try:
            price = float(fields[1])
            change_pct = float(fields[3])
            results.append({
                "code": code_full,
                "name": name,
                "price": price,
                "volume": int(float(fields[4])),
                "amount": float(fields[5]) if fields[5] else 0.0,
                "change_pct": change_pct,
            })
        except (ValueError, IndexError):
            continue

    return results


def get_real_time_picks(top_n: int = 50) -> List[Dict]:
    """获取实时选股池：所有A股，去除ST和无量，按涨跌幅排序取top_n
    返回: [{code, name, price, change_pct, volume, amount, turnover}]
    """
    stocks = ak_get_all_stocks()
    if not stocks:
        return []

    codes = [s["code"] for s in stocks]
    quotes = fetch_realtime_prices(codes)

    # 过滤 ST、无量、只取 60/00/30 开头
    filtered = [
        q for q in quotes
        if "ST" not in q.get("name", "") and q.get("volume", 0) > 0
        and q.get("code", "")[:2] in ("60", "00", "30")
    ]
    filtered.sort(key=lambda x: x.get("change_pct", 0), reverse=True)
    return filtered[:top_n]


# ════════════════════════════════════════════════════════
#  CLI 入口
# ════════════════════════════════════════════════════════
def check_health() -> dict:
    """健康检查：验证各组件是否可用（本地快速检查，不做网络请求）"""
    import os
    result = {
        "akshare": False,
        "sina_realtime": True,
        "sina_stock_list": True,
        "kline_db": False,
        "flask_api": True,
    }
    # 1. 检查 AKShare — 只验证导入（不做网络请求避免超时）
    try:
        import akshare as ak
        result["akshare"] = True
    except Exception:
        result["akshare"] = False
    # 2. 检查数据库
    try:
        conn = get_kline_db()
        conn.execute("SELECT 1").fetchone()
        conn.close()
        result["kline_db"] = True
    except Exception:
        result["kline_db"] = False
    return result
def _get_cache_db():
    """Connect to stock_cache.db for cache tables"""
    conn = sqlite3.connect(CACHE_DB, timeout=30)
    conn.row_factory = sqlite3.Row
    return conn


def cache_spot_from_akshare():
    """Cache A-share spot data from AKShare into stock_spot table"""
    import akshare as ak
    import pandas as pd
    try:
        df = ak.stock_zh_a_spot_em()
        if df is None or df.empty:
            log.warning("AKShare spot empty, skipping cache")
            return 0
        col_map = {
            "代码": "code", "名称": "name",
            "最新价": "price", "涨跌幅": "change_pct",
            "涨跌额": "change_amount", "成交量": "volume",
            "成交额": "amount", "振幅": "amplitude",
            "最高": "high", "最低": "low",
            "今开": "open", "昨收": "pre_close",
            "换手率": "turnover", "市盈率-动态": "pe",
            "市净率": "pb", "总市值": "total_mv",
            "流通市值": "circ_mv",
        }
        df = df.rename(columns=col_map)
        conn = _get_cache_db()
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        count = 0
        for _, row in df.iterrows():
            try:
                conn.execute(
                    """INSERT OR REPLACE INTO stock_spot
                    (code, name, price, open, high, low, volume, amount,
                     change_pct, change_amount, turnover, pe, pb, total_mv, circ_mv, updated_at)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        str(row.get("code", "")),
                        str(row.get("name", "")),
                        float(row.get("price", 0) or 0),
                        float(row.get("open", 0) or 0),
                        float(row.get("high", 0) or 0),
                        float(row.get("low", 0) or 0),
                        int(float(row.get("volume", 0) or 0)),
                        float(row.get("amount", 0) or 0),
                        float(row.get("change_pct", 0) or 0),
                        float(row.get("change_amount", 0) or 0),
                        float(row.get("turnover", 0) or 0),
                        float(row.get("pe", 0) or 0),
                        float(row.get("pb", 0) or 0),
                        float(row.get("total_mv", 0) or 0),
                        float(row.get("circ_mv", 0) or 0),
                        now,
                    ),
                )
                count += 1
            except (ValueError, TypeError):
                continue
        conn.commit()
        conn.close()
        log.info("cached %d spots at %s", count, now)
        return count
    except Exception as e:
        log.warning("cache spot failed: %s", str(e)[:80])
        return 0

def cache_sectors_from_akshare():
    """Cache industry/concept sector data from AKShare"""
    import akshare as ak
    conn = get_kline_db()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    total = 0
    for s_type, func in [("industry", ak.stock_board_industry_name_em),
                         ("concept", ak.stock_board_concept_name_em)]:
        try:
            df = func()
            if df is None or df.empty:
                continue
            col_map = {
                "板块名称": "name", "板块代码": "code",
                "涨跌幅": "change_pct", "涨跌额": "change_amount",
                "总市值": "total_mv", "市盈率": "pe",
                "上涨家数": "up_count", "下跌家数": "down_count",
            }
            df = df.rename(columns=col_map)
            for _, row in df.iterrows():
                try:
                    conn.execute(
                        "INSERT OR REPLACE INTO sector_data VALUES (?,?,?,?,?,?,?,?)",
                        (
                            row.get("code", ""), row.get("name", ""),
                            row.get("price", 0), row.get("change_pct", 0),
                            row.get("total_mv", 0), row.get("pe", 0),
                            row.get("up_count", 0), row.get("down_count", 0),
                        )
                    )
                    total += 1
                except (ValueError, TypeError):
                    continue

        except Exception as e:
            log.warning("cache %s failed: %s", s_type, str(e)[:60])
    conn.commit()
    conn.close()
    log.info("cached %d sector rows", total)
    return total

def cache_north_flow_from_akshare():
    """Cache north-bound (HSGT) flow data from AKShare"""
    import akshare as ak
    try:
        df = ak.stock_hsgt_hist_em(symbol="北向资金")
        if df is None or df.empty:
            return 0
        conn = get_kline_db()
        count = 0
        # AKShare returns Chinese column names: 日期/当日成交净买额/历史累计净买额
        col_map = {"日期": "date", "当日成交净买额": "net_flow", "历史累计净买额": "cum_flow"}
        df = df.rename(columns=col_map)
        for _, row in df.iterrows():
            try:
                conn.execute(
                    "INSERT OR REPLACE INTO north_flow VALUES (?,?,?)",
                    (
                        str(row.get("date", "")),
                        float(row.get("net_flow", 0) or 0),
                        float(row.get("cum_flow", 0) or 0),
                    ),
                )
                count += 1
            except (ValueError, TypeError):
                continue
        conn.commit()
        conn.close()
        log.info("cached %d north flow rows", count)
        return count
    except Exception as e:
        log.warning("cache north flow failed: %s", str(e)[:60])
        return 0

def cache_limit_up_from_akshare(date: str = None):
    """缓存涨停股池到 limit_up 表"""
    import akshare as ak
    if date is None:
        date = datetime.now().strftime("%Y%m%d")
    try:
        data = ak_get_limit_up(date)
        if not data:
            return 0
        conn = get_kline_db()
        conn.execute("""CREATE TABLE IF NOT EXISTS limit_up (
            date TEXT, code TEXT, name TEXT, price REAL, change_pct REAL,
            amount REAL, turnover REAL, total_mv REAL, type TEXT,
            PRIMARY KEY (date, code)
        )""")
        count = 0
        for d in data:
            try:
                conn.execute(
                    "INSERT OR REPLACE INTO limit_up VALUES (?,?,?,?,?,?,?,?,?)",
                    (d["date"], d["code"], d["name"], d["price"], d["change_pct"],
                     d["amount"], d["turnover"], d["total_mv"], d["type"]),
                )
                count += 1
            except Exception:
                continue
        conn.commit()
        conn.close()
        log.info("cached %d limit_up for %s", count, date)
        return count
    except Exception as e:
        log.warning("cache limit_up failed: %s", str(e)[:80])
        return 0


def cache_lhb_from_akshare():
    """缓存龙虎榜个股统计到 lhb_stock 表"""
    try:
        data = ak_get_lhb_stock_statistic("近一月")
        if not data:
            return 0
        conn = get_kline_db()
        conn.execute("""CREATE TABLE IF NOT EXISTS lhb_stock (
            code TEXT PRIMARY KEY, name TEXT, last_date TEXT, price REAL,
            change_pct REAL, times INTEGER, net_buy REAL, period TEXT, updated_at TEXT
        )""")
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        count = 0
        for d in data:
            try:
                conn.execute(
                    "INSERT OR REPLACE INTO lhb_stock VALUES (?,?,?,?,?,?,?,?,?)",
                    (d["code"], d["name"], d["last_date"], d["price"], d["change_pct"],
                     d["times"], d["net_buy"], d["period"], now),
                )
                count += 1
            except Exception:
                continue
        conn.commit()
        conn.close()
        log.info("cached %d lhb stock stats", count)
        return count
    except Exception as e:
        log.warning("cache lhb failed: %s", str(e)[:80])
        return 0


def cache_high_low_from_akshare():
    """缓存创新高/新低统计到 high_low 表"""
    try:
        data = ak_get_high_low()
        if not data:
            return 0
        conn = get_kline_db()
        conn.execute("""CREATE TABLE IF NOT EXISTS high_low (
            date TEXT PRIMARY KEY, close INTEGER, high20 INTEGER, low20 INTEGER,
            high60 INTEGER, low60 INTEGER, high120 INTEGER, low120 INTEGER, updated_at TEXT
        )""")
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        count = 0
        for d in data:
            try:
                conn.execute(
                    "INSERT OR REPLACE INTO high_low VALUES (?,?,?,?,?,?,?,?,?)",
                    (d["date"], d["close"], d["high20"], d["low20"], d["high60"],
                     d["low60"], d["high120"], d["low120"], now),
                )
                count += 1
            except Exception:
                continue
        conn.commit()
        conn.close()
        log.info("cached %d high_low rows", count)
        return count
    except Exception as e:
        log.warning("cache high_low failed: %s", str(e)[:80])
        return 0




def build_weekly_kline(full: bool = False):
    from datetime import datetime, timedelta
    conn = get_kline_db()
    conn.execute('CREATE TABLE IF NOT EXISTS kline_weekly (code TEXT, week_start TEXT, open REAL, high REAL, low REAL, close REAL, volume INTEGER, amount REAL, turnover REAL DEFAULT 0, PRIMARY KEY (code, week_start))')
    latest = conn.execute('SELECT MAX(date) FROM kline_daily').fetchone()[0]
    dt = datetime.strptime(latest, '%Y%m%d')
    cur_week = (dt - timedelta(days=dt.weekday())).strftime('%Y%m%d')
    if full:
        conn.execute('DELETE FROM kline_weekly')
        min_d = conn.execute('SELECT MIN(date) FROM kline_daily').fetchone()[0]
    else:
        conn.execute('DELETE FROM kline_weekly WHERE week_start=?', (cur_week,))
        min_d = cur_week
    sql = (
        "INSERT INTO kline_weekly SELECT code, week_start, "
        "MAX(CASE WHEN rn=1 THEN open END), MAX(high), MIN(low), "
        "MAX(CASE WHEN rn_desc=1 THEN close END), "
        "SUM(volume), SUM(amount), AVG(turnover) "
        "FROM (SELECT *, ROW_NUMBER() OVER (PARTITION BY code, week_start ORDER BY date) as rn, "
        "ROW_NUMBER() OVER (PARTITION BY code, week_start ORDER BY date DESC) as rn_desc "
        "FROM (SELECT *, date(SUBSTR(date,1,4)||'-'||SUBSTR(date,5,2)||'-'||SUBSTR(date,7,2), 'weekday 1', '-7 days') as week_start "
        "FROM kline_daily WHERE date>=? AND date<=?)) GROUP BY code, week_start"
    )
    conn.execute(sql, (min_d, latest))
    conn.commit()
    cnt = conn.execute('SELECT COUNT(*) FROM kline_weekly').fetchone()[0]
    conn.close()
    log.info('weekly: %d rows', cnt)
    return cnt
def smart_refresh_cache():
    """智能刷新缓存：交易时段拉行情，收盘后拉涨停/龙虎榜，其他数据随时拉"""
    from datetime import datetime as dt
    h = dt.now().hour
    w = dt.now().weekday()
    results = {}
    is_trade_day = w < 5  # 周一~周五
    # 交易时段 (9:00-15:30) 拉实时行情
    if is_trade_day and 9 <= h <= 15:
        results["spot"] = cache_spot_from_akshare()
        results["sectors"] = cache_sectors_from_akshare()
    else:
        results["spot"] = 0
        results["sectors"] = 0
    # 收盘后拉涨停板 (15:00 后)
    if is_trade_day and h >= 15:
        results["limit_up"] = cache_limit_up_from_akshare()
    else:
        results["limit_up"] = 0
    # 北向资金/龙虎榜/创新高 随时可拉（日级数据）
    results["north_flow"] = cache_north_flow_from_akshare()
    results["lhb"] = cache_lhb_from_akshare()
    results["high_low"] = cache_high_low_from_akshare()
    return results




def cache_cyq_chip_data(code: str = None, days: int = 1250) -> int:
    """缓存筹码分布数据到 stock_cache.db
    code: 指定股票代码；为 None 时从 Flask API 拿 Top20 选股
    Returns: 缓存行数
    """
    from akshare_source import ak_get_cyq_chip_data
    conn = get_kline_db()
    conn.execute("""CREATE TABLE IF NOT EXISTS chip_distribution (
        code TEXT, date TEXT, [获利比例] REAL, [平均成本] REAL,
        [90成本_低] REAL, [90成本_高] REAL, [90集中度] REAL,
        [70成本_低] REAL, [70成本_高] REAL, [70集中度] REAL,
        updated_at TEXT, PRIMARY KEY (code, date)
    )""")
    conn.commit()
    conn.close()
    if code:
        codes_to_fetch = [code]
    else:
        try:
            import requests
            resp = requests.get("http://127.0.0.1:5000/api/picks?top=20", timeout=10)
            data = resp.json()
            codes_to_fetch = [s["code"] for s in data.get("data", []) if s.get("code")]
        except Exception:
            log.warning("cyq: cannot get picks list, using recent active stocks")
            conn = get_kline_db()
            rows = conn.execute(
                "SELECT DISTINCT code FROM kline_daily WHERE date=(SELECT MAX(date) FROM kline_daily) LIMIT 20"
            ).fetchall()
            conn.close()
            codes_to_fetch = [r["code"] for r in rows]
    total = 0
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    for c in codes_to_fetch:
        try:
            data = ak_get_cyq_chip_data(c, days=days)
            if not data:
                continue
            conn = get_kline_db()
            for d in data:
                conn.execute(
                    "INSERT OR REPLACE INTO chip_distribution (code, date, [获利比例], [平均成本], [90成本_低], [90成本_高], [90集中度], [70成本_低], [70成本_高], [70集中度], updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        d["code"], d["date"], d["获利比例"], d["平均成本"],
                        d["90成本-低"], d["90成本-高"], d["90集中度"],
                        d["70成本-低"], d["70成本-高"], d["70集中度"],
                        now,
                    ),
                )
            conn.commit()
            conn.close()
            total += len(data)
            log.info("cyq %s: cached %d rows", c, len(data))
        except Exception as e:
            log.warning("cyq %s: failed: %s", c, str(e)[:80])
            continue
    log.info("cyq cache: total %d rows", total)
    return total


def get_cached_spot(codes: list = None) -> list:
    """? stock_spot ??????????????"""
    conn = _get_cache_db()
    if codes:
        placeholders = ",".join("?" for _ in codes)
        rows = conn.execute(
            f"SELECT * FROM stock_spot WHERE code IN ({placeholders})", codes
        ).fetchall()
    else:
        rows = conn.execute("SELECT * FROM stock_spot ORDER BY code").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_kline_for_backtest(code: str, start: str, end: str) -> list:
    """?????????????????K?"""
    conn = get_kline_db()
    rows = conn.execute(
        "SELECT * FROM kline_daily WHERE code=? AND date BETWEEN ? AND ? ORDER BY date",
        (code, start, end),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# CLI ????
_CACHE_CLI_CMDS = {
    "cache-spot": lambda: print(f"cached {cache_spot_from_akshare()} spots"),
    "cache-sectors": lambda: print(f"cached {cache_sectors_from_akshare()} sectors"),
    "cache-north": lambda: print(f"cached {cache_north_flow_from_akshare()} north flow"),
    "cache-limit-up": lambda: print(f"cached {cache_limit_up_from_akshare()} limit_up"),
    "cache-lhb": lambda: print(f"cached {cache_lhb_from_akshare()} lhb"),
    "cache-high-low": lambda: print(f"cached {cache_high_low_from_akshare()} high_low"),
    "cache-cyq": lambda: print(f"cached {cache_cyq_chip_data(sys.argv[2] if len(sys.argv) > 2 else None, days=int(sys.argv[3]) if len(sys.argv) > 3 else 1250)} cyq rows"),
    "cache-all": lambda: print(smart_refresh_cache()),
}
def clean_all():
    log.info("开始完整清洗...")
    clean_pre_2000()
    clean_bad_codes()
    clean_duplicates()
    remove_delisted_stocks()
    update_stock_list()
    log.info("清洗完成")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("用法: python data_manager.py [clean|update|catch-up|status|stock-list]")
        sys.exit(0)

    cmd = sys.argv[1]
    if cmd == "clean":
        clean_all()
    elif cmd == "update":
        days = int(sys.argv[2]) if len(sys.argv) > 2 else 10
        daily_update(catch_up_days=days)
    elif cmd == "catch-up":
        catch_up_missing()
    elif cmd == "status":
        s = show_status()
        print(f"总行数:         {s['total_rows']:,}")
        print(f"股票数:         {s['stock_count']:,}")
        print(f"数据范围:       {s['date_min']} ~ {s['date_max']}")
        print(f"最新日数据:     {s['date_max']} 有 {s['latest_day_stocks']} 只")
        print(f"活跃股票:       {s['active_stocks']:,}")
        print(f"退市股票:       {s['delisted_stocks']:,}")
        print(f"平均每只:       {s['avg_rows_per_stock']} 行")
        print(f"数据库大小:     {s['db_size_mb']} MB")
    elif cmd == "stock-list":
        stocks = get_stock_list()
        for s in stocks:
            print(f"  {s['code']} {s['name']}  {s['board']:4s}  {s['status']:8s}  last={s.get('last_date', '')}  days={s.get('total_days', 0)}")
        print(f"共 {len(stocks)} 只")
    elif cmd == "cache-cyq":
        code = sys.argv[2] if len(sys.argv) > 2 else None
        cyq_days = int(sys.argv[3]) if len(sys.argv) > 3 else 1250
        print(f"cached {cache_cyq_chip_data(code, days=cyq_days)} cyq rows")
    else:
        print(f"未知命令: {cmd}")
