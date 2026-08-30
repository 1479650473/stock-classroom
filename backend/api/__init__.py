# -*- coding: utf-8 -*-
"""stock-classroom Web API v2.

Flask blueprint package powering the new Tauri/Vue frontend. Reuses the
existing backend domain modules (data_manager / trade_engine / strategy /
akshare_source) — this package only exposes them over REST.

Layout:
  paths.py          — project/data/db paths
  envelope.py       — uniform {code,data,message} / {code,error} envelopes
  jobman.py         — in-process JobManager (thread pool + SSE stream)
  settings_store.py — read/write backend/configs/settings.json
  server.py         — create_app() factory, registers all blueprints
  blueprints/       — one module per domain (system, market, trade, ...)
"""
