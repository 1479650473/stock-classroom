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

if getattr(sys, "frozen", False):
    # PyInstaller 打包: __file__ 在临时解压目录, data 以 exe 目录(或 SC_DATA_DIR)为准
    _exe_dir = os.path.dirname(sys.executable)
    DATA_DIR = os.environ.get("SC_DATA_DIR") or os.path.join(_exe_dir, "data")
    BASE_DIR = os.path.join(_exe_dir, "backend")
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    DATA_DIR = os.environ.get("SC_DATA_DIR") or os.path.join(os.path.dirname(BASE_DIR), "data")
KLINE_DB = os.path.join(DATA_DIR, "kline.db")
CACHE_DB = os.path.join(DATA_DIR, "stock_cache.db")
MINUTE_DB = os.path.join(DATA_DIR, "minute.db")  # 分钟线独立库(体量大, 便于备份/迁移)

# basicConfig 只在 CLI 入口执行（见 __main__），避免 import 时污染根 logger
log = logging.getLogger("data_mgr")

SINA_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
WORKERS = 15   # 15 线程并发


def get_kline_db():
    conn = sqlite3.connect(KLINE_DB, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA cache_size=-400000")
    return conn


def get_minute_db():
    conn = sqlite3.connect(MINUTE_DB, timeout=60)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA cache_size=-200000")
    return conn


def ensure_minute_tables(freqs=(5,)):
    """建分钟线表 kline_min{freq}: code + dt('YYYYMMDDHHMM') + OHLCVA(不复权, volume=股/amount=元)."""
    conn = get_minute_db()
    try:
        for f in freqs:
            conn.execute(
                f"""CREATE TABLE IF NOT EXISTS kline_min{f} (
                    code TEXT NOT NULL,
                    dt   TEXT NOT NULL,
                    open REAL, high REAL, low REAL, close REAL,
                    volume REAL, amount REAL,
                    PRIMARY KEY (code, dt)
                ) WITHOUT ROWID"""
            )
            conn.execute(f"CREATE INDEX IF NOT EXISTS idx_min{f}_dt ON kline_min{f}(dt)")
        conn.commit()
    finally:
        conn.close()


def insert_minute_rows(conn, freq, rows):
    """批量 upsert 分钟线行 [(code, dt, o,h,l,c, v,a)]. 返回写入行数."""
    if not rows:
        return 0
    table = f"kline_min{int(freq)}"
    conn.executemany(
        f"INSERT OR REPLACE INTO {table} (code,dt,open,high,low,close,volume,amount) "
        "VALUES (?,?,?,?,?,?,?,?)",
        rows,
    )
    return len(rows)


# ════════════════════════════════════════════════════════
#  数据获取函数已统一到 akshare_source.py
#  ak_fetch_kline, ak_fetch_index_kline, ak_get_all_stocks
#  均从 akshare_source 模块导入
# ════════════════════════════════════════════════════════


# ════════════════════════════════════════════════════════
#  年度分表维护（kline_daily 是 UNION ALL 视图，写入/删除必须落到 kline_YYYY）
# ════════════════════════════════════════════════════════
KLINE_COLS = "code,date,open,high,low,close,volume,amount,turnover"


def _year_tables(conn):
    """已有的 kline_YYYY 年度分表名（升序）"""
    return [r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' "
        "AND name GLOB 'kline_[0-9][0-9][0-9][0-9]' ORDER BY name")]


def _rebuild_kline_view(conn):
    """按现有年度分表重建 kline_daily 视图"""
    tables = _year_tables(conn)
    if not tables:
        return
    sql = "CREATE VIEW kline_daily AS " + " UNION ALL ".join(
        f"SELECT {KLINE_COLS} FROM {t}" for t in tables)
    conn.execute("DROP VIEW IF EXISTS kline_daily")
    conn.execute(sql)


def ensure_year_table(conn, year):
    """创建年度分表（如不存在）并重建视图。返回是否新建"""
    year = str(year)
    tname = f"kline_{year}"
    if tname in _year_tables(conn):
        return False
    conn.execute(f"""CREATE TABLE IF NOT EXISTS {tname} (
        code TEXT, date TEXT, open REAL, high REAL, low REAL, close REAL,
        volume INTEGER, amount REAL, turnover REAL DEFAULT 0,
        PRIMARY KEY (code, date))""")
    conn.execute(f"CREATE INDEX IF NOT EXISTS idx_{year} ON {tname}(code, date)")
    _rebuild_kline_view(conn)
    log.info("创建年度分表 %s 并重建 kline_daily 视图", tname)
    return True


def _delete_from_shards(conn, where, params=()):
    """对所有年度分表执行 DELETE（kline_daily 是视图，不能直接删）"""
    total = 0
    for t in _year_tables(conn):
        total += conn.execute(f"DELETE FROM {t} WHERE {where}", params).rowcount
    return total


def _bulk_insert_kline(conn, rows, replace=True):
    """按年份分组批量写入 K 线，自动建年度分表。返回 (写入行数, 跳过行数)"""
    by_year = {}
    skipped = 0
    for r in rows:
        year = str(r[1])[:4]
        if len(year) != 4 or not year.isdigit():
            skipped += 1
            continue
        row = tuple(r) if len(r) >= 9 else tuple(r) + (0,)
        by_year.setdefault(year, []).append(row)
    verb = "INSERT OR REPLACE" if replace else "INSERT OR IGNORE"
    inserted = 0
    for year, batch in by_year.items():
        try:
            ensure_year_table(conn, year)
            conn.executemany(
                f"{verb} INTO kline_{year} ({KLINE_COLS}) VALUES (?,?,?,?,?,?,?,?,?)", batch)
            inserted += len(batch)
        except sqlite3.Error as e:
            skipped += len(batch)
            log.warning("写入 kline_%s 失败 (%d 行): %s", year, len(batch), e)
    return inserted, skipped


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
    # 预建当年与次年的年度分表，避免跨年时写入失败
    year = datetime.now().year
    ensure_year_table(conn, year)
    ensure_year_table(conn, year + 1)
    conn.commit()
    conn.close()


# ════════════════════════════════════════════════════════
#  清洗模块
# ════════════════════════════════════════════════════════
def clean_pre_2000():
    conn = get_kline_db()
    n = _delete_from_shards(conn, "date < '20000101'")
    conn.commit(); conn.close()
    if n: log.info("清理 2000 年前数据: %d 行", n)
    return n

def clean_bad_codes():
    conn = get_kline_db()
    n1 = _delete_from_shards(conn, "code NOT GLOB '[0-9][0-9][0-9][0-9][0-9][0-9]'")
    n2 = _delete_from_shards(conn, "code GLOB '8*'")
    conn.commit(); conn.close()
    if n1 or n2: log.info("清理异常代码: %d + %d", n1, n2)
    return n1 + n2

