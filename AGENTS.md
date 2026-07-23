# AGENTS.md — AI Assistant Context

## Project Identity
- **Name**: stock-classroom (A股量化教室)
- **Version**: v4.1.0
- **Type**: PyQt5 Desktop App + Optional Flask API
- **Python**: 3.14.3
- **Database**: SQLite dual (kline.db + stock_cache.db)
- **Data Source**: AKShare / Sina API

## Architecture (plugin-based, v4.0+)
```
Platform Shell (~200 lines, immutable)
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
| Platform | `frontend/platform/theme.py` | `build_style(base_fs)`, `fs()`, COLORS |
| Backend | `backend/data_manager.py` | SQLite CRUD, AKShare dispatch |
| Backend | `backend/akshare_source.py` | ~18 API wrappers + diagnose |
| Backend | `backend/indicators.py` | MACD/RSI/BOLL |
| Backend | `backend/factor_engine/` | Multi-factor scoring engine |
| Settings | `frontend/plugins/settings/config.py` | `load_settings()` / `save_settings()` → `backend/configs/settings.json` |
| Configs | `backend/configs/settings.json` | `font_size` + `agent{api_base, api_key, model}` |

## Plugins (all in `frontend/plugins/`)
| ID | Region | Description |
|----|--------|-------------|
| search | TOPBAR | Stock search input |
| settings | TOPBAR | Gear button → settings dialog (font + AI config) |
| agent | TOPBAR | Star button → floating AI chat window |
| market | LEFT | Market overview + sectors |
| picks | LEFT | Factor scoring Top 20 |
| holdings | LEFT | Portfolio panel |
| datapipeline | LEFT | Data update pipeline (11 steps) |
| datacenter | LEFT | Database browser + table details |
| kline | RIGHT | K-line chart (QPainter) |

## Navigation Order
`frontend/plugins/plugins.json` → `nav_order`: search, settings, agent, market, picks, holdings, datapipeline, datacenter, kline

## Theme
- Dark: `#0D1117` (bg) / `#161B22` (panel) / `#D4A574` (accent gold)
- `theme.py`: `build_style(base_fs)` dynamically generates CSS with `$fs` placeholder
- `fs()` helper converts base font size to px strings
- Default font size: 13px (stored in settings.json)

## Naming Conventions
- Plugin files: `plugin.py`, `panel.py`, `companion.py`
- Backend: `backend/` contains all data logic
- Style: `C_BG`, `C_PANEL`, `C_BORDER`, `C_TEXT`, `C_SUBTEXT`, `C_ACCENT`
- Chinese UI text everywhere (avoid English labels)

## Build
```bat
package\build_desktop.bat
```
Output: `dist/StockClassroom/` (~285 MB). Requires `kline.db` + `stock_cache.db` in `data/`.

## Dependencies
Core: `flask`, `PyQt5`, `akshare`, `pandas`, `requests`, `py_mini_racer`, `openai`

## Git
Remote: `https://github.com/1479650473/stock-classroom`
