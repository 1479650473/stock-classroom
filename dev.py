# -*- coding: utf-8 -*-
"""dev.py — 一键开发环境：Python 后端(5000) + Vite 前端(5173)。

为什么需要它：
  · 桌面版（安装后的客户端）常驻托盘并占用 5000 端口，与开发环境冲突；
    更麻烦的是它的后端是**冻结的旧构建**，改了 Python 代码不会生效 —— 却看起来"没报错"。
  · 这个脚本会先检查 5000 端口是谁在用，是桌面版后端就明确提示（或 --kill 停掉）。

用法：
    python dev.py                # 起后端 + 前端（Ctrl+C 一起停）
    python dev.py --kill         # 先停掉占用 5000 的桌面版后端，再起
    python dev.py --api-only     # 只起后端
    python dev.py --web-only     # 只起前端
    python dev.py --port 5001    # 换后端端口（前端需同步改 base，一般用默认 5000）
"""
from __future__ import annotations

import argparse
import os
import socket
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.abspath(__file__))
WEB = os.path.join(ROOT, "web")
NODE = r"C:\nvm\v22.23.2\node.exe"
VITE = os.path.join(WEB, "node_modules", "vite", "bin", "vite.js")


def port_owner(port: int) -> int | None:
    """返回监听该端口的 PID（无则 None）。用 netstat，避免额外依赖。"""
    try:
        out = subprocess.run(["netstat", "-ano"], capture_output=True, text=True, timeout=10).stdout
    except Exception:
        return None
    for line in out.splitlines():
        parts = line.split()
        if len(parts) >= 5 and parts[0].upper().startswith("TCP") and parts[3] == "LISTENING":
            if parts[1].endswith(f":{port}"):
                try:
                    return int(parts[4])
                except ValueError:
                    continue
    return None


def proc_name(pid: int) -> str:
    try:
        out = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
            capture_output=True, text=True, timeout=10).stdout.strip()
        return out.split(",")[0].strip('"') if out else "?"
    except Exception:
        return "?"


def wait_port(port: int, timeout: float = 40) -> bool:
    t0 = time.time()
    while time.time() - t0 < timeout:
        with socket.socket() as s:
            s.settimeout(0.4)
            if s.connect_ex(("127.0.0.1", port)) == 0:
                return True
        time.sleep(0.3)
    return False


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=5000)
    ap.add_argument("--kill", action="store_true", help="停掉占用端口的桌面版后端")
    ap.add_argument("--api-only", action="store_true")
    ap.add_argument("--web-only", action="store_true")
    args = ap.parse_args()

    procs: list[subprocess.Popen] = []

    # ── 后端 ──
    if not args.web_only:
        pid = port_owner(args.port)
        if pid:
            name = proc_name(pid)
            print(f"[dev] 端口 {args.port} 已被占用：PID {pid} ({name})")
            if name.lower() == "stock-api.exe":
                print("[dev] 这是桌面版客户端自带的后端（冻结构建）—— 改 Python 代码不会生效！")
                if args.kill:
                    subprocess.run(["taskkill", "/PID", str(pid), "/F"], capture_output=True)
                    time.sleep(1.5)
                    print("[dev] 已停止桌面版后端（托盘里的应用会失去连接，重启客户端可恢复）")
                else:
                    print("[dev] 选择：① 退出托盘里的应用后重跑；② 加 --kill 由我停掉它。")
                    sys.exit(2)
            else:
                print("[dev] 端口被其他进程占用，请先处理后再试。")
                sys.exit(2)
        env = dict(os.environ)
        env.setdefault("PYTHONIOENCODING", "utf-8")
        print(f"[dev] 启动 Python 后端 http://127.0.0.1:{args.port} …")
        be = subprocess.Popen([sys.executable, os.path.join(ROOT, "run_web.py"), "--port", str(args.port)],
                              cwd=ROOT, env=env)
        procs.append(be)
        if wait_port(args.port):
            print(f"[dev] 后端就绪（PID {be.pid}）")
        else:
            print("[dev] 后端 40s 内未就绪，请看上面的输出")

    # ── 前端 ──
    if not args.api_only:
        if port_owner(5173):
            print("[dev] 5173 已在监听（vite 可能已在运行），跳过启动前端")
        else:
            if not os.path.exists(NODE):
                print(f"[dev] 找不到 node：{NODE}（改脚本里的 NODE 路径）")
            else:
                print("[dev] 启动 Vite 前端 http://localhost:5173 …")
                fe = subprocess.Popen([NODE, VITE, "--host", "--port", "5173", "--strictPort"],
                                      cwd=WEB)
                procs.append(fe)

    print("\n[dev] 就绪：")
    print(f"      浏览器调试 : http://localhost:5173")
    print(f"      后端接口   : http://127.0.0.1:{args.port}/api/system/bootstrap")
    print("      桌面调试   : cd web/src-tauri && cargo tauri dev   (debug 构建不会拉起 sidecar)")
    print("      Ctrl+C 停止\n")
    try:
        while True:
            time.sleep(1)
            if any(p.poll() is not None for p in procs):
                print("[dev] 有子进程退出，整体停止")
                break
    except KeyboardInterrupt:
        pass
    finally:
        for p in procs:
            if p.poll() is None:
                p.terminate()
        print("[dev] 已停止")


if __name__ == "__main__":
    main()