def clean_duplicates():
    conn = get_kline_db()
    n = 0
    for t in _year_tables(conn):
        n += conn.execute(
            f"DELETE FROM {t} WHERE rowid NOT IN (SELECT MIN(rowid) FROM {t} GROUP BY code, date)"
        ).rowcount
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
    tables = _year_tables(conn)
    for i in range(0, len(delisted), 100):
        batch = delisted[i:i+100]
        ph = ",".join("?" for _ in batch)
        for t in tables:
            total += conn.execute(f"DELETE FROM {t} WHERE code IN ({ph})", batch).rowcount
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

    # 批量写入（按年份分组 + executemany + 自动建分表）
    log.info("正在写入 %d 行数据...", len(batch_rows))
    conn = get_kline_db()
    inserted, write_skipped = _bulk_insert_kline(conn, batch_rows, replace=True)
    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    conn.commit()
    conn.close()
    elapsed = time.time() - t0

    update_stock_list()
    status = "ok" if errors < len(todo) * 0.5 else "partial_fail"
    _log_update(target_date, len(stocks), len(todo), inserted, status,
                f"+{inserted} 行, 拉取失败 {errors}, 写入跳过 {write_skipped}")
    log.info("更新完成: +%d 行, %d 只写入, 拉取失败 %d, 写入跳过 %d, 耗时 %.0f 秒",
             inserted, len(set(r[0] for r in batch_rows)), errors, write_skipped, elapsed)
    return True


def _log_update(update_date, stocks_total, stocks_new, rows_added, status="ok", message=""):
    try:
        conn = get_kline_db()
        conn.execute("INSERT INTO data_update_log (update_date, stocks_total, stocks_new, rows_added, status, message) VALUES (?,?,?,?,?,?)",
                     (update_date, stocks_total, stocks_new, rows_added, status, message))
        conn.commit(); conn.close()
    except Exception:
        pass


def _last_db_date(conn):
    row = conn.execute("SELECT MAX(date) FROM kline_daily").fetchone()
    return str(row[0]) if row and row[0] else None


def update_codes(codes, end_date: str = None, catch_up_days: int = None, workers: int = 15,
                 progress=None, timeout_each: float = 20.0) -> dict:
    """定向增量更新一批代码(如量化池/选股池)的 K 线。

    - 逐 code 并行拉取(接 akshare_source.ak_fetch_kline, 内层有重试+超时+3源回退)
    - catch_up_days: 抓取窗口(bar数). None → 按 DB 最新日期到今天的缺口自动算, 至少 60,
      保证 REVERSAL/VOLATILITY 因子(需前 20 根)在该截面有连续历史, 不退化/断历史.
    - 超时兜底: 某 code 挂起超时 → 记 skipped, 不阻塞整批
    - end_date 默认为最近交易日(昨日); 返回 {updated, skipped, rows_added, distribution}
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed, TimeoutError as _TE
    if end_date is None:
        # 目标日期应为"今天"(或最新交易日), 让窗口覆盖到最新; 抓取上限由源决定.
        end_date = datetime.now().strftime("%Y%m%d")
    # 自动算抓取窗口: 从 DB 最新日到 end_date 的日历缺口 + warmup 缓冲
    if catch_up_days is None:
        try:
            _c = get_kline_db()
            last = _last_db_date(_c)
            _c.close()
            if last:
                gap = (datetime.strptime(str(end_date), "%Y%m%d") - datetime.strptime(str(last), "%Y%m%d")).days
                catch_up_days = max(60, int(gap * 1.6) + 40)   # 1.6 倍日历日≈交易日, +40 warmup
            else:
                catch_up_days = 90
        except Exception:
            catch_up_days = 90
    codes = list(codes)
    total = len(codes)
    updated, skipped, errors, rows_added = 0, 0, 0, 0
    dist = {}
    t0 = time.time()

    def _fetch(c):
        rows = ak_fetch_kline(c, days=catch_up_days)
        # 保留全部抓取行(已限定 catch_up_days 窗口, INSERT OR REPLACE 去重) ——
        # 不能只留 end_date: REVERSAL/VOLATILITY 因子需要该日前 20 根历史, 只留当日会断历史
        return rows, c

    batch_rows = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futs = {pool.submit(_fetch, c): c for c in codes}
        for f in as_completed(futs):
            c = futs[f]
            try:
                rows, _ = f.result(timeout=timeout_each)
            except _TE:
                skipped += 1
                errors += 1
                if progress:
                    progress(f"{c} 超时(>{timeout_each:.0f}s) 跳过", c)
                continue
            except Exception as e:
                skipped += 1
                errors += 1
                if progress:
                    progress(f"{c} 拉取失败 {str(e)[:30]}", c)
                continue
            if rows:
                updated += 1
                batch_rows.extend(rows)
                rows_added += len(rows)
                dist[str(rows[-1][1])] = dist.get(str(rows[-1][1]), 0) + 1
            else:
                errors += 1
            done = updated + skipped
            if progress and (done % 50 == 0 or done == total):
                progress(f"[{done}/{total}] +{rows_added} 行", None)

    if batch_rows:
        conn = get_kline_db()
        inserted, write_skipped = _bulk_insert_kline(conn, batch_rows, replace=True)
        try:
            conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")   # app 可能持有 DB, 失败不致命
        except Exception:
            pass
        conn.commit()
        conn.close()
        rows_added = inserted
    else:
        insert_skipped = 0

    return {"updated": updated, "skipped": skipped, "errors": errors,
            "rows_added": rows_added, "total": total,
            "elapsed": time.time() - t0, "distribution": dist}


def update_pool(pool=None, end_date: str = None, progress=None, workers: int = 15):
    """刷新量化池(默认 build_wide_pool 的 287 只)到最新 —— as_of 前进的关键。"""
    if pool is None:
        from backend.strategy.factor_selector import build_wide_pool
        pool = build_wide_pool()
    return update_codes(pool, end_date=end_date, progress=progress, workers=workers)


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
        try:
            rows = ak_fetch_kline(code, days=days)
        except Exception as e:
            log.warning("  %s %s 抓取失败(跳过): %s", code, s["name"], str(e)[:60])
            continue
        if not rows:
            continue
        conn = get_kline_db()
        added, skipped = _bulk_insert_kline(conn, rows, replace=False)
        conn.commit()
        conn.close()
        total_added += added
        log.info("  %s %s: +%d 行", code, s["name"], added)

    log.info("补全完成: +%d 行, 耗时 %.0f 秒", total_added, time.time() - t0)
    return total_added


# ════════════════════════════════════════════════════════
#  公共查询接口（给 app.py 调用）
# ════════════════════════════════════════════════════════

def get_kline_data(code: str, days: int = 180, conn=None) -> List[Dict]:
    """从数据库读取 K 线数据（sh/sz/bj 前缀为指数代码，同样在 kline_daily 中）
    conn: 可选，传入已有连接以避免批量调用时反复开关连接
    """
    own = conn is None
    if own:
        conn = get_kline_db()
    rows = conn.execute(
        "SELECT * FROM kline_daily WHERE code=? ORDER BY date DESC LIMIT ?",
        (code, days)
    ).fetchall()
    if own:
        conn.close()
    result = [dict(r) for r in rows]
    result.reverse()
    return result


def compute_factor_picks(kline_days: int = 60) -> List[Dict]:
    """多因子评分选股（全部候选按总分降序返回，调用方自行切片取 Top N）
    供 Flask /api/picks 与内部缓存任务（如 CYQ）共用，全程复用单个连接。
    """
    from factor_engine import FactorScorer
    conn = get_kline_db()
    rows = conn.execute(
        "SELECT code, name FROM stock_list WHERE status='active' ORDER BY code"
    ).fetchall()
    candidates = []
    for r in rows:
        code, name = str(r["code"]), str(r["name"])
        if code[:2] not in ("60", "00", "30", "68"):
            continue
        if "ST" in name:
            continue
        candidates.append((code, name))
    scorer = FactorScorer()
    results = []
    for code, name in candidates:
        kd = get_kline_data(code, kline_days, conn=conn)
        if not kd or len(kd) < 2:
            continue
        last, prev = kd[-1], kd[-2]
        close, pv = last["close"], prev["close"]
        vol = int(last.get("volume", 0))
        if vol <= 0:
            continue
        chg = round((close - pv) / pv * 100, 2) if pv else 0.0
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
    conn.close()
    results.sort(key=lambda x: x["score"], reverse=True)
    return results


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
    """缓存全市场实时快照到 stock_spot(东财优先, 反爬时回退新浪直连)."""
    import akshare as ak
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    rows = []
    # ① 东财实时快照
    try:
        df = ak.stock_zh_a_spot_em()
        if df is not None and not df.empty:
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
            for _, row in df.iterrows():
                try:
                    rows.append((
                        str(row.get("code", "")), str(row.get("name", "")),
                        float(row.get("price", 0) or 0), float(row.get("open", 0) or 0),
                        float(row.get("high", 0) or 0), float(row.get("low", 0) or 0),
                        int(float(row.get("volume", 0) or 0)), float(row.get("amount", 0) or 0),
                        float(row.get("change_pct", 0) or 0), float(row.get("change_amount", 0) or 0),
                        float(row.get("turnover", 0) or 0), float(row.get("pe", 0) or 0),
                        float(row.get("pb", 0) or 0), float(row.get("total_mv", 0) or 0),
                        float(row.get("circ_mv", 0) or 0), now,
                    ))
                except (ValueError, TypeError):
                    continue
    except Exception as e:
        log.warning("cache spot(东财) failed: %s", str(e)[:60])
    # ② 新浪直连回退(无 pe/pb/市值)
    if not rows:
        try:
            conn = get_kline_db()
            codes = [(str(r[0]), str(r[1])) for r in conn.execute(
                "SELECT code, name FROM stock_list WHERE status='active'")]
            conn.close()
            quotes = fetch_realtime_prices(codes)
            for q in quotes:
                rows.append((
                    str(q.get("code", "")), str(q.get("name", "")),
                    float(q.get("price", 0) or 0), float(q.get("open", 0) or 0),
                    float(q.get("high", 0) or 0), float(q.get("low", 0) or 0),
                    int(q.get("volume", 0) or 0), float(q.get("amount", 0) or 0),
                    float(q.get("change_pct", 0) or 0), 0.0,
                    float(q.get("turnover", 0) or 0), 0.0, 0.0, 0.0, 0.0, now,
                ))
        except Exception as e:
            log.warning("cache spot(新浪) failed: %s", str(e)[:60])
    if not rows:
        return 0
    conn = _get_cache_db()
    conn.executemany(
        """INSERT OR REPLACE INTO stock_spot
        (code, name, price, open, high, low, volume, amount,
         change_pct, change_amount, turnover, pe, pb, total_mv, circ_mv, updated_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        rows,
    )
    conn.commit()
    conn.close()
    log.info("cached %d spots at %s", len(rows), now)
    return len(rows)

