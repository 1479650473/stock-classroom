# -*- coding: utf-8 -*-
"""trade-automation 桥接层 —— 把实盘 CLI 工具包成软件功能。

## 为什么需要这一层
`trade-automation` 是一个独立的 C# 桌面自动化工具（GUI 自动化券商客户端 TdxW）。
它的能力已经在 `AGENTS.md` 里定义得很清楚，但**只能从命令行用**：
盘前启动、读持仓/资金/成交、实时行情、下单、收盘快照……
这一步是把它接进 stock-classroom 的后端，让软件里能直接操作。

## 设计原则（重要，别绕开）
1. **一切以 `last-result.json` 为准，不以 stdout 为准。**
   该工具用退出码表达结果（0 成功 / 1 环境失败 / 2 断言未命中 / 3 前置失败 /
   4 资金不足 / 8 ST 预检拒绝），把结构化结果写进 `last-result.json` 与各 `*.log`。
   stdout 只作诊断。**所以桥接层返回的是 JSON 文件内容，不是解析后的文本。**
2. **只读与写入严格分开**：本模块只暴露 `run_readonly()`，
   涉及提交委托的调用必须走 `run_write()`（需显式确认 + 幂等锁由 C# 侧负责）。
3. **硬超时**：GUI 自动化会卡住（今天 09:18 就是光标到不了位、逐步重试）。
   所有调用都有超时上限，超时即杀进程并如实报告，**不假装成功**。
4. **不猜**：命令未成功时，把 exit code、stderr、相关日志原文一起返回给调用方。

## 环境事实（实测，2026-10-15）
- 工具目录：`projects/trade-automation`
- 入口：`TradeAutomation.App\\bin\\x64\\Debug\\net8.0-windows10.0.22621.0\\TradeAutomation.App.exe`
- `ta.cmd` 是同目录 exe 的转发脚本，工作目录必须是 trade-automation 根
- 结果文件都在 exe 所在目录（即 `bin\\x64\\Debug\\...`）
"""
from __future__ import annotations

import glob
import json
import os
import subprocess
import sys
import time

# ── 路径解析 ───────────────────────────────────────────────────────────
# 本文件位于 <项目根>/backend/api/trade_bridge.py，故项目根 = 上溯 3 层。
# ⚠️ 不要在注释里写"上溯 N 层"的推导而不验证 —— 我第一版写成 4 层，
#    结果 ROOT 落在 projects/ 而不是 stock-classroom/，exe 直接找不到。
#    改成：以"项目根下应有 backend/"为自检条件，找不到就往上一级找。
_HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(_HERE))
if not os.path.isdir(os.path.join(ROOT, 'backend')):
    _alt = os.path.dirname(ROOT)
    if os.path.isdir(os.path.join(_alt, 'backend')):
        ROOT = _alt

# 同级项目：<projects>/trade-automation
DEFAULT_TA_DIR = os.path.join(os.path.dirname(ROOT), 'trade-automation')
TA_DIR = os.environ.get('SC_TRADE_DIR') or DEFAULT_TA_DIR

_BIN_CANDIDATES = [
    os.path.join(TA_DIR, 'TradeAutomation.App', 'bin', 'x64', 'Debug',
                 'net8.0-windows10.0.22621.0', 'TradeAutomation.App.exe'),
    os.path.join(TA_DIR, 'TradeAutomation.App', 'bin', 'Debug',
                 'net8.0-windows10.0.22621.0', 'TradeAutomation.App.exe'),
]


def tool_dir() -> str:
    """返回实际使用的 exe 所在目录（结果文件也在这里）。"""
    for p in _BIN_CANDIDATES:
        if os.path.isfile(p):
            return os.path.dirname(p)
    return os.path.dirname(_BIN_CANDIDATES[0])


def tool_exe() -> str | None:
    for p in _BIN_CANDIDATES:
        if os.path.isfile(p):
            return p
    return None


def available() -> bool:
    return tool_exe() is not None


def _read_json(path: str):
    try:
        with open(path, 'r', encoding='utf-8-sig') as f:
            return json.load(f)
    except Exception:
        return None


def last_result():
    """最近一次命令的结果（工具侧权威产物）。"""
    return _read_json(os.path.join(tool_dir(), 'last-result.json'))


def _tail(path: str, n: int = 40) -> str:
    try:
        with open(path, 'r', encoding='utf-8', errors='replace') as f:
            return ''.join(f.readlines()[-n:])
    except Exception:
        return ''


