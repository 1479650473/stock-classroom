# -*- coding: utf-8 -*-
"""probe_intraday.py — 盘中数据频率探测(免费源).

每 30s 拉一次: 新浪快照 / 腾讯快照 / 腾讯分时, 记录数据时间戳推进与耗时/失败.
输出: data/logs/intraday_probe.log (逐次) + 结束汇总(刷新粒度/可持续频率).
用法: python scripts/probe_intraday.py [--interval 30] [--until 11:30]
"""
from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime

import requests

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOG = os.path.join(ROOT, "data", "logs", "intraday_probe.log")

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"


def _sina():
    t0 = time.time()
    r = requests.get("https://hq.sinajs.cn/list=sh600036,sz000001,sh000300",
                     headers={"Referer": "https://finance.sina.com.cn", "User-Agent": UA}, timeout=10)
    dt = time.time() - t0
    txt = r.content.decode("gbk", errors="replace")
    for l in txt.strip().split("\n"):
        if "sh600036" in l and '"' in l:
            f = l.split('"')[1].split(",")
            if len(f) > 31:
                return {"price": f[3], "vol": f[8], "time": f"{f[30]} {f[31]}", "elapsed": round(dt, 2)}
    return None


def _tx():
    t0 = time.time()
    r = requests.get("https://qt.gtimg.cn/q=sh600036",
                     headers={"User-Agent": UA}, timeout=10)
    dt = time.time() - t0
    txt = r.content.decode("gbk", errors="replace")
    if '"' in txt:
        f = txt.split('"')[1].split("~")
        if len(f) > 30:
            return {"price": f[3], "vol": f[6], "time": f[30], "elapsed": round(dt, 2)}
    return None


def _tx_minute():
    t0 = time.time()
    r = requests.get("https://web.ifzq.gtimg.cn/appstock/app/minute/query?code=sh600036",
                     headers={"User-Agent": UA}, timeout=10)
    dt = time.time() - t0
    j = r.json()
    d = j.get("data", {}).get("sh600036", {}).get("data", {})
    lines = d.get("data", [])
    last = lines[-1].split(" ") if lines else []
    return {"date": d.get("date", ""), "n": len(lines),
            "last_time": last[0] if last else "", "last_price": last[1] if len(last) > 1 else "",
            "elapsed": round(dt, 2)}


def _sina_min():
    t0 = time.time()
    r = requests.get("https://quotes.sina.cn/cn/api/jsonp_v2.php/x/CN_MarketDataService.getKLineData"
                     "?symbol=sh600036&scale=1&ma=no&datalen=3",
                     headers={"Referer": "https://finance.sina.com.cn", "User-Agent": UA}, timeout=10)
    dt = time.time() - t0
    txt = r.text
    i = txt.find("[")
    j = txt.rfind("]")
    if i >= 0 and j > i:
        data = json.loads(txt[i:j + 1])
        if data:
            return {"last": data[-1], "n": len(data), "elapsed": round(dt, 2)}
    return None


def main():
    interval = 30
    until = "11:30"
    args = sys.argv[1:]
    for i, a in enumerate(args):
        if a == "--interval" and i + 1 < len(args):
            interval = int(args[i + 1])
        if a == "--until" and i + 1 < len(args):
            until = args[i + 1]

    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    lg = open(LOG, "a", encoding="utf-8")

    def log(msg):
        line = f"{datetime.now().strftime('%H:%M:%S')} {msg}"
        print(line, flush=True)
        lg.write(line + "\n")
        lg.flush()

    log(f"=== 盘中频率探测开始 (interval={interval}s, until={until}) ===")
    n_ok = n_fail = 0
    tx_minute_ts = []      # 腾讯分时时间戳推进记录
    sina_ts = []
    while True:
        now = datetime.now()
        if now.strftime("%H:%M") >= until:
            break
        parts = []
        try:
            s = _sina()
            if s:
                n_ok += 1
                sina_ts.append((now.strftime("%H:%M:%S"), s["time"]))
                parts.append(f"sina p={s['price']} t={s['time']} {s['elapsed']}s")
        except Exception as e:
            n_fail += 1
            parts.append(f"sina EXC {str(e)[:40]}")
        try:
            x = _tx()
            if x:
                parts.append(f"tx p={x['price']} t={x['time']} {x['elapsed']}s")
        except Exception as e:
            parts.append(f"tx EXC {str(e)[:30]}")
        try:
            m = _tx_minute()
            if m:
                tx_minute_ts.append((now.strftime("%H:%M:%S"), m["last_time"], m["last_price"]))
                parts.append(f"txmin n={m['n']} last={m['last_time']}@{m['last_price']} {m['elapsed']}s")
        except Exception as e:
            parts.append(f"txmin EXC {str(e)[:30]}")
        try:
            sm = _sina_min()
            if sm:
                parts.append(f"sinamin last={sm['last']} {sm['elapsed']}s")
        except Exception as e:
            parts.append(f"sinamin EXC {str(e)[:30]}")
        log(" | ".join(parts))
        time.sleep(interval)

    # 汇总: 腾讯分时刷新粒度
    log("=== 汇总 ===")
    if tx_minute_ts:
        changes = []
        prev = None
        for wall, t, p in tx_minute_ts:
            if t != prev:
                changes.append((wall, t, p))
                prev = t
        log(f"腾讯分时: 共 {len(tx_minute_ts)} 次采样, 时间戳推进 {len(changes)} 次")
        for c in changes[-15:]:
            log(f"  {c[0]} -> 分时最新 {c[1]} @{c[2]}")
    log(f"新浪快照: {len(sina_ts)} 次成功, 失败 {n_fail}")
    lg.close()


if __name__ == "__main__":
    while True:
        try:
            main()
            break
        except KeyboardInterrupt:
            break
        except Exception as e:
            try:
                with open(LOG, "a", encoding="utf-8") as f:
                    f.write(f"[{datetime.now().strftime('%H:%M:%S')}] PROBE CRASH: "
                            f"{type(e).__name__}: {str(e)[:120]}\n")
            except Exception:
                pass
            time.sleep(60)