def cache_sectors_from_akshare():
    """Cache industry/concept sector data from AKShare"""
    import akshare as ak
    conn = get_kline_db()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    # 清理旧版本列错位写入的脏数据（type 列被写成了 0）
    conn.execute("DELETE FROM sector_data WHERE type NOT IN ('industry', 'concept')")
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
            rows = []
            for _, row in df.iterrows():
                try:
                    rows.append((
                        str(row.get("code", "")), str(row.get("name", "")),
                        s_type,
                        float(row.get("change_pct", 0) or 0),
                        float(row.get("change_amount", 0) or 0),
                        int(float(row.get("up_count", 0) or 0)),
                        int(float(row.get("down_count", 0) or 0)),
                        now,
                    ))
                except (ValueError, TypeError):
                    continue
            conn.executemany("INSERT OR REPLACE INTO sector_data VALUES (?,?,?,?,?,?,?,?)", rows)
            total += len(rows)
        except Exception as e:
            log.warning("cache %s failed: %s", s_type, str(e)[:60])
    conn.commit()
    conn.close()
    log.info("cached %d sector rows", total)
    return total

# ════════════════════════════════════════════════════════
#  ETF 数据 (etf_list 全市场列表 + etf_daily 全历史K线, 独立表不并入 kline_daily)
# ════════════════════════════════════════════════════════
def init_etf_tables():
    conn = get_kline_db()
    conn.execute("""CREATE TABLE IF NOT EXISTS etf_list (
        code TEXT PRIMARY KEY, name TEXT, type TEXT, updated_at TEXT)""")
    conn.execute("""CREATE TABLE IF NOT EXISTS etf_daily (
        code TEXT, date TEXT, open REAL, high REAL, low REAL, close REAL,
        volume INTEGER, amount REAL, turnover REAL DEFAULT 0,
        PRIMARY KEY (code, date))""")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_etf_daily_code ON etf_daily(code, date)")
    conn.commit()
    conn.close()


def cache_etf_list_from_akshare() -> int:
    """全市场 ETF 列表落库(东财 spot, ~1600 只)."""
    from akshare_source import ak_get_etf_list
    data = ak_get_etf_list() or []
    if not data:
        return 0
    conn = get_kline_db()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    for d in data:
        conn.execute("INSERT OR REPLACE INTO etf_list (code, name, type, updated_at) VALUES (?,?,?,?)",
                     (str(d.get("code", "")), str(d.get("name", "")),
                      str(d.get("type", "") or ""), now))
    conn.commit()
    conn.close()
    log.info("cached %d etf list rows", len(data))
    return len(data)


