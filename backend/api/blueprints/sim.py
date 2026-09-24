# -*- coding: utf-8 -*-
"""模拟盘可视化 — 读取 stock-ml 项目的 snapshot.json 提供账户数据。

数据源: D:/小光工作区/projects/stock-ml/project/linglai/output/sim/snapshot.json
由 stock-ml 的 scripts/sim_snapshot.py 生成（含全部模拟账户：净值/持仓/交易/曲线）。
"""
import json
import os
import subprocess

from flask import Blueprint

from ..envelope import ok, err

bp = Blueprint("sim", __name__, url_prefix="/api/sim")

STOCK_ML = os.environ.get("STOCK_ML_DIR", r"D:\小光工作区\projects\stock-ml\project\linglai")
STOCK_ML_PY = os.environ.get("STOCK_ML_PY", r"D:\小光工作区\projects\stock-ml\.venv\Scripts\python.exe")
SNAP = os.path.join(STOCK_ML, "output", "sim", "snapshot.json")


def _load():
    if not os.path.exists(SNAP):
        return None
    with open(SNAP, encoding="utf-8") as f:
        return json.load(f)


@bp.route("/accounts", methods=["GET"])
def accounts():
    d = _load()
    if d is None:
        return err(404, "no_snapshot", "模拟盘快照不存在——请先运行 stock-ml/scripts/sim_snapshot.py")
    return ok(d)


@bp.route("/refresh", methods=["POST"])
def refresh():
    """重新生成快照（调用 stock-ml 的 sim_snapshot.py）"""
    script = os.path.join(STOCK_ML, "scripts", "sim_snapshot.py")
    if not os.path.exists(script):
        return err(404, "no_script", f"脚本不存在: {script}")
    try:
        r = subprocess.run([STOCK_ML_PY, script], cwd=STOCK_ML,
                           capture_output=True, text=True, timeout=180,
                           encoding="utf-8", errors="replace")
        if r.returncode != 0:
            return err(500, "refresh_failed", (r.stderr or r.stdout or "")[-500:])
        d = _load()
        return ok(d, message="快照已刷新")
    except Exception as e:
        return err(500, "refresh_error", str(e))


@bp.route("/health", methods=["GET"])
def health():
    d = _load()
    return ok({
        "snapshot_exists": d is not None,
        "generated": d.get("generated") if d else None,
        "data_date": d.get("data_date") if d else None,
        "accounts": len(d.get("accounts", [])) if d else 0,
        "stock_ml": STOCK_ML,
    })
