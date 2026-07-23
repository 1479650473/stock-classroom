# -*- coding: utf-8 -*-
"""Background data update worker for DataPipeline plugin."""

import time, sqlite3
from datetime import datetime
from PyQt5.QtCore import QThread, pyqtSignal


def _patch_paths(db_path, cache_path):
    import backend.data_manager as dm
    dm.KLINE_DB = db_path
    dm.CACHE_DB = cache_path


def _step_stock_list():
    from backend.data_manager import update_stock_list
    return update_stock_list() or 0

def _step_kline():
    from backend.data_manager import update_kline
    return update_kline(catch_up_days=10) or 0

def _step_spot():
    from backend.data_manager import cache_spot_from_akshare
    return cache_spot_from_akshare() or 0

def _step_sectors():
    from backend.data_manager import cache_sectors_from_akshare
    return cache_sectors_from_akshare() or 0

def _step_north_flow():
    from backend.data_manager import cache_north_flow_from_akshare
    return cache_north_flow_from_akshare() or 0

def _step_limit_up():
    from backend.data_manager import cache_limit_up_from_akshare
    return cache_limit_up_from_akshare() or 0

def _step_lhb():
    from backend.data_manager import cache_lhb_from_akshare
    return cache_lhb_from_akshare() or 0

def _step_high_low():
    from backend.data_manager import cache_high_low_from_akshare
    return cache_high_low_from_akshare() or 0

def _step_fund_flow():
    from backend.cache_modules import cache_fund_flow_from_akshare
    return cache_fund_flow_from_akshare() or 0

def _step_lhb_daily(db_path):
    from backend.data_lhb import update_lhb_daily
    return update_lhb_daily(db_path, days_back=3) or 0

def _step_weekly():
    from backend.data_manager import build_weekly_kline
    return build_weekly_kline() or 0


STEP_DEFS = [
    ("\u65e5K\u7ebf",           _step_kline,        False),
    ("\u5b9e\u65f6\u884c\u60c5", _step_spot,         False),
    ("\u677f\u5757\u884c\u60c5", _step_sectors,      False),
    ("\u5317\u5411\u8d44\u91d1", _step_north_flow,   False),
    ("\u6da8\u505c\u677f",       _step_limit_up,      False),
    ("\u9f99\u864e\u699c",       _step_lhb,           False),
    ("\u521b\u65b0\u9ad8/\u4f4e", _step_high_low,    False),
    ("\u8d44\u91d1\u6d41\u5411", _step_fund_flow,    False),
    ("\u9f99\u864e\u699c\u8be6\u60c5", None,          True),
    ("\u5468K\u7ebf",           _step_weekly,         False),
]


class UpdateWorker(QThread):
    progress = pyqtSignal(str, object)
    finished = pyqtSignal(object)

    def __init__(self, db_path, cache_path, single_step=None):
        super().__init__()
        self.db_path = db_path
        self.cache_path = cache_path
        self.single_step = single_step

    def run(self):
        _patch_paths(self.db_path, self.cache_path)
        if self.single_step:
            self._run_single()
        else:
            self._run_all()

    def _run_all(self):
        start_time = time.time()
        results = []
        total = 0
        try:
            for step_name, step_fn, needs_db in STEP_DEFS:
                fn = step_fn
                if needs_db:
                    fn = lambda db=self.db_path: _step_lhb_daily(db)
                try:
                    r = fn()
                    results.append({"name": step_name, "rows": r, "ok": True})
                    total += r
                    self.progress.emit(step_name, {"rows": r, "ok": True})
                except Exception as e:
                    results.append({"name": step_name, "rows": 0, "ok": False, "error": str(e)[:120]})
                    self.progress.emit(step_name, {"rows": 0, "ok": False, "error": str(e)[:120]})
            elapsed = round(time.time() - start_time, 1)
            self._write_log(total, results, elapsed)
            self.finished.emit({"ok": True, "total_rows": total, "steps": results, "elapsed": elapsed})
        except Exception as e:
            self.finished.emit({"ok": False, "error": str(e)})

    def _run_single(self):
        fn = None
        for step_name, step_fn, needs_db in STEP_DEFS:
            if step_name == self.single_step:
                fn = step_fn
                if needs_db:
                    fn = lambda db=self.db_path: _step_lhb_daily(db)
                break
        if not fn:
            self.finished.emit({"ok": False, "error": f"Unknown step: {self.single_step}"})
            return
        try:
            r = fn()
            self.progress.emit(self.single_step, {"rows": r, "ok": True})
            self.finished.emit({"ok": True, "total_rows": r, "step_name": self.single_step})
        except Exception as e:
            self.progress.emit(self.single_step, {"rows": 0, "ok": False, "error": str(e)[:120]})
            self.finished.emit({"ok": False, "error": str(e), "step_name": self.single_step})

    def _write_log(self, total_rows, results, elapsed):
        try:
            conn = sqlite3.connect(self.db_path)
            ok_count = sum(1 for r in results if r["ok"])
            fail_count = sum(1 for r in results if not r["ok"])
            conn.execute(
                "INSERT INTO data_update_log (update_date, stocks_total, rows_added, "
                "status, message, duration_sec) VALUES (?,?,?,?,?,?)",
                (datetime.now().strftime("%Y-%m-%d"), 0, total_rows,
                 "ok" if fail_count == 0 else "partial",
                 f"{ok_count}/{len(results)} steps ok, {elapsed}s",
                 elapsed)
            )
            conn.commit()
            conn.close()
        except Exception:
            pass
