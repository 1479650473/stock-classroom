# AGENTS.md — AI Assistant Context

## Project Identity
- **Name**: stock-classroom (A股量化教室)
- **Version**: v4.2.0
- **Type**: PyQt5 Desktop App + Optional Flask API
- **Python**: 3.14.3
- **Database**: SQLite triple (kline.db + stock_cache.db + sim_trade.db)
- **Data Source**: AKShare / Sina API

## Architecture (plugin-based, v4.0+)
```
Platform Shell (~300 lines, immutable)
  └─ PluginManager → discovers from frontend/plugins/
      └─ Each plugin: IPlugin subclass in plugin.py
```

**Key principle**: Platform never imports panel code directly. Plugins fail in isolation.

## Key Files
| Layer | Files | Purpose |
|-------|-------|---------|
| Entry | `desktop_app.py` (~30 lines) | App bootstrap |
| Platform | `frontend/platform/platform_shell.py` | Main window shell |
| Platform | `frontend/platform/plugin_manager.py` | Discover/register/activate/ErrorBoundary |
| Platform | `frontend/platform/plugin_base.py` | IPlugin interface, PlatformBus signals, PlatformServices |
| Platform | `frontend/platform/theme.py` | `build_style(base_fs)`, `fs()`, `dp()`, COLORS |
| Backend | `backend/data_manager.py` | SQLite CRUD, AKShare dispatch |
| Backend | `backend/akshare_source.py` | ~18 API wrappers + diagnose |
| Backend | `backend/indicators.py` | MACD/RSI/BOLL |
| Backend | `backend/factor_engine/` | Multi-factor scoring engine |
| Backend | `backend/trade_engine/` | **Simulated trading engine (v4.2)** |
| Settings | `frontend/plugins/settings/config.py` | `load_settings()` / `save_settings()` → `backend/configs/settings.json` |
| Configs | `backend/configs/settings.json` | `font_size` + `window_size` + `agent{api_base, api_key, model}` |

## Plugins (all in `frontend/plugins/`, 11 total)
| ID | Region | Description |
|----|--------|-------------|
| search | TOPBAR | Stock search input |
| settings | TOPBAR | Gear button → settings (font + window size + AI config) |
| agent | TOPBAR | Star button → floating AI chat (6-tool function calling) |
| market | LEFT | Market overview + sectors |
| picks | LEFT | Factor scoring Top 20 |
| holdings | LEFT | Portfolio panel |
| trade | LEFT | **Simulated trading panel (v4.2)** |
| datapipeline | LEFT | Data update pipeline (11 steps) |
| datacenter | LEFT | Database browser + table details |
| trainer | LEFT | **Backtest training placeholder (v4.2)** |
| kline | RIGHT | K-line chart (QPainter) |

## Navigation Order
`frontend/plugins/plugins.json` → `nav_order`: search, settings, agent, market, picks, holdings, trade, datapipeline, datacenter, trainer, kline

## Theme (v4.2)
- Dark: `#0D1117` (bg) / `#161B22` (panel) / `#D4A574` (accent gold)
- `theme.py`: `build_style(base_fs)` dynamically generates CSS with `$fs` placeholder
- `fs()` helper: font scaling (19-23px range at base 21)
- `dp()` / `dps()` helpers: widget dimension scaling (~1.62x at base 21)
- Default settings: font_size=21, window_size=large (1980×1280)

## Naming Conventions
- Plugin files: `plugin.py`, `panel.py`, `companion.py`
- Backend: `backend/` contains all data logic
- Style: `C_BG`, `C_PANEL`, `C_BORDER`, `C_TEXT`, `C_SUBTEXT`, `C_ACCENT`
- Chinese UI text everywhere
- Widget dimensions: use `dp(x)` not hardcoded px

## Build
```bat
package\build_desktop.bat
```
Output: `dist/StockClassroom/` (~285 MB). Requires `kline.db` + `stock_cache.db` in `data/`.

## Dependencies
Core: `flask`, `PyQt5`, `akshare`, `pandas`, `requests`, `py_mini_racer`, `openai`

## Git
Remote: `https://github.com/1479650473/stock-classroom`
