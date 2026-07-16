"""每日收盘后全量数据维护脚本
用法（直接运行）:
  python scripts/daily_maintenance.py

用法（指定日期回补）:
  python scripts/daily_maintenance.py --date 20260710

Windows Task Scheduler 建议配置：
  每天 16:00 运行，周一~周五
"""

import sys, os, time, logging, subprocess, json, argparse
from datetime import datetime, timedelta

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(PROJECT_DIR, "backend"))

LOG_DIR = os.path.join(PROJECT_DIR, "scripts", "logs")
os.makedirs(LOG_DIR, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(
            os.path.join(LOG_DIR, f"maintenance_{datetime.now().strftime('%Y%m%d')}.log"),
            encoding="utf-8"
        )
    ]
)
log = logging.getLogger("daily_maint")

FLASK_PORT = 5000
FLASK_PROCESS = None


def log_step(step, status, detail=""):
    icon = "✓" if status == "ok" else "✗" if status == "fail" else "→"
    log.info("%s [%s] %s %s", icon, step, status, detail)


def start_flask():
    """Start Flask server in background for picks list API"""
    global FLASK_PROCESS
    server_path = os.path.join(PROJECT_DIR, "run_server.py")
    if not os.path.exists(server_path):
        log.warning("Flask server script not found, skipping")
        return False
    try:
        FLASK_PROCESS = subprocess.Popen(
            [sys.executable, server_path],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            cwd=PROJECT_DIR,
            creationflags=subprocess.CREATE_NO_WINDOW
        )
        # Wait for server to start
        import requests
        for i in range(30):
            time.sleep(0.5)
            try:
                r = requests.get(f"http://127.0.0.1:{FLASK_PORT}/api/health", timeout=2)
                if r.status_code == 200:
                    log.info("Flask server started on port %d", FLASK_PORT)
                    return True
            except:
                continue
        log.warning("Flask server did not respond within 15s")
        return False
    except Exception as e:
        log.warning("Flask start failed: %s", str(e)[:60])
        return False


def stop_flask():
    """Stop Flask server"""
    global FLASK_PROCESS
    if FLASK_PROCESS:
        FLASK_PROCESS.terminate()
        try:
            FLASK_PROCESS.wait(timeout=5)
        except:
            FLASK_PROCESS.kill()
        FLASK_PROCESS = None
        log.info("Flask server stopped")


def update_kline(target_date=None, catch_up_days=10):
    """Step 1: 更新日K线数据（分年表）"""
    log_step("K线", "→", "开始更新...")
    t0 = time.time()
    try:
        ok = daily_update(target_date=target_date, catch_up_days=catch_up_days)
        elapsed = time.time() - t0
        if ok:
            log_step("K线", "ok", f"耗时 {elapsed:.0f}s")
            return True
        else:
            log_step("K线", "fail", f"耗时 {elapsed:.0f}s")
            return False
    except Exception as e:
        log_step("K线", "fail", str(e)[:100])
        return False


def update_cache():
    """Step 2: 更新缓存数据（北向/龙虎榜/创新高/涨停）"""
    from data_manager import (
        cache_north_flow_from_akshare,
        cache_lhb_from_akshare,
        cache_high_low_from_akshare,
        cache_limit_up_from_akshare,
    )
    results = {}
    steps = [
        ("北向资金", cache_north_flow_from_akshare),
        ("龙虎榜",   cache_lhb_from_akshare),
        ("创新高",   cache_high_low_from_akshare),
        ("涨停池",   cache_limit_up_from_akshare),
    ]
    for name, func in steps:
        t0 = time.time()
        try:
            cnt = func()
            elapsed = time.time() - t0
            status = "ok" if cnt > 0 else "warn"
            results[name] = {"status": status, "count": cnt, "time": f"{elapsed:.1f}s"}
            log_step(name, status, f"{cnt} 行 ({elapsed:.1f}s)")
        except Exception as e:
            results[name] = {"status": "fail", "error": str(e)[:60]}
            log_step(name, "fail", str(e)[:60])
    return results


def update_weekly():
    增量更新周K线（只重新计算最新一周）
    log_step('周K', '→', '聚合周线...')
    t0 = time.time()
    try:
        from data_manager import build_weekly_kline
        cnt = build_weekly_kline(full=False)
        elapsed = time.time() - t0
        if cnt > 0:
            log_step('周K', 'ok', f'{cnt} 行 ({elapsed:.0f}s)')
        else:
            log_step('周K', 'warn', f'{cnt} 行 ({elapsed:.0f}s)')
        return cnt
    except Exception as e:
        log_step('周K', 'fail', str(e)[:100])
        return 0


