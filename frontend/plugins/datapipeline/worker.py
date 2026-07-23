# -*- coding: utf-8 -*-
"""Background data update worker for DataPipeline plugin."""

import sys, os, traceback, time, sqlite3
from datetime import datetime
from PyQt5.QtCore import QThread, pyqtSignal


class UpdateWorker(QThread):
    progress = pyqtSignal(str, object)
    finished = pyqtSignal(object)

    def __init__(self, db_path, cache_path):
        super().__init__()
        self.db_path = db_path
        self.cache_path = cache_path

    def run(self):
        start_time = time.time()
        results = []
        total = 0

        try:
            # Patch data_manager paths before any update functions access them
            import backend.data_manager as dm
            dm.KLINE_DB = self.db_path
            dm.CACHE_DB = self.cache_path

            steps = [
                ("\u80a1\u7968\u5217\u8868", self._step_stock_list),
                ("\u65e5K\u7ebf", self._step_kline),
                ("\u5b9e\u65f6\u884c\u60c5", self._step_spot),
                ("\u677f\u5757\u884c\u60c5", self._step_sectors),
                ("\u5317\u5411\u8d44\u91d1", self._step_north_flow),
                ("\u6da8\u505c\u677f", self._step_limit_up),
                ("\u9f99\u864e\u699c", self._step_lhb),
                ("\u521b\u65b0\u9ad8/\u4f4e", self._step_high_low),
                ("\u8d44\u91d1\u6d41\u5411", self._step_fund_flow),
                ("\u9f99\u864e\u699c\u8be6\u60c5", self._step_lhb_daily),
                ("\u5468K\u7ebf", self._step_weekly),
            ]

            for step_name, step_fn in steps:
                try:
                    r = step_fn()
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

    def _step_stock_list(self):
        from backend.data_manager import update_stock_list
        n = update_stock_list()
        return n or 0

    def _step_kline(self):
        from backend.data_manager import update_kline
        return update_kline(catch_up_days=10) or 0

    def _step_spot(self):
        from backend.data_manager import cache_spot_from_akshare
        return cache_spot_from_akshare() or 0

    def _step_sectors(self):
        from backend.data_manager import cache_sectors_from_akshare
        return cache_sectors_from_akshare() or 0

    def _step_north_flow(self):
        from backend.data_manager import cache_north_flow_from_akshare
        return cache_north_flow_from_akshare() or 0

    def _step_limit_up(self):
        from backend.data_manager import cache_limit_up_from_akshare
        return cache_limit_up_from_akshare() or 0

    def _step_lhb(self):
        from backend.data_manager import cache_lhb_from_akshare
        return cache_lhb_from_akshare() or 0

    def _step_high_low(self):
        from backend.data_manager import cache_high_low_from_akshare
        return cache_high_low_from_akshare() or 0

    def _step_fund_flow(self):
        from backend.cache_modules import cache_fund_flow_from_akshare
        r = cache_fund_flow_from_akshare()
        return r or 0

    def _step_lhb_daily(self):
        from backend.data_lhb import update_lhb_daily
        return update_lhb_daily(self.db_path, days_back=3) or 0

    def _step_weekly(self):
        from backend.data_manager import build_weekly_kline
        return build_weekly_kline() or 0

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