def get_etf_list(search: str = "", etype: str = "") -> List[Dict]:
    conn = get_kline_db()
    sql = "SELECT * FROM etf_list WHERE 1=1"
    params = []
    if search:
        sql += " AND (code LIKE ? OR name LIKE ?)"
        params += [f"%{search}%", f"%{search}%"]
    if etype:
        sql += " AND type = ?"
        params.append(etype)
    sql += " ORDER BY code"
    rows = conn.execute(sql, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_etf_kline(code: str, days: int = 250) -> List[Dict]:
    conn = get_kline_db()
    rows = conn.execute(
        "SELECT date, open, high, low, close, volume, amount, turnover FROM etf_daily "
        "WHERE code=? ORDER BY date DESC LIMIT ?", (code, days)).fetchall()
    conn.close()
    out = [dict(r) for r in reversed(rows)]
    return out


def get_etf_compare(codes: List[str], days: int = 250) -> dict:
    """多只 ETF 归一化对比(各自首日 close=1). 返回 {dates, series: [{code, name, values}]}."""
    conn = get_kline_db()
    dates = None
    series = []
    for code in codes:
        rows = conn.execute(
            "SELECT date, close FROM etf_daily WHERE code=? ORDER BY date DESC LIMIT ?",
            (code, days)).fetchall()
        rows = list(reversed(rows))
        if not rows:
            continue
        base = rows[0][1] or 1.0
        ds = [r[0] for r in rows]
        if dates is None:
            dates = ds
        name_row = conn.execute("SELECT name FROM etf_list WHERE code=?", (code,)).fetchone()
        series.append({"code": code, "name": (name_row[0] if name_row else code),
                       "values": [round((r[1] or 0) / base, 4) for r in rows]})
    conn.close()
    return {"dates": dates or [], "series": series}


_ERR_SAMPLE_MAX = 3          # T-DATA-02: 每步最多记 3 条取数异常样例


def _record_fetch_error(samples, code, exc, label):
    """记录**前 N 条**取数异常（T-DATA-02，2026-10-12）。

    为什么需要：2026-10-12 东财系瞬时阻断时 etf 1624/1624、资金流 5205/5205 全失败，
    但原来的 `except Exception: rows = []` 把异常**丢弃且不写日志**，只把计数 +1 →
    事后完全无法归因（只能靠"同一晚新浪/baostock/同花顺都正常"旁证推断是源挂了）。

    只记前 _ERR_SAMPLE_MAX 条（5205 条全记会刷爆日志），样例同时带进返回值，
    由 update_daily 落进 data/update_marker.json，可事后取证。
    """
    if len(samples) < _ERR_SAMPLE_MAX:
        msg = "%s: %s" % (type(exc).__name__, str(exc)[:160])
        samples.append("%s|%s" % (code, msg))
        log.warning("%s 取数失败(样例 %d/%d) code=%s: %s",
                    label, len(samples), _ERR_SAMPLE_MAX, code, msg)


def update_etf_kline(codes=None, workers: int = 10, progress=None, budget_secs: int = 1200) -> dict:
    """ETF K线增量更新. codes=None 时自动选落后(etf_daily 最新 < 日K最新交易日)的 ETF.

    加时间预算(默认20分钟)防新浪反爬时阻塞后续步骤.
    Returns: {updated, skipped, errors, rows_added, total}
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed
    from akshare_source import ak_fetch_etf_kline
    if codes is None:
        conn = get_kline_db()
        latest = conn.execute("SELECT MAX(date) FROM kline_2026").fetchone()[0] or ""
        today = datetime.now().strftime("%Y%m%d")
        rows = conn.execute(
            "SELECT l.code, COALESCE((SELECT MAX(date) FROM etf_daily e WHERE e.code=l.code), '') md "
            "FROM etf_list l").fetchall()
        conn.close()
        codes = [str(r[0]) for r in rows if str(r[1]) < str(latest) or str(r[1]) == today]
    total = len(codes)
    updated = skipped = errors = rows_added = 0
    err_samples = []
    batch = []
    t0 = time.time()
    deadline = t0 + budget_secs

    def _fetch(c):
        rows = ak_fetch_etf_kline(c)
        return rows, c

    done = 0
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futs = {pool.submit(_fetch, c): c for c in codes}
        for f in as_completed(futs):
            c = futs[f]
            done += 1
            if time.time() > deadline:
                errors += total - done
                log.warning("etf: 时间预算 %ds 用尽, 跳过剩余 %d 只", budget_secs, total - done)
                break
            try:
                rows, _ = f.result(timeout=60)
            except Exception as e:
                rows = []
                _record_fetch_error(err_samples, c, e, "etf")
            if rows:
                updated += 1
                batch.extend(rows)
                rows_added += len(rows)
            else:
                errors += 1
            if progress and (done % 50 == 0 or done == total):
                progress(f"[{done}/{total}] +{rows_added} 行", None)
    if batch:
        conn = get_kline_db()
        ins, _ = _bulk_insert_etf(conn, batch)
        conn.commit()
        conn.close()
        rows_added = ins
    return {"updated": updated, "skipped": skipped, "errors": errors,
            "rows_added": rows_added, "total": total, "err_samples": err_samples,
            "elapsed": round(time.time() - t0, 1)}


def _bulk_insert_etf(conn, rows):
    """按行写 etf_daily (INSERT OR REPLACE). 返回 (写入行数, 跳过行数)."""
    skipped = 0
    clean = []
    for r in rows:
        if len(r) >= 8:
            clean.append(tuple(r[:8]) + (r[8] if len(r) > 8 else 0.0,))
        else:
            skipped += 1
    conn.executemany(
        "INSERT OR REPLACE INTO etf_daily (code,date,open,high,low,close,volume,amount,turnover) "
        "VALUES (?,?,?,?,?,?,?,?,?)", clean)
    return len(clean), skipped


# ════════════════════════════════════════════════════════
#  个股资金流日频 (fund_flow_daily, 东财 daykline 全历史)
# ════════════════════════════════════════════════════════
def init_fund_flow_tables():
    conn = get_kline_db()
    conn.execute("""CREATE TABLE IF NOT EXISTS fund_flow_daily (
        code TEXT, date TEXT, close REAL, change_pct REAL,
        main_net REAL, main_ratio REAL,
        super_net REAL, super_ratio REAL,
        large_net REAL, large_ratio REAL,
        medium_net REAL, medium_ratio REAL,
        small_net REAL, small_ratio REAL,
        PRIMARY KEY (code, date))""")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_ffd_code ON fund_flow_daily(code, date)")
    conn.commit()
    conn.close()


def get_fund_flow(code: str, days: int = 250) -> List[Dict]:
    """单只股票资金流历史(升序). 返回含 date/main_net/main_ratio 等字段."""
    conn = get_kline_db()
    rows = conn.execute(
        "SELECT date, close, change_pct, main_net, main_ratio, super_net, super_ratio, "
        "large_net, large_ratio, medium_net, medium_ratio, small_net, small_ratio "
        "FROM fund_flow_daily WHERE code=? ORDER BY date DESC LIMIT ?", (code, days)).fetchall()
    conn.close()
    out = [dict(r) for r in reversed(rows)]
    return out


def update_fund_flow(codes=None, workers: int = 10, progress=None, budget_secs: int = 1800) -> dict:
    """个股资金流增量更新(新浪主源, 幂等 INSERT OR REPLACE).

    codes=None 时自动选"落后股票"(fund_flow 最新日期 < 日K最新交易日) + 无记录新股,
    通常几十只 → 每日增量 ~1-2 分钟; 全量首拉用 scripts/rebuild_fund_flow.py.
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed
    from akshare_source import ak_fetch_fund_flow
    if codes is None:
        conn = get_kline_db()
        latest = conn.execute("SELECT MAX(date) FROM kline_2026").fetchone()[0] or ""
        today = datetime.now().strftime("%Y%m%d")
        rows = conn.execute(
            "SELECT s.code, COALESCE((SELECT MAX(date) FROM fund_flow_daily f WHERE f.code=s.code), '') md "
            "FROM stock_list s WHERE s.status='active' AND substr(s.code,1,2) IN ('00','30','60','68')").fetchall()
        conn.close()
        # 落后于日K最新 或 已有当日行(可能盘中快照, 收盘后重拉覆盖)
        codes = [str(r[0]) for r in rows if str(r[1]) < str(latest) or str(r[1]) == today]
    total = len(codes)
    updated = errors = rows_added = 0
    err_samples = []
    batch = []
    t0 = time.time()

    def _fetch(c):
        # 每只重置坏源缓存: 新浪限流是周期性窗口(数分钟), 不应触发 300s 全局暂停
        try:
            from akshare_source import _SRC_HEALTH
            _SRC_HEALTH.pop("sina", None)
            _SRC_HEALTH.pop("em", None)
        except Exception:
            pass
        return ak_fetch_fund_flow(c), c

    done = 0
    deadline = t0 + budget_secs
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futs = {pool.submit(_fetch, c): c for c in codes}
        for f in as_completed(futs):
            c = futs[f]
            done += 1
            if time.time() > deadline:
                errors += total - done
                log.warning("fund_flow: 时间预算 %ds 用尽, 跳过剩余 %d 只", budget_secs, total - done)
                break
            try:
                rows, _ = f.result(timeout=70)
            except Exception as e:
                rows = []
                _record_fetch_error(err_samples, c, e, "fund_flow")
            if rows:
                updated += 1
                batch.extend(rows)
                rows_added += len(rows)
            else:
                errors += 1
            if progress and (done % 100 == 0 or done == total):
                progress(f"[{done}/{total}] +{rows_added} 行", None)
    if batch:
        conn = get_kline_db()
        conn.executemany(
            "INSERT OR REPLACE INTO fund_flow_daily "
            "(code,date,close,change_pct,main_net,main_ratio,super_net,super_ratio,"
            "large_net,large_ratio,medium_net,medium_ratio,small_net,small_ratio) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)", batch)
        conn.commit()
        conn.close()
        rows_added = len(batch)
    return {"updated": updated, "errors": errors, "rows_added": rows_added,
            "total": total, "err_samples": err_samples,
            "elapsed": round(time.time() - t0, 1)}


# ════════════════════════════════════════════════════════
#  周K/月K (从日K聚合, kline_weekly / kline_monthly)
# ════════════════════════════════════════════════════════
def _period_agg(data, keyfn):
    """data: [(date,o,h,l,c,vol,amt,turn)] 升序 → [(key,last_date,o,h,l,c,vol,amt,turn)]."""
    out = []
    cur_key = None
    o = h = l = c = 0.0
    vol = amt = turn_n = 0
    turn_sum = 0.0
    last_date = None
    for r in data:
        k = keyfn(r[0])
        if k != cur_key:
            if cur_key is not None:
                out.append((cur_key, last_date, o, h, l, c, int(vol), amt,
                            round(turn_sum / turn_n, 4) if turn_n else 0.0))
            cur_key = k
            o, h, l, c = r[1], r[2], r[3], r[4]
            vol, amt, turn_sum, turn_n = 0, 0.0, 0.0, 0
        else:
            if r[2] > h:
                h = r[2]
            if r[3] < l:
                l = r[3]
        c = r[4]
        vol += r[5] or 0
        amt += r[6] or 0
        if r[7]:
            turn_sum += r[7]
            turn_n += 1
        last_date = r[0]
    if cur_key is not None:
        out.append((cur_key, last_date, o, h, l, c, int(vol), amt,
                    round(turn_sum / turn_n, 4) if turn_n else 0.0))
    return out


def _week_key(d: str) -> str:
    from datetime import datetime as _dt, timedelta as _td
    dt = _dt(int(d[:4]), int(d[4:6]), int(d[6:8]))
    return (dt - _td(days=dt.weekday())).strftime("%Y%m%d")


def _month_key(d: str) -> str:
    return d[:6]


def rebuild_period_kline(recent_days: int = 0, progress=None) -> dict:
    """从日K聚合重建周K/月K. recent_days=0 全量; >0 仅重建最近 N 天(每日增量).

    表结构: (code, date=该周期最后交易日, open, high, low, close, volume, amount, turnover).
    """
    from datetime import datetime, timedelta
    conn = get_kline_db()
    c = conn.cursor()
    if recent_days <= 0:
        c.execute("DROP TABLE IF EXISTS kline_weekly")
        c.execute("DROP TABLE IF EXISTS kline_monthly")
    for t in ("kline_weekly", "kline_monthly"):
        c.execute(f"""CREATE TABLE IF NOT EXISTS {t} (
            code TEXT, date TEXT, open REAL, high REAL, low REAL, close REAL,
            volume INTEGER, amount REAL, turnover REAL DEFAULT 0,
            PRIMARY KEY (code, date))""")
        c.execute(f"CREATE INDEX IF NOT EXISTS idx_{t}_code ON {t}(code, date)")

    cutoff = ""
    if recent_days > 0:
        cutoff = (datetime.now() - timedelta(days=recent_days)).strftime("%Y%m%d")
        c.execute("DELETE FROM kline_weekly WHERE date >= ?", (cutoff,))
        c.execute("DELETE FROM kline_monthly WHERE date >= ?", (cutoff,))
    conn.commit()

    codes = [str(r[0]) for r in c.execute("SELECT DISTINCT code FROM kline_daily ORDER BY code")]
    where = " AND date >= ?" if cutoff else ""
    w_buf, m_buf = [], []
    done = 0
    t0 = time.time()
    for code in codes:
        params = (code, cutoff) if cutoff else (code,)
        rows = c.execute(
            "SELECT date, open, high, low, close, volume, amount, turnover "
            f"FROM kline_daily WHERE code=?{where} ORDER BY date", params).fetchall()
        if not rows:
            continue
        data = [(r[0], r[1], r[2], r[3], r[4], r[5], r[6], r[7]) for r in rows]
        for _k, d, o, h, l, cl, v, a, tu in _period_agg(data, _week_key):
            w_buf.append((code, d, o, h, l, cl, v, a, tu))
        for _k, d, o, h, l, cl, v, a, tu in _period_agg(data, _month_key):
            m_buf.append((code, d, o, h, l, cl, v, a, tu))
        done += 1
        if len(w_buf) >= 50000:
            c.executemany("INSERT OR REPLACE INTO kline_weekly VALUES (?,?,?,?,?,?,?,?,?)", w_buf)
            w_buf = []
        if len(m_buf) >= 50000:
            c.executemany("INSERT OR REPLACE INTO kline_monthly VALUES (?,?,?,?,?,?,?,?,?)", m_buf)
            m_buf = []
        if progress and done % 1000 == 0:
            progress(f"聚合进度 {done}/{len(codes)}", None)
    if w_buf:
        c.executemany("INSERT OR REPLACE INTO kline_weekly VALUES (?,?,?,?,?,?,?,?,?)", w_buf)
    if m_buf:
        c.executemany("INSERT OR REPLACE INTO kline_monthly VALUES (?,?,?,?,?,?,?,?,?)", m_buf)
    conn.commit()
    w_n = c.execute("SELECT COUNT(*) FROM kline_weekly").fetchone()[0]
    m_n = c.execute("SELECT COUNT(*) FROM kline_monthly").fetchone()[0]
    conn.close()
    log.info("period kline: weekly=%d monthly=%d (%s)", w_n, m_n,
             "recent %dd" % recent_days if recent_days else "full")
    return {"weekly": w_n, "monthly": m_n, "elapsed": round(time.time() - t0, 1)}


def get_period_kline(code: str, period: str = "weekly", limit: int = 250) -> List[Dict]:
    """读周K/月K (升序). period: weekly|monthly."""
    table = "kline_weekly" if period == "weekly" else "kline_monthly"
    conn = get_kline_db()
    rows = conn.execute(
        f"SELECT code, date, open, high, low, close, volume, amount, turnover "
        f"FROM {table} WHERE code=? ORDER BY date DESC LIMIT ?", (code, limit)).fetchall()
    conn.close()
    return [dict(r) for r in reversed(rows)]


# ════════════════════════════════════════════════════════
#  龙虎榜 (lhb_daily) + 融资融券 (margin_daily)
# ════════════════════════════════════════════════════════
def init_lhb_margin_tables(rebuild: bool = False):
    """建表. rebuild=True 时重建 lhb_daily(首拉用, 旧表无唯一约束)."""
    conn = get_kline_db()
    if rebuild:
        conn.execute("DROP TABLE IF EXISTS lhb_daily")
    conn.execute("""CREATE TABLE IF NOT EXISTS lhb_daily (
        code TEXT, name TEXT, trade_date TEXT, close_price REAL, change_rate REAL,
        net_amount REAL, buy_amount REAL, sell_amount REAL, deal_amount REAL,
        market_amount REAL, net_ratio REAL, deal_ratio REAL, turnover REAL,
        market_cap REAL, reason TEXT, d1_chg REAL, d2_chg REAL, d5_chg REAL, d10_chg REAL,
        PRIMARY KEY (code, trade_date, reason))""")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_lhb_date ON lhb_daily(trade_date)")
    conn.execute("""CREATE TABLE IF NOT EXISTS margin_daily (
        code TEXT, date TEXT, name TEXT,
        rzye REAL, rzmre REAL, rzche REAL, rqye REAL, rqmcl REAL, rqchl REAL, rzrqye REAL,
        PRIMARY KEY (code, date))""")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_margin_date ON margin_daily(date)")
    conn.commit()
    conn.close()


def update_lhb_range(start_date: str, end_date: str) -> int:
    """拉取日期范围龙虎榜明细并写入. 返回行数."""
    from akshare_source import ak_fetch_lhb_range
    rows = ak_fetch_lhb_range(start_date, end_date)
    if not rows:
        return 0
    conn = get_kline_db()
    conn.executemany(
        "INSERT OR REPLACE INTO lhb_daily (code,name,trade_date,close_price,change_rate,"
        "net_amount,buy_amount,sell_amount,deal_amount,market_amount,net_ratio,deal_ratio,"
        "turnover,market_cap,reason,d1_chg,d2_chg,d5_chg,d10_chg) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", rows)
    conn.commit()
    conn.close()
    return len(rows)


def update_margin_dates(dates: List[str]) -> dict:
    """拉取指定日期列表的融资融券明细(SSE+SZSE). 返回 {ok, rows}."""
    from akshare_source import ak_fetch_margin_day
    ok = rows_n = 0
    for d in dates:
        rows = ak_fetch_margin_day(d)
        if rows:
            conn = get_kline_db()
            conn.executemany(
                "INSERT OR REPLACE INTO margin_daily "
                "(code,date,name,rzye,rzmre,rzche,rqye,rqmcl,rqchl,rzrqye) "
                "VALUES (?,?,?,?,?,?,?,?,?,?)", rows)
            conn.commit()
            conn.close()
            ok += 1
            rows_n += len(rows)
    return {"ok": ok, "rows": rows_n}


def get_lhb(code: str = "", days: int = 250) -> List[Dict]:
    """龙虎榜明细(按股票或最近N条)."""
    conn = get_kline_db()
    if code:
        rows = conn.execute(
            "SELECT * FROM lhb_daily WHERE code=? ORDER BY trade_date DESC LIMIT ?",
            (code, days)).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM lhb_daily ORDER BY trade_date DESC LIMIT ?", (days,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_margin(code: str, days: int = 250) -> List[Dict]:
    """单只股票融资融券历史(升序)."""
    conn = get_kline_db()
    rows = conn.execute(
        "SELECT date, rzye, rzmre, rzche, rqye, rqmcl, rqchl, rzrqye "
        "FROM margin_daily WHERE code=? ORDER BY date DESC LIMIT ?", (code, days)).fetchall()
    conn.close()
    return [dict(r) for r in reversed(rows)]


# ════════════════════════════════════════════════════════
#  行业市盈率 (industry_pe, 巨潮证监会行业分类 120 行业)
# ════════════════════════════════════════════════════════
def init_industry_pe_table():
    conn = get_kline_db()
    conn.execute("""CREATE TABLE IF NOT EXISTS industry_pe (
        date TEXT, code TEXT, name TEXT, category TEXT, level TEXT,
        company_count INTEGER, calc_count INTEGER, total_mv REAL, net_profit REAL,
        pe_weighted REAL, pe_median REAL, pe_avg REAL,
        PRIMARY KEY (date, code))""")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_industry_pe_date ON industry_pe(date)")
    conn.commit()
    conn.close()


def cache_industry_pe(date: str = None) -> int:
    """拉取指定日期(默认最近交易日)行业市盈率并写入. 返回行数."""
    from akshare_source import ak_get_industry_pe
    if date is None:
        date = datetime.now().strftime("%Y%m%d")
    data = ak_get_industry_pe(date)
    if not data:
        return 0
    conn = get_kline_db()
    conn.executemany(
        "INSERT OR REPLACE INTO industry_pe "
        "(date,code,name,category,level,company_count,calc_count,total_mv,net_profit,"
        "pe_weighted,pe_median,pe_avg) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        [(d["date"], d["code"], d["name"], d["category"], d["level"],
          d["company_count"], d["calc_count"], d["total_mv"], d["net_profit"],
          d["pe_weighted"], d["pe_median"], d["pe_avg"]) for d in data])
    conn.commit()
    conn.close()
    log.info("cached %d industry_pe rows for %s", len(data), date)
    return len(data)