def run_readonly(args: list[str], timeout: int = 120, log_name: str | None = None):
    """执行一个**只读**命令，返回结构化结果。

    返回 dict：
      ok        bool     —— 工具退出码为 0
      exit_code int
      result    dict|None —— last-result.json 内容（权威）
      stderr    str      —— 尾巴若干行
      log_tail  str      —— 指定日志的尾部（便于定位"为什么失败"）
      elapsed   float
      error     str|None —— 桥接层自身的错误（超时/找不到 exe 等），与工具错误分开
      cmd       list[str]
    """
    out = {
        'ok': False, 'exit_code': None, 'result': None, 'stderr': '',
        'log_tail': '', 'elapsed': None, 'error': None, 'cmd': [],
    }
    exe = tool_exe()
    if not exe:
        out['error'] = f'找不到 trade-automation 可执行文件（期望在 {TA_DIR} 下）'
        return out

    cmd = [exe, *args]
    out['cmd'] = args
    t0 = time.time()
    try:
        proc = subprocess.run(
            cmd, cwd=TA_DIR, capture_output=True, text=True,
            encoding='utf-8', errors='replace', timeout=timeout,
        )
        out['exit_code'] = proc.returncode
        out['stderr'] = (proc.stderr or '')[-2000:]
        out['ok'] = proc.returncode == 0
    except subprocess.TimeoutExpired:
        out['error'] = f'超时（{timeout}s）：GUI 自动化未在限时内完成，已放弃等待'
        out['exit_code'] = -1
    except Exception as e:
        out['error'] = f'{type(e).__name__}: {e}'
    out['elapsed'] = round(time.time() - t0, 2)

    # 权威产物：不管退出码如何都读一次，便于前端展示"工具自己怎么说"
    out['result'] = last_result()
    if log_name:
        out['log_tail'] = _tail(os.path.join(tool_dir(), log_name))
    return out


def list_snapshots(limit: int = 30):
    """列出收盘快照（文件名即时间戳，按时间倒序）。"""
    d = os.path.join(tool_dir(), 'snapshots')
    if not os.path.isdir(d):
        return []
    files = sorted(glob.glob(os.path.join(d, 'snapshot_*.json')), reverse=True)[:limit]
    return [os.path.basename(f) for f in files]


def read_snapshot(name: str):
    """读一份快照。name 必须是 snapshots/ 下的文件名（防目录穿越）。"""
    if os.path.basename(name) != name or not name.endswith('.json'):
        return None
    return _read_json(os.path.join(tool_dir(), 'snapshots', name))


def read_fills(date8: str):
    """读某日成交回传 fills_{yyyymmdd}.jsonl（按 UTF-8 BOM 兼容解析）。"""
    if not (date8.isdigit() and len(date8) == 8):
        return []
    p = os.path.join(tool_dir(), f'fills_{date8}.jsonl')
    rows = []
    try:
        with open(p, 'r', encoding='utf-8-sig') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rows.append(json.loads(line))
                except Exception:
                    rows.append({'parse_error': '这一行不是合法 JSON', 'raw': line})
    except FileNotFoundError:
        return []
    except Exception:
        return []
    return rows


def read_idempotency():
    """读幂等锁记录（每笔已提交委托及其状态）。"""
    j = _read_json(os.path.join(tool_dir(), 'idempotency.json'))
    return (j or {}).get('Entries', []) if isinstance(j, dict) else []


def status_summary():
    """给前端用的总体状态：工具是否可用 + 最近一次结果 + 环境文件时间。"""
    d = tool_dir()
    def mtime(name):
        p = os.path.join(d, name)
        try:
            return time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(os.path.getmtime(p)))
        except Exception:
            return None

    lr = last_result() or {}
    return {
        'available': available(),
        'tool_dir': d,
        'ta_dir': TA_DIR,
        'last': {
            'ts': lr.get('ts'),
            'command': lr.get('command'),
            'action': lr.get('action'),
            'ok': lr.get('ok'),
            'exit_code': lr.get('exit_code'),
            'message': lr.get('message'),
            'parameters': lr.get('parameters'),
        } if lr else None,
        'files': {
            'last-result': mtime('last-result.json'),
            'startup.log': mtime('startup.log'),
            'logintest.log': mtime('logintest.log'),
            'query.log': mtime('query.log'),
            'orders.log': mtime('orders.log'),
        },
        'snapshots': list_snapshots(5),
    }