def update_cyq():
    """Step 3: 更新筹码分布（选股列表 Top20）"""
    log_step("筹码", "→", "开始更新...")
    t0 = time.time()
    try:
        from data_manager import cache_cyq_chip_data
        count = cache_cyq_chip_data()  # 无参数=自动获取选股列表
        elapsed = time.time() - t0
        if count > 0:
            log_step("筹码", "ok", f"{count} 行 ({elapsed:.0f}s)")
        else:
            log_step("筹码", "warn", f"0 行 ({elapsed:.0f}s)")
        return count
    except Exception as e:
        log_step("筹码", "fail", str(e)[:100])
        return 0


def prune_logs(days=30):
    """清理超过N天的旧日志"""
    cutoff = datetime.now() - timedelta(days=days)
    pruned = 0
    for fname in os.listdir(LOG_DIR):
        fpath = os.path.join(LOG_DIR, fname)
        if not fname.endswith(".log"):
            continue
        mtime = datetime.fromtimestamp(os.path.getmtime(fpath))
        if mtime < cutoff:
            os.remove(fpath)
            pruned += 1
    if pruned:
        log.info("清理了 %d 个旧日志文件", pruned)


def print_summary(results):
    """打印汇总"""
    sep = "=" * 50
    log.info(sep)
    log.info("每日维护 — 汇总")
    log.info(sep)
    for step, result in results.items():
        if isinstance(result, dict):
            status = result.get("status", "?")
            detail = result.get("count", result.get("error", ""))
            log.info("  %-8s [%s] %s", step, status, detail)
        else:
            log.info("  %-8s %s", step, result)
    log.info(sep)
    total_ok = sum(1 for r in results.values() if isinstance(r, dict) and r.get("status") == "ok")
    total = sum(1 for r in results.values() if isinstance(r, dict))
    log.info("  总计: %d/%d 步骤成功", total_ok, total)


def main():
    parser = argparse.ArgumentParser(description="stock-classroom 每日数据维护脚本")
    parser.add_argument("--date", type=str, default=None, help="指定更新日期 (YYYYMMDD)")
    parser.add_argument("--catch-up", type=int, default=10, help="K线回补天数")
    parser.add_argument("--no-flask", action="store_true", help="不启动 Flask 服务")
    parser.add_argument("--skip-kline", action="store_true", help="跳过K线更新")
    parser.add_argument("--skip-cache", action="store_true", help="跳过缓存更新")
    parser.add_argument("--skip-cyq", action="store_true", help="跳过筹码分布")
    args = parser.parse_args()

    t_start = time.time()
    log.info("=" * 50)
    log.info("每日数据维护开始 — %s", datetime.now().strftime("%Y-%m-%d %H:%M"))
    log.info("=" * 50)
    results = {}

    # Step 1: K线更新
    if not args.skip_kline:
        results["K线"] = update_kline(target_date=args.date, catch_up_days=args.catch_up)

    # Step 2: 缓存更新
    if not args.skip_cache:
        results["缓存"] = update_cache()

    # Step 3: 周K线聚合
    if args.rebuild_weekly:
        log_step('周K', '→', '全量重建...')
        from data_manager import build_weekly_kline
        build_weekly_kline(full=True)
    elif not args.skip_kline:
        update_weekly()

    # Step 4: 筹码分布（需要 Flask picks list 接口）
    if not args.skip_cyq:
        if not args.no_flask:
            flask_ok = start_flask()
            if not flask_ok:
                log.warning("Flask 未启动，筹码分布使用活跃股回退")
        cyq_count = update_cyq()
        results["筹码"] = {"status": "ok" if cyq_count > 0 else "warn", "count": f"{cyq_count} 行"}
        if not args.no_flask:
            stop_flask()

    # 清理旧日志
    prune_logs(days=30)

    # 汇总
    elapsed = time.time() - t_start
    results["耗时"] = f"{elapsed:.0f} 秒"
    print_summary(results)
    log.info("维护完成 — %s (总耗时 %d 秒)", datetime.now().strftime("%Y-%m-%d %H:%M"), elapsed)


if __name__ == "__main__":
    main()