def get_industry_pe(date: str = None, level: str = "") -> List[Dict]:
    """行业市盈率. date=None 取最新日期; level='1'/'2' 过滤层级."""
    conn = get_kline_db()
    if not date:
        date = conn.execute("SELECT MAX(date) FROM industry_pe").fetchone()[0]
    if not date:
        conn.close()
        return []
    sql = "SELECT * FROM industry_pe WHERE date=?"
    params = [date]
    if level:
        sql += " AND level=?"
        params.append(level)
    sql += " ORDER BY code"
    rows = conn.execute(sql, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ════════════════════════════════════════════════════════
#  筹码分布 (chip_distribution, 全市场最近 N 天)
# ════════════════════════════════════════════════════════
def _chip_worker(codes: list, days: int) -> dict:
    """多进程 worker: 每进程独立 py_mini_racer(V8 并发会崩, 必须多进程)."""
    from akshare_source import ak_get_cyq_chip_data
    import sqlite3 as _sq
    ok = fail = rows_n = 0
    failed = []
    db = KLINE_DB
    for code in codes:
        try:
            data = ak_get_cyq_chip_data(code, days=days)
            if not data:
                fail += 1
                failed.append(code)
                continue
            con = _sq.connect(db, timeout=60)
            con.executemany(
                "INSERT OR REPLACE INTO chip_distribution (code, date, [获利比例], [平均成本], "
                "[90成本_低], [90成本_高], [90集中度], [70成本_低], [70成本_高], [70集中度], updated_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                [(d["code"], d["date"], d["获利比例"], d["平均成本"],
                  d["90成本-低"], d["90成本-高"], d["90集中度"],
                  d["70成本-低"], d["70成本-高"], d["70集中度"],
                  datetime.now().strftime("%Y-%m-%d %H:%M:%S")) for d in data])
            con.commit()
            con.close()
            ok += 1
            rows_n += len(data)
        except Exception:
            fail += 1
            failed.append(code)
    return {"ok": ok, "fail": fail, "rows": rows_n, "failed": failed}


def update_chip_all(days: int = 250, procs: int = 6, progress=None) -> dict:
    """全市场筹码分布重算(最近 days 天). 多进程(每进程独立 V8). 返回 {ok, fail, rows}."""
    import multiprocessing as mp
    from concurrent.futures import ThreadPoolExecutor, as_completed
    conn = get_kline_db()
    codes = [str(r[0]) for r in conn.execute(
        "SELECT code FROM stock_list WHERE status='active' AND substr(code,1,2) IN ('00','30','60','68') "
        "ORDER BY code").fetchall()]
    conn.close()
    total = len(codes)
    chunks = [codes[i::procs] for i in range(procs)]
    chunks = [ch for ch in chunks if ch]
    t0 = time.time()
    ok = fail = rows_n = 0
    # 用线程池跑多个"进程池任务"? 直接用 mp.Pool
    with mp.Pool(len(chunks)) as pool:
        results = pool.starmap(_chip_worker, [(ch, days) for ch in chunks])
    for r in results:
        ok += r["ok"]
        fail += r["fail"]
        rows_n += r["rows"]
    el = round(time.time() - t0, 1)
    log.info("chip update: ok=%d fail=%d rows=%d (%ss)", ok, fail, rows_n, el)
    return {"ok": ok, "fail": fail, "rows": rows_n, "total": total, "elapsed": el}


# ════════════════════════════════════════════════════════
#  股东户数 / 基金持仓 (季度)
# ════════════════════════════════════════════════════════
def get_holder_count(code: str, limit: int = 40) -> List[Dict]:
    """股东户数历史(降序)."""
    conn = get_kline_db()
    rows = conn.execute(
        "SELECT report_date, holder_count, holder_count_prev, holder_change, holder_change_pct, "
        "avg_mv, avg_shares, total_mv, total_shares, announce_date "
        "FROM holder_count WHERE code=? ORDER BY report_date DESC LIMIT ?", (code, limit)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_fund_hold(code: str, limit: int = 40) -> List[Dict]:
    """基金持仓历史(降序)."""
    conn = get_kline_db()
    rows = conn.execute(
        "SELECT report_date, fund_count, hold_shares, hold_value, hold_change_pct, change_shares "
        "FROM fund_hold WHERE code=? ORDER BY report_date DESC LIMIT ?", (code, limit)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ════════════════════════════════════════════════════════
#  概念/行业板块 (THS 指数历史, board_list + board_daily)
# ════════════════════════════════════════════════════════
def init_board_tables():
    conn = get_kline_db()
    conn.execute("""CREATE TABLE IF NOT EXISTS board_list (
        code TEXT PRIMARY KEY, name TEXT, type TEXT, updated_at TEXT)""")
    conn.execute("""CREATE TABLE IF NOT EXISTS board_daily (
        code TEXT, name TEXT, type TEXT, date TEXT,
        open REAL, high REAL, low REAL, close REAL, volume INTEGER, amount REAL,
        PRIMARY KEY (code, date))""")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_board_daily_date ON board_daily(date)")
    conn.commit()
    conn.close()


def cache_board_list() -> int:
    """刷新板块列表(THS 概念+行业)."""
    from akshare_source import ak_get_board_list_ths
    data = ak_get_board_list_ths()
    if not data:
        return 0
    conn = get_kline_db()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn.executemany("INSERT OR REPLACE INTO board_list VALUES (?,?,?,?)",
                     [(d["code"], d["name"], d["type"], now) for d in data])
    conn.commit()
    conn.close()
    return len(data)


def update_board_daily(recent_days: int = 0, workers: int = 8, progress=None) -> dict:
    """板块指数增量更新(THS). recent_days>0 时只拉最近 N 天."""
    from concurrent.futures import ThreadPoolExecutor, as_completed
    from akshare_source import ak_fetch_board_index_ths
    conn = get_kline_db()
    boards = [dict(r) for r in conn.execute("SELECT code, name, type FROM board_list")]
    conn.close()
    if not boards:
        return {"updated": 0, "errors": 0, "rows_added": 0, "total": 0}
    if recent_days > 0:
        start = (datetime.now() - timedelta(days=recent_days)).strftime("%Y%m%d")
    else:
        start = "20100101"
    end = (datetime.now() + timedelta(days=1)).strftime("%Y%m%d")
    total = len(boards)
    updated = errors = rows_added = 0
    batch = []
    t0 = time.time()

    def _fetch(b):
        rows = ak_fetch_board_index_ths(b["name"], b["type"], start, end)
        return rows, b

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futs = {pool.submit(_fetch, b): b for b in boards}
        done = 0
        for f in as_completed(futs):
            b = futs[f]
            done += 1
            try:
                rows, _ = f.result(timeout=60)
            except Exception:
                rows = []
            if rows:
                updated += 1
                batch.extend([(b["code"], b["name"], b["type"]) + tuple(r) for r in rows])
                rows_added += len(rows)
            else:
                errors += 1
            if progress and (done % 50 == 0 or done == total):
                progress(f"[{done}/{total}] +{rows_added} 行", None)
    if batch:
        conn = get_kline_db()
        conn.executemany(
            "INSERT OR REPLACE INTO board_daily "
            "(code,name,type,date,open,high,low,close,volume,amount) VALUES (?,?,?,?,?,?,?,?,?,?)", batch)
        conn.commit()
        conn.close()
    return {"updated": updated, "errors": errors, "rows_added": rows_added,
            "total": total, "elapsed": round(time.time() - t0, 1)}


def get_board_list(btype: str = "") -> List[Dict]:
    conn = get_kline_db()
    if btype:
        rows = conn.execute("SELECT * FROM board_list WHERE type=? ORDER BY code", (btype,)).fetchall()
    else:
        rows = conn.execute("SELECT * FROM board_list ORDER BY type, code").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_board_kline(code: str, days: int = 250) -> List[Dict]:
    conn = get_kline_db()
    rows = conn.execute(
        "SELECT date, open, high, low, close, volume, amount FROM board_daily "
        "WHERE code=? ORDER BY date DESC LIMIT ?", (code, days)).fetchall()
    conn.close()
    return [dict(r) for r in reversed(rows)]


def cache_sector_board_from_akshare():
    """写入 sector_board 快照表(991行: 行业/概念板块涨跌榜, 含 leader).

    此前该表只有历史一次性手动写入, 现纳入每日更新. leader 尽量保留旧值,
    避免覆盖历史留下的领涨股信息; 若旧值不存在则从涨停池当日数据补.
    """
    try:
        from akshare_source import ak_get_sectors, ak_get_limit_up
        conn = get_kline_db()
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        conn.execute("""CREATE TABLE IF NOT EXISTS sector_board (
            code TEXT, name TEXT, type TEXT, rank INTEGER, latest_price REAL,
            change_pct REAL, up_count INTEGER, dn_count INTEGER,
            leader TEXT, leader_chg REAL, updated_at TEXT,
            PRIMARY KEY (code, type))""")
        # 当日涨停池 → code->name 映射, 用于 leader 兜底(板块领涨=板块内涨停股)
        limit_map = {}
        try:
            for d in ak_get_limit_up(datetime.now().strftime("%Y%m%d")) or []:
                limit_map[str(d.get("code", ""))] = d.get("name", "")
        except Exception:
            pass
        total = 0
        for s_type in ("industry", "concept"):
            data = ak_get_sectors(s_type) or []
            # 东财反爬时行业板块用同花顺备选(含领涨股)
            if not data and s_type == "industry":
                try:
                    from akshare_source import ak_get_sectors_ths
                    data = ak_get_sectors_ths() or []
                except Exception:
                    data = []
            for i, d in enumerate(data):
                code = str(d.get("code", ""))
                name = str(d.get("name", ""))
                old = conn.execute("SELECT leader, leader_chg FROM sector_board WHERE code=? AND type=?",
                                   (code, s_type)).fetchone()
                # 新值优先, 空则保留旧值(防源缺字段时清掉)
                new_leader = str(d.get("leader", "") or "") or limit_map.get(code, "")
                leader = new_leader or (old[0] if old and old[0] else "")
                new_chg = float(d.get("leader_chg", 0) or 0)
                leader_chg = new_chg if new_chg else (old[1] if old and old[1] is not None else 0.0)
                conn.execute("""INSERT OR REPLACE INTO sector_board
                    (code, name, type, rank, latest_price, change_pct, up_count, dn_count,
                     leader, leader_chg, updated_at)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                             (code, name, s_type, i + 1,
                              float(d.get("price", 0) or 0), float(d.get("change_pct", 0) or 0),
                              int(d.get("up_count", 0) or 0), int(d.get("down_count", 0) or 0),
                              leader, leader_chg, now))
            total += len(data)
        conn.commit()
        conn.close()
        log.info("cached %d sector_board rows", total)
        return total
    except Exception as e:
        log.warning("cache sector_board failed: %s", str(e)[:80])
        return 0


def cache_north_flow_from_akshare():
    """Cache north-bound (HSGT) flow data from AKShare"""
    import akshare as ak
    try:
        df = ak.stock_hsgt_hist_em(symbol="北向资金")
        if df is None or df.empty:
            return 0
        conn = get_kline_db()
        # AKShare returns Chinese column names: 日期/当日成交净买额/历史累计净买额
        col_map = {"日期": "date", "当日成交净买额": "net_flow", "历史累计净买额": "cum_flow"}
        df = df.rename(columns=col_map)
        rows = []
        for _, row in df.iterrows():
            try:
                rows.append((
                    str(row.get("date", "")),
                    float(row.get("net_flow", 0) or 0),
                    float(row.get("cum_flow", 0) or 0),
                ))
            except (ValueError, TypeError):
                continue
        conn.executemany("INSERT OR REPLACE INTO north_flow VALUES (?,?,?)", rows)
        conn.commit()
        conn.close()
        count = len(rows)
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
        rows = []
        for d in data:
            try:
                rows.append((d["date"], d["code"], d["name"], d["price"], d["change_pct"],
                             d["amount"], d["turnover"], d["total_mv"], d["type"]))
            except (KeyError, TypeError):
                continue
        conn.executemany("INSERT OR REPLACE INTO limit_up VALUES (?,?,?,?,?,?,?,?,?)", rows)
        count = len(rows)
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
        rows = []
        for d in data:
            try:
                rows.append((d["code"], d["name"], d["last_date"], d["price"], d["change_pct"],
                             d["times"], d["net_buy"], d["period"], now))
            except (KeyError, TypeError):
                continue
        conn.executemany("INSERT OR REPLACE INTO lhb_stock VALUES (?,?,?,?,?,?,?,?,?)", rows)
        count = len(rows)
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
        rows = []
        for d in data:
            try:
                rows.append((d["date"], d["close"], d["high20"], d["low20"], d["high60"],
                             d["low60"], d["high120"], d["low120"], now))
            except (KeyError, TypeError):
                continue
        conn.executemany("INSERT OR REPLACE INTO high_low VALUES (?,?,?,?,?,?,?,?,?)", rows)
        count = len(rows)
        conn.commit()
        conn.close()
        log.info("cached %d high_low rows", count)
        return count
    except Exception as e:
        log.warning("cache high_low failed: %s", str(e)[:80])
        return 0




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
            # 直接调用因子评分引擎，不再依赖本机 Flask 服务
            picks = compute_factor_picks()[:20]
            codes_to_fetch = [s["code"] for s in picks if s.get("code")]
            if not codes_to_fetch:
                raise RuntimeError("picks empty")
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
            conn.executemany(
                "INSERT OR REPLACE INTO chip_distribution (code, date, [获利比例], [平均成本], [90成本_低], [90成本_高], [90集中度], [70成本_低], [70成本_高], [70集中度], updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                [(
                    d["code"], d["date"], d["获利比例"], d["平均成本"],
                    d["90成本-低"], d["90成本-高"], d["90集中度"],
                    d["70成本-低"], d["70成本-高"], d["70集中度"],
                    now,
                ) for d in data],
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
    """读取 stock_cache.db 中的 stock_spot 缓存行情"""
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
    """读取指定区间的 K 线数据（供回测使用）"""
    conn = get_kline_db()
    rows = conn.execute(
        "SELECT * FROM kline_daily WHERE code=? AND date BETWEEN ? AND ? ORDER BY date",
        (code, start, end),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# CLI 子命令表
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
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
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
