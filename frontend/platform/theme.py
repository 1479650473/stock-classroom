# -*- coding: utf-8 -*-
"""Design system for stock-classroom — multi-theme engine.

Palette + QSS fragments are generated from one of three full themes
(Graphite / Obsidian / Ivory). Plugins should read tokens via the module
constants (C_BG, C_TEXT, ...) or the shared helpers (qss_*, premium.*), which
all read from the ACTIVE theme, so a theme switch restyles the whole app.

Keep the public API stable: fs(), fsi(), dp(), dps(), C_* constants,
style_*(), qss_*(), build_style(). A theme is set once at startup via
set_theme(key) (or build_style(key)); the C_* module attrs stay in sync.
"""

from typing import Dict

from PyQt5.QtCore import QObject, pyqtSignal

FONT_BASE = 13


class _ThemeSignals(QObject):
    """Emitted when the active theme changes (for immediate re-render)."""
    changed = pyqtSignal()


signals = _ThemeSignals()

# ──────────────────────────────────────────────────────────────
#  Theme registry — three full visual directions
# ──────────────────────────────────────────────────────────────

THEMES: Dict[str, dict] = {
    "graphite": {
        "name": "石墨 · 冷调极简", "dark": True,
        "bg": "#0B0D11", "panel": "#14171C", "raised": "#1A1E24", "overlay": "#20252C",
        "border": "#232830", "border_soft": "#1D222A", "border_top": "#2E343C",
        "text": "#E8EAED", "sub": "#9AA3B0", "faint": "#5C6670",
        "accent": "#7AA2F7", "accent_hover": "#8FB4FF",
        "accent_dim": "rgba(122,162,247,0.12)", "on_accent": "#0A0C10",
        "up": "#E5484D", "down": "#3FB950", "info": "#7AA2F7", "warn": "#D29922",
        # card: flat panel + hairline + subtle top light (no heavy gradient)
        "card_stops": ["#15181D", "#12151A", "#0E1115"],
        "card_border": "#232830", "card_border_top": "#2E343C",
        "card_hover_border": "#333B45",
        "radius_card": 9, "radius_btn": 6, "radius_input": 6,
        "sel_bg": "rgba(122,162,247,0.15)", "sel_fg": "#AFC8FF",
        "row_alt": "#12151A",
        "scroll_handle": "#2A313B", "scroll_hover": "#3A434F",
        "btn_grad": ["#1A1E24", "#14171C"], "btn_grad_hover": ["#20262E", "#181C22"],
        "btn_border_top": "#394049", "btn_text": "#DDE2E8", "btn_text_hover": "#F0F3F8",
        "accent_grad": ["#8AB2FF", "#6C9DF2"], "accent_grad_hover": ["#9CC0FF", "#7BA8F6"],
        "accent_border": "#7AA2F7",
        "progress_grad": ["#7AA2F7", "#9BC0FF"],
        "nav_check_border": "#7AA2F7",
    },
    "obsidian": {
        "name": "黑曜石 · 仪器质感", "dark": True,
        "bg": "#060708", "panel": "#0E1012", "raised": "#14171A", "overlay": "#191C1F",
        "border": "#000000", "border_soft": "#111316", "border_top": "#2C3036",
        "text": "#E8E3DA", "sub": "#9AA0A6", "faint": "#5E646B",
        "accent": "#E0A050", "accent_hover": "#EDB97A",
        "accent_dim": "rgba(224,160,80,0.12)", "on_accent": "#1A120A",
        "up": "#E0564D", "down": "#3FB950", "info": "#E0A050", "warn": "#D29922",
        # machined inner well: set in theme template via obsidian-specific rules
        "card_stops": ["#111315", "#0D0F11", "#0A0B0D"],
        "card_border": "#000000", "card_border_top": "#2A2F34",
        "card_hover_border": "#5C4630",
        "radius_card": 8, "radius_btn": 6, "radius_input": 6,
        "sel_bg": "rgba(224,160,80,0.15)", "sel_fg": "#F2D8AE",
        "row_alt": "#0D0F11",
        "scroll_handle": "#23272C", "scroll_hover": "#4A3D2A",
        "btn_grad": ["#111316", "#0C0E10"], "btn_grad_hover": ["#191C20", "#111418"],
        "btn_border_top": "#2A2F34", "btn_text": "#D6D1C8", "btn_text_hover": "#EDE7DC",
        "accent_grad": ["#C99B5E", "#A87C45"], "accent_grad_hover": ["#DBB27A", "#B98D50"],
        "accent_border": "#C99B5E",
        "progress_grad": ["#C99B5E", "#E0B878"],
        "nav_check_border": "#E0A050",
    },
    "ivory": {
        "name": "象牙 · 暖纸编辑风", "dark": False,
        "bg": "#F3EEE6", "panel": "#FBF8F2", "raised": "#FFFFFF", "overlay": "#EFEAE0",
        "border": "#E2DBCC", "border_soft": "#ECE5D8", "border_top": "#D8CFBE",
        "text": "#1C1917", "sub": "#8A8177", "faint": "#B4AC9F",
        "accent": "#8E3A2F", "accent_hover": "#A04A3D",
        "accent_dim": "rgba(142,58,47,0.10)", "on_accent": "#F7F2EA",
        "up": "#8E3A2F", "down": "#3F7D50", "info": "#8E3A2F", "warn": "#B07A2A",
        # paper: light surface + hairline + crisp
        "card_stops": ["#FDFBF5", "#FBF8F2", "#F6F1E6"],
        "card_border": "#E4DCCE", "card_border_top": "#D9CFBE",
        "card_hover_border": "#C7BA9F",
        "radius_card": 3, "radius_btn": 22, "radius_input": 6,
        "sel_bg": "rgba(142,58,47,0.12)", "sel_fg": "#7A2F25",
        "row_alt": "#F6F1E6",
        "scroll_handle": "#DCD3C2", "scroll_hover": "#C3B79C",
        "btn_grad": ["#2A2621", "#1C1917"], "btn_grad_hover": ["#3A352D", "#242019"],
        "btn_border_top": "#3E372C", "btn_text": "#F3EEE6", "btn_text_hover": "#FFFFFF",
        "accent_grad": ["#9A4638", "#7A2F25"], "accent_grad_hover": ["#A55445", "#87352A"],
        "accent_border": "#8E3A2F",
        "progress_grad": ["#8E3A2F", "#A04A3D"],
        "nav_check_border": "#8E3A2F",
    },
}

DEFAULT_THEME = "graphite"
_current_key = DEFAULT_THEME

# Backwards-compatible map (kline widget etc.) — populated by set_theme()
COLORS = {
    "ma5": "#F0A56A", "ma10": "#5DADE2", "ma20": "#AF7AC5", "ma60": "#F7DC6F",
    "dif": "#FF6B6B",
}


def _t(key):
    return THEMES[_current_key][key]


def current_theme() -> dict:
    """Return the active theme dict."""
    return THEMES[_current_key]


def theme_key() -> str:
    return _current_key


def set_theme(key: str) -> None:
    """Set the active theme and re-sync the module C_* constants."""
    global _current_key
    if key not in THEMES:
        key = DEFAULT_THEME
    _current_key = key
    t = THEMES[key]
    # re-sync module-level palette constants (so `from theme import C_BG` and
    # later `import theme; theme.C_BG` both reflect the active theme)
    globals().update({
        "C_BG": t["bg"], "C_PANEL": t["panel"], "C_RAISED": t["raised"],
        "C_OVERLAY": t["overlay"], "C_BORDER": t["border"],
        "C_BORDER_SOFT": t["border_soft"], "C_TEXT": t["text"],
        "C_SUBTEXT": t["sub"], "C_FAINT": t["faint"], "C_ACCENT": t["accent"],
        "C_ACCENT_HOVER": t["accent_hover"], "C_ACCENT_DIM": t["accent_dim"],
        "C_ON_ACCENT": t["on_accent"], "C_UP": t["up"], "C_DOWN": t["down"],
        "C_INFO": t["info"], "C_WARN": t["warn"],
    })
    globals()["COLORS"].update({
        "bg": t["bg"], "panel": t["panel"], "border": t["border_soft"],
        "text": t["text"], "subtext": t["sub"], "accent": t["accent"],
        "rise": t["up"], "fall": t["down"], "hover": t["raised"],
    })
    if signals.receivers(signals.changed):
        signals.changed.emit()


# sync to defaults at import
set_theme(DEFAULT_THEME)


# ──────────────────────────────────────────────────────────────
#  Scaling helpers
# ──────────────────────────────────────────────────────────────

def fs(size: int) -> str:
    return f"{round(size * FONT_BASE / 13)}px"


def fsi(size: int) -> int:
    return round(size * FONT_BASE / 13)


def dp(size: int) -> int:
    return round(size * FONT_BASE / 13)


def dps(size: int) -> str:
    return f"{dp(size)}px"


# ──────────────────────────────────────────────────────────────
#  Reusable QSS fragments (built from the active theme)
# ──────────────────────────────────────────────────────────────

def qss_card(radius: int = None) -> str:
    r = _t("radius_card") if radius is None else radius
    s = _t("card_stops")
    return (
        f"QFrame#card{{background:qlineargradient(x1:0,y1:0,x2:0,y2:1,"
        f"stop:0 {s[0]},stop:0.5 {s[1]},stop:1 {s[2]});"
        f"border:1px solid {_t('card_border')};border-top:1px solid {_t('card_border_top')};"
        f"border-radius:{dps(r)};}}"
        f"QFrame#card:hover{{border-top-color:{_t('card_hover_border')};;border-color:{_t('raised')};}}"
    )


def qss_btn() -> str:
    if _current_key == "obsidian":
        return _obsidian_btn()
    if _current_key == "graphite":
        return _graphite_btn()
    if _current_key == "ivory":
        return _ivory_btn()
    g, gh = _t("btn_grad"), _t("btn_grad_hover")
    return (f"QPushButton{{background:qlineargradient(x1:0,y1:0,x2:0,y2:1,"
            f"stop:0 {g[0]},stop:1 {g[1]});color:{_t('btn_text')};"
            f"border:1px solid {_t('border')};border-top:1px solid {_t('btn_border_top')};"
            f"border-radius:{dps(_t('radius_btn'))};padding:{dps(4)} {dps(12)};"
            f"font-size:{fs(12)};font-weight:500;}}"
            f"QPushButton:hover{{background:qlineargradient(x1:0,y1:0,x2:0,y2:1,"
            f"stop:0 {gh[0]},stop:1 {gh[1]});border-top-color:{_t('accent')};color:{_t('btn_text_hover')};}}"
            f"QPushButton:pressed{{background:{_t('bg')};border-top-color:{_t('card_border')};}}"
            f"QPushButton:disabled{{color:{_t('faint')};border-color:{_t('border_soft')};}}")


def qss_btn_accent() -> str:
    if _current_key == "obsidian":
        return _obsidian_btn_accent()
    if _current_key == "graphite":
        return _graphite_btn_accent()
    if _current_key == "ivory":
        return _ivory_btn_accent()
    a, ah = _t("accent_grad"), _t("accent_grad_hover")
    return (f"QPushButton{{background:qlineargradient(x1:0,y1:0,x2:0,y2:1,"
            f"stop:0 {a[0]},stop:1 {a[1]});color:{_t('on_accent')};border:none;"
            f"border-radius:{dps(_t('radius_btn'))};padding:{dps(5)} {dps(14)};"
            f"font-size:{fs(12)};font-weight:600;}}"
            f"QPushButton:hover{{background:qlineargradient(x1:0,y1:0,x2:0,y2:1,"
            f"stop:0 {ah[0]},stop:1 {ah[1]});}}"
            f"QPushButton:pressed{{background:{_t('accent')};}}"
            f"QPushButton:disabled{{background:{_t('overlay')};color:{_t('faint')};}}")


def qss_btn_accent_outline() -> str:
    if _current_key == "obsidian":
        return _obsidian_btn_accent_outline()
    c = _t("accent")
    return (f"QPushButton{{background:{_t('accent_dim')};color:{c};"
            f"border:1px solid {c};border-top:1px solid {_t('accent_hover')};"
            f"border-radius:{dps(_t('radius_btn'))};padding:{dps(4)} {dps(12)};"
            f"font-size:{fs(12)};font-weight:600;}}"
            f"QPushButton:hover{{background:{_t('accent_dim')};color:{_t('accent_hover')};}}"
            f"QPushButton:disabled{{color:{_t('faint')};border-color:{_t('border_soft')};background:transparent;}}")


def qss_input() -> str:
    if _current_key == "obsidian":
        return _obsidian_input()
    if _current_key == "graphite":
        return _graphite_input()
    if _current_key == "ivory":
        return _ivory_input()
    return (f"QLineEdit{{background:{_t('panel')};color:{_t('text')};"
            f"border:1px solid {_t('border')};border-top:1px solid {_t('border_top')};"
            f"border-radius:{dps(_t('radius_input'))};padding:{dps(5)} {dps(10)};font-size:{fs(12)};}}"
            f"QLineEdit:focus{{border-color:{_t('accent')};}}"
            f"QLineEdit:disabled{{color:{_t('faint')};}}")


def qss_combo() -> str:
    if _current_key == "obsidian":
        return _obsidian_combo()
    if _current_key == "graphite":
        return _graphite_combo()
    if _current_key == "ivory":
        return _ivory_combo()
    return (f"QComboBox{{background:{_t('panel')};color:{_t('text')};"
            f"border:1px solid {_t('border')};border-top:1px solid {_t('border_top')};"
            f"border-radius:{dps(_t('radius_input'))};padding:{dps(4)} {dps(10)};font-size:{fs(12)};}}"
            f"QComboBox:hover{{border-top-color:{_t('accent')};}}"
            f"QComboBox::drop-down{{border:none;width:{dps(24)};}}"
            f"QComboBox QAbstractItemView{{background:{_t('panel')};color:{_t('text')};"
            f"border:1px solid {_t('border')};border-radius:{dps(5)};"
            f"selection-background-color:{_t('sel_bg')};selection-color:{_t('sel_fg')};outline:none;}}")


def qss_spinbox() -> str:
    if _current_key == "obsidian":
        return _obsidian_spinbox()
    if _current_key == "graphite":
        return _graphite_spinbox()
    if _current_key == "ivory":
        return _ivory_spinbox()
    return (f"QSpinBox,QDoubleSpinBox{{background:{_t('panel')};color:{_t('text')};"
            f"border:1px solid {_t('border')};border-radius:{dps(_t('radius_input'))};"
            f"padding:{dps(4)} {dps(8)};font-size:{fs(12)};}}"
            f"QSpinBox:focus,QDoubleSpinBox:focus{{border-color:{_t('accent')};}}")


# ── Obsidian machined controls (metal edge + recessed/sunk well) ──────────
def _mach_recess(g, bt, radius, pad_v, pad_h, fsize):
    """Recessed machined body: top lip shadow + light bottom catch + bowl gradient."""
    return (f"background:qlineargradient(x1:0,y1:0,x2:0,y2:1,"
            f"stop:0 {g[0]},stop:0.58 {g[1]},stop:1 {g[0]});"
            f"border:1px solid #050607;border-top:1px solid #000;"
            f"border-bottom:1px solid {bt};border-left:1px solid #050607;border-right:1px solid #050607;"
            f"border-radius:{dps(radius)};padding:{dps(pad_v)} {dps(pad_h)};font-size:{fs(fsize)};")


def _obsidian_btn() -> str:
    t = _t
    g, gh = t("btn_grad"), t("btn_grad_hover")
    return (
        f"QPushButton{{{_mach_recess(g, t('btn_border_top'), t('radius_btn'), 4, 12, 12)}"
        f"color:{t('btn_text')};font-weight:500;}}"
        f"QPushButton:hover{{background:qlineargradient(x1:0,y1:0,x2:0,y2:1,"
        f"stop:0 {gh[0]},stop:1 {gh[1]});border-top-color:{t('accent')};"
        f"border-bottom-color:{t('card_hover_border')};color:{t('btn_text_hover')};}}"
        f"QPushButton:pressed{{background:{t('bg')};border-top-color:{t('btn_border_top')};border-bottom-color:#000;}}"
        f"QPushButton:disabled{{color:{t('faint')};border-color:{t('border_soft')};}}"
    )


def _obsidian_btn_accent() -> str:
    t = _t
    a = t("accent_grad")
    return (
        f"QPushButton{{background:qlineargradient(x1:0,y1:0,x2:0,y2:1,"
        f"stop:0 {a[0]},stop:0.5 {a[0]},stop:1 {a[1]});color:{t('on_accent')};"
        f"border:1px solid #000;border-top:1px solid {t('accent_hover')};"
        f"border-bottom:1px solid #000;border-left:1px solid #000;border-right:1px solid #000;"
        f"border-radius:{dps(t('radius_btn'))};padding:{dps(5)} {dps(14)};font-size:{fs(12)};font-weight:600;}}"
        f"QPushButton:hover{{background:qlineargradient(x1:0,y1:0,x2:0,y2:1,"
        f"stop:0 {a[0]},stop:1 {a[0]});border-top-color:{t('accent_hover')};}}"
        f"QPushButton:pressed{{background:{t('accent')};border-top-color:#000;}}"
        f"QPushButton:disabled{{background:{t('overlay')};color:{t('faint')};}}"
    )


def _obsidian_btn_accent_outline() -> str:
    t = _t
    c = t("accent")
    return (
        f"QPushButton{{background:{t('accent_dim')};color:{c};"
        f"border:1px solid #050607;border-top:1px solid #000;border-bottom:1px solid {c};"
        f"border-left:1px solid #050607;border-right:1px solid #050607;"
        f"border-radius:{dps(t('radius_btn'))};padding:{dps(4)} {dps(12)};font-size:{fs(12)};font-weight:600;}}"
        f"QPushButton:hover{{background:{t('accent_dim')};color:{t('accent_hover')};border-top-color:{t('accent')};}}"
        f"QPushButton:disabled{{color:{t('faint')};border-color:{t('border_soft')};background:transparent;}}"
    )


def _obsidian_input() -> str:
    t = _t
    g, bt = t("btn_grad"), t("btn_border_top")
    return (
        f"QLineEdit{{{_mach_recess(g, bt, t('radius_input'), 5, 10, 12)}color:{t('text')};}}"
        f"QLineEdit:focus{{border-color:{t('accent')};border-bottom-color:{t('accent_hover')};}}"
        f"QLineEdit:disabled{{color:{t('faint')};}}"
    )


def _obsidian_combo() -> str:
    t = _t
    g, bt = t("btn_grad"), t("btn_border_top")
    return (
        f"QComboBox{{{_mach_recess(g, bt, t('radius_input'), 4, 10, 12)}color:{t('text')};}}"
        f"QComboBox:hover{{border-top-color:{t('accent')};border-bottom-color:{t('card_hover_border')};}}"
        f"QComboBox::drop-down{{border:none;width:{dps(24)};}}"
        f"QComboBox QAbstractItemView{{background:{t('panel')};color:{t('text')};"
        f"border:1px solid {t('border')};border-radius:{dps(5)};"
        f"selection-background-color:{t('sel_bg')};selection-color:{t('sel_fg')};outline:none;}}"
    )


def _obsidian_spinbox() -> str:
    t = _t
    g, bt = t("btn_grad"), t("btn_border_top")
    return (
        f"QSpinBox,QDoubleSpinBox{{{_mach_recess(g, bt, t('radius_input'), 4, 8, 12)}color:{t('text')};}}"
        f"QSpinBox:focus,QDoubleSpinBox:focus{{border-color:{t('accent')};border-bottom-color:{t('accent_hover')};}}"
    )


# ── Graphite cold-steel controls (plate edge + faint recess) ──────────────
def _graphite_btn() -> str:
    t = _t
    g, gh = t("btn_grad"), t("btn_grad_hover")
    return (
        f"QPushButton{{background:qlineargradient(x1:0,y1:0,x2:0,y2:1,"
        f"stop:0 {g[0]},stop:1 {g[1]});color:{t('btn_text')};"
        f"border:1px solid {t('border')};border-top:1px solid {t('border_top')};"
        f"border-bottom:1px solid {t('border_top')};"
        f"border-radius:{dps(t('radius_btn'))};padding:{dps(4)} {dps(12)};font-size:{fs(12)};font-weight:500;}}"
        f"QPushButton:hover{{background:qlineargradient(x1:0,y1:0,x2:0,y2:1,"
        f"stop:0 {gh[0]},stop:1 {gh[1]});border-top-color:{t('accent')};color:{t('btn_text_hover')};}}"
        f"QPushButton:pressed{{background:{t('bg')};border-top-color:{t('border')};}}"
        f"QPushButton:disabled{{color:{t('faint')};border-color:{t('border_soft')};}}"
    )


def _graphite_btn_accent() -> str:
    t = _t
    a, ah = t("accent_grad"), t("accent_grad_hover")
    return (
        f"QPushButton{{background:qlineargradient(x1:0,y1:0,x2:0,y2:1,"
        f"stop:0 {a[0]},stop:1 {a[1]});color:{t('on_accent')};"
        f"border:1px solid {t('accent_border')};border-top:1px solid {t('accent_hover')};"
        f"border-bottom:1px solid {t('border')};"
        f"border-radius:{dps(t('radius_btn'))};padding:{dps(5)} {dps(14)};font-size:{fs(12)};font-weight:600;}}"
        f"QPushButton:hover{{background:qlineargradient(x1:0,y1:0,x2:0,y2:1,"
        f"stop:0 {ah[0]},stop:1 {ah[1]});border-top-color:{t('accent_hover')};}}"
        f"QPushButton:disabled{{background:{t('overlay')};color:{t('faint')};}}"
    )


def _graphite_input() -> str:
    t = _t
    return (
        f"QLineEdit{{background:qlineargradient(x1:0,y1:0,x2:0,y2:1,"
        f"stop:0 {t('raised')},stop:0.6 {t('panel')},stop:1 {t('raised')});color:{t('text')};"
        f"border:1px solid {t('border_soft')};border-top:1px solid {t('border')};"
        f"border-bottom:1px solid {t('border_top')};"
        f"border-radius:{dps(t('radius_input'))};padding:{dps(5)} {dps(10)};font-size:{fs(12)};}}"
        f"QLineEdit:focus{{border-color:{t('accent')};border-bottom-color:{t('accent_hover')};}}"
        f"QLineEdit:disabled{{color:{t('faint')};}}"
    )


def _graphite_combo() -> str:
    t = _t
    body = (f"background:qlineargradient(x1:0,y1:0,x2:0,y2:1,"
            f"stop:0 {t('raised')},stop:0.6 {t('panel')},stop:1 {t('raised')});color:{t('text')};"
            f"border:1px solid {t('border_soft')};border-top:1px solid {t('border')};"
            f"border-bottom:1px solid {t('border_top')};"
            f"border-radius:{dps(t('radius_input'))};padding:{dps(4)} {dps(10)};font-size:{fs(12)};")
    return (f"QComboBox{{{body}}}"
            f"QComboBox:hover{{border-top-color:{t('accent')};}}"
            f"QComboBox::drop-down{{border:none;width:{dps(24)};}}"
            f"QComboBox QAbstractItemView{{background:{t('panel')};color:{t('text')};"
            f"border:1px solid {t('border')};border-radius:{dps(5)};"
            f"selection-background-color:{t('sel_bg')};selection-color:{t('sel_fg')};outline:none;}}"
            )


def _graphite_spinbox() -> str:
    t = _t
    body = (f"background:qlineargradient(x1:0,y1:0,x2:0,y2:1,"
            f"stop:0 {t('raised')},stop:0.6 {t('panel')},stop:1 {t('raised')});color:{t('text')};"
            f"border:1px solid {t('border_soft')};border-top:1px solid {t('border')};"
            f"border-bottom:1px solid {t('border_top')};"
            f"border-radius:{dps(t('radius_input'))};padding:{dps(4)} {dps(8)};font-size:{fs(12)};")
    return (f"QSpinBox,QDoubleSpinBox{{{body}}}"
            f"QSpinBox:focus,QDoubleSpinBox:focus{{border-color:{t('accent')};border-bottom-color:{t('accent_hover')};}}"
            )


# ── Ivory paper controls (debossed into paper + ink chips) ────────────────
def _ivory_btn() -> str:
    t = _t
    g, gh = t("btn_grad"), t("btn_grad_hover")
    return (
        f"QPushButton{{background:qlineargradient(x1:0,y1:0,x2:0,y2:1,"
        f"stop:0 {g[0]},stop:1 {g[1]});color:{t('btn_text')};"
        f"border:1px solid {t('border_top')};border-top:1px solid #FFFFFF;"
        f"border-bottom:1px solid {t('border_top')};"
        f"border-radius:{dps(t('radius_btn'))};padding:{dps(4)} {dps(12)};font-size:{fs(12)};font-weight:500;}}"
        f"QPushButton:hover{{background:qlineargradient(x1:0,y1:0,x2:0,y2:1,"
        f"stop:0 {gh[0]},stop:1 {gh[1]});border-top-color:{t('accent')};color:{t('btn_text_hover')};}}"
        f"QPushButton:pressed{{background:{g[1]};border-top-color:{t('border_top')};}}"
        f"QPushButton:disabled{{color:{t('faint')};border-color:{t('border_soft')};}}"
    )


def _ivory_btn_accent() -> str:
    t = _t
    a, ah = t("accent_grad"), t("accent_grad_hover")
    return (
        f"QPushButton{{background:qlineargradient(x1:0,y1:0,x2:0,y2:1,"
        f"stop:0 {a[0]},stop:1 {a[1]});color:{t('on_accent')};"
        f"border:1px solid {t('accent_border')};border-top:1px solid #FFFFFF;"
        f"border-bottom:1px solid {t('border_top')};"
        f"border-radius:{dps(t('radius_btn'))};padding:{dps(5)} {dps(14)};font-size:{fs(12)};font-weight:600;}}"
        f"QPushButton:hover{{background:qlineargradient(x1:0,y1:0,x2:0,y2:1,"
        f"stop:0 {ah[0]},stop:1 {ah[1]});border-top-color:{t('accent_hover')};}}"
        f"QPushButton:disabled{{background:{t('overlay')};color:{t('faint')};}}"
    )


def _ivory_input() -> str:
    t = _t
    return (
        f"QLineEdit{{background:qlineargradient(x1:0,y1:0,x2:0,y2:1,"
        f"stop:0 {t('panel')},stop:0.6 {t('overlay')},stop:1 {t('panel')});color:{t('text')};"
        f"border:1px solid {t('border')};border-top:1px solid {t('border_top')};"
        f"border-bottom:1px solid #FFFFFF;"
        f"border-radius:{dps(t('radius_input'))};padding:{dps(5)} {dps(10)};font-size:{fs(12)};}}"
        f"QLineEdit:focus{{border-color:{t('accent')};border-bottom-color:{t('accent_hover')};}}"
        f"QLineEdit:disabled{{color:{t('faint')};}}"
    )


def _ivory_combo() -> str:
    t = _t
    body = (f"background:qlineargradient(x1:0,y1:0,x2:0,y2:1,"
            f"stop:0 {t('panel')},stop:0.6 {t('overlay')},stop:1 {t('panel')});color:{t('text')};"
            f"border:1px solid {t('border')};border-top:1px solid {t('border_top')};border-bottom:1px solid #FFFFFF;"
            f"border-radius:{dps(t('radius_input'))};padding:{dps(4)} {dps(10)};font-size:{fs(12)};")
    return (f"QComboBox{{{body}}}"
            f"QComboBox:hover{{border-top-color:{t('accent')};}}"
            f"QComboBox::drop-down{{border:none;width:{dps(24)};}}"
            f"QComboBox QAbstractItemView{{background:{t('panel')};color:{t('text')};"
            f"border:1px solid {t('border')};border-radius:{dps(5)};"
            f"selection-background-color:{t('sel_bg')};selection-color:{t('sel_fg')};outline:none;}}"
            )


def _ivory_spinbox() -> str:
    t = _t
    body = (f"background:qlineargradient(x1:0,y1:0,x2:0,y2:1,"
            f"stop:0 {t('panel')},stop:0.6 {t('overlay')},stop:1 {t('panel')});color:{t('text')};"
            f"border:1px solid {t('border')};border-top:1px solid {t('border_top')};border-bottom:1px solid #FFFFFF;"
            f"border-radius:{dps(t('radius_input'))};padding:{dps(4)} {dps(8)};font-size:{fs(12)};")
    return (f"QSpinBox,QDoubleSpinBox{{{body}}}"
            f"QSpinBox:focus,QDoubleSpinBox:focus{{border-color:{t('accent')};border-bottom-color:{t('accent_hover')};}}"
            )


def qss_table() -> str:
    return (f"QTableWidget{{background:{_t('bg')};color:{_t('text')};border:1px solid {_t('border')};"
            f"border-radius:{dps(7)};gridline-color:{_t('border_soft')};font-size:{fs(11)};}}"
            f"QTableWidget::item{{padding:{dps(4)} {dps(9)};border-bottom:1px solid {_t('border_soft')};}}"
            f"QTableWidget::item:selected{{background:{_t('sel_bg')};color:{_t('sel_fg')};}}"
            f"QTableWidget::item:hover:!selected{{background:{_t('raised')};}}"
            f"QHeaderView::section{{background:{_t('panel')};color:{_t('sub')};border:none;"
            f"border-bottom:1px solid {_t('border')};padding:{dps(5)} {dps(9)};font-weight:600;"
            f"font-size:{fs(10)};letter-spacing:0.5px;}}")


def qss_list() -> str:
    return (f"QListWidget{{background:{_t('bg')};color:{_t('text')};border:1px solid {_t('border')};"
            f"border-radius:{dps(6)};font-size:{fs(11)};outline:none;padding:{dps(3)};}}"
            f"QListWidget::item{{padding:{dps(4)} {dps(9)};border-radius:{dps(4)};}}"
            f"QListWidget::item:selected{{background:{_t('sel_bg')};color:{_t('sel_fg')};}}"
            f"QListWidget::item:hover:!selected{{background:{_t('raised')};}}")


def style_h1() -> str:
    return f"color:{_t('text')};font-size:{fs(15)};font-weight:700;background:transparent;"


def style_h2() -> str:
    return f"color:{_t('text')};font-size:{fs(13)};font-weight:600;background:transparent;"


def style_label() -> str:
    return f"color:{_t('sub')};font-size:{fs(11)};background:transparent;"


def style_caption() -> str:
    return f"color:{_t('faint')};font-size:{fs(10)};background:transparent;"


def style_num(color: str = None, size: int = 15) -> str:
    return (f"color:{color or _t('text')};font-size:{fs(size)};font-weight:700;"
            f"background:transparent;font-family:'Consolas','Segoe UI','Microsoft YaHei';")


# ──────────────────────────────────────────────────────────────
#  Global stylesheet (built from the active theme)
# ──────────────────────────────────────────────────────────────

def _build_template(t: dict) -> str:
    dark = t["dark"]
    if not dark:
        return _ivory_template(t)
    if _current_key == "obsidian":
        return _obsidian_template(t)
    return _graphite_template(t)


def build_style(base_fs: int = 13, key: str = None) -> str:
    """Build the global QSS stylesheet for the given (or active) theme."""
    global FONT_BASE
    FONT_BASE = base_fs
    if key:
        set_theme(key)
    t = THEMES[_current_key]
    s = _build_template(t)
    scale = base_fs / 13
    for sz in range(8, 37):
        s = s.replace(f"$fs{sz}", f"{round(sz * scale)}px")
    for dm in range(2, 61):
        s = s.replace(f"$dp{dm}", f"{round(dm * scale)}px")
    globals()["STYLE"] = s
    return s


def _shared_parts(t: dict) -> str:
    return f"""QMainWindow, QWidget {{
    background-color: {t['bg']};
    color: {t['text']};
    font-family: "Segoe UI", "Microsoft YaHei";
    font-size: $fs13;
    selection-background-color: {t['sel_bg']};
    selection-color: {t['sel_fg']};
}}
QFrame#card {{
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 {t['card_stops'][0]}, stop:0.5 {t['card_stops'][1]}, stop:1 {t['card_stops'][2]});
    border: 1px solid {t['card_border']};
    border-top: 1px solid {t['card_border_top']};
    border-radius: $dp{t['radius_card']};
}}
QFrame#card:hover {{
    border-top-color: {t['card_hover_border']}; border-color: {t['raised']};
}}
QListWidget {{ background: {t['bg']}; color: {t['text']}; border: 1px solid {t['border']};
    border-radius: $dp6; outline:none; padding: $dp3; }}
QListWidget::item {{ padding: $dp5 $dp10; border-radius: $dp4; }}
QListWidget::item:selected {{ background: {t['sel_bg']}; color: {t['sel_fg']}; }}
QListWidget::item:hover:!selected {{ background: {t['raised']}; }}
QTableWidget {{ background: {t['bg']}; color: {t['text']}; border: 1px solid {t['border']};
    border-radius: $dp7; gridline-color: {t['border_soft']}; }}
QTableWidget::item {{ padding: $dp4 $dp9; border-bottom: 1px solid {t['border_soft']}; }}
QTableWidget::item:selected {{ background: {t['sel_bg']}; color: {t['sel_fg']}; }}
QTableWidget::item:hover:!selected {{ background: {t['raised']}; }}
QHeaderView::section {{ background: {t['panel']}; color: {t['sub']}; border:none;
    border-bottom: 1px solid {t['border']}; padding: $dp5 $dp9; font-weight:600; font-size: $fs10; letter-spacing: 0.5px;}}
QHeaderView::section:horizontal {{ border-right: 1px solid {t['border_soft']}; }}
QTableCornerButton::section {{ background: {t['panel']}; border:none; }}
QLineEdit {{ background: {t['panel']}; color: {t['text']}; border: 1px solid {t['border']};
    border-top: 1px solid {t['border_top']}; border-radius: $dp6; padding: $dp5 $dp10; font-size: $fs12;
    selection-background-color: {t['sel_bg']}; }}
QLineEdit:focus {{ border-color: {t['accent']}; }}
QLineEdit:disabled {{ color: {t['faint']}; }}
QTextEdit, QPlainTextEdit {{ background: {t['panel']}; color: {t['text']}; border: 1px solid {t['border']};
    border-top: 1px solid {t['border_top']}; border-radius: $dp6; padding: $dp6; font-size: $fs12;
    selection-background-color: {t['sel_bg']}; }}
QTextEdit:focus, QPlainTextEdit:focus {{ border-color: {t['accent']}; }}
QComboBox {{ background: {t['panel']}; color: {t['text']}; border: 1px solid {t['border']};
    border-top: 1px solid {t['border_top']}; border-radius: $dp6; padding: $dp4 $dp10; font-size: $fs12; }}
QComboBox:hover {{ border-top-color: {t['accent']}; }}
QComboBox::drop-down {{ border:none; width: $dp24; }}
QComboBox QAbstractItemView {{ background: {t['panel']}; color: {t['text']}; border: 1px solid {t['border']};
    border-radius: $dp5; selection-background-color: {t['sel_bg']}; selection-color: {t['sel_fg']}; outline:none;}}
QSpinBox, QDoubleSpinBox {{ background: {t['panel']}; color: {t['text']}; border: 1px solid {t['border']};
    border-radius: $dp6; padding: $dp4 $dp8; font-size: $fs12; }}
QSpinBox:focus, QDoubleSpinBox:focus {{ border-color: {t['accent']}; }}
QCheckBox {{ color: {t['text']}; font-size: $fs12; spacing: $dp6; }}
QCheckBox::indicator {{ width: $dp14; height: $dp14; border: 1px solid {t['border_top']}; border-radius: $dp4; background: {t['panel']}; }}
QCheckBox::indicator:checked {{ background: {t['accent']}; border-color: {t['accent']}; }}
QCheckBox::indicator:hover {{ border-color: {t['accent']}; }}
QRadioButton {{ color: {t['text']}; font-size: $fs12; spacing: $dp6; }}
QProgressBar {{ background: {t['panel']}; border: 1px solid {t['border']}; border-radius: $dp5; text-align:center; color:{t['sub']}; font-size: $fs10; }}
QProgressBar::chunk {{ background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 {t['progress_grad'][0]}, stop:1 {t['progress_grad'][1]}); border-radius: $dp4; }}
QTreeWidget {{ background: {t['bg']}; color: {t['text']}; border: 1px solid {t['border']}; border-radius: $dp6; outline:none; }}
QTreeWidget::item {{ padding: $dp4 $dp6; border-radius: $dp3; }}
QTreeWidget::item:selected {{ background: {t['sel_bg']}; color: {t['sel_fg']}; }}
QTreeWidget::item:hover:!selected {{ background: {t['raised']}; }}
QTabWidget::pane {{ border: 1px solid {t['border']}; border-radius: $dp6; background: {t['bg']}; }}
QTabBar::tab {{ background: transparent; color: {t['sub']}; padding: $dp6 $dp14; border-bottom: 2px solid transparent; font-size: $fs11; letter-spacing: 0.5px; font-weight:500; }}
QTabBar::tab:selected {{ color: {t['sel_fg']}; border-bottom-color: {t['accent']}; }}
QTabBar::tab:hover:!selected {{ color: {t['text']}; }}
QScrollBar:vertical {{ background: transparent; width: $dp9; margin: $dp2; }}
QScrollBar::handle:vertical {{ background: {t['scroll_handle']}; min-height: $dp30; border-radius: $dp4; }}
QScrollBar::handle:vertical:hover {{ background: {t['scroll_hover']}; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0px; }}
QScrollBar:horizontal {{ background: transparent; height: $dp9; margin: $dp2; }}
QScrollBar::handle:horizontal {{ background: {t['scroll_handle']}; min-width: $dp30; border-radius: $dp4; }}
QScrollBar::handle:horizontal:hover {{ background: {t['scroll_hover']}; }}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0px; }}
QToolTip {{ background: {t['panel']}; color: {t['text']}; border: 1px solid {t['border']}; border-radius: $dp4; padding: $dp4 $dp8; }}
QMenu {{ background: {t['panel']}; color: {t['text']}; border: 1px solid {t['border']}; border-radius: $dp5; }}
QMenu::item {{ padding: $dp4 $dp12; }}
QMenu::item:selected {{ background: {t['sel_bg']}; color: {t['sel_fg']}; }}
QSplitter::handle {{ background: {t['border_soft']}; }}
QStatusBar {{ background: {t['panel']}; color: {t['sub']}; border-top: 1px solid {t['border_soft']}; }}
/*** push buttons ***/
QPushButton {{ background: qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 {t['btn_grad'][0]}, stop:1 {t['btn_grad'][1]}); color: {t['btn_text']};
    border: 1px solid {t['border']}; border-top: 1px solid {t['btn_border_top']}; border-radius: $dp{t['radius_btn']}; padding: $dp4 $dp12; font-size: $fs12; font-weight:500; }}
QPushButton:hover {{ background: qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 {t['btn_grad_hover'][0]}, stop:1 {t['btn_grad_hover'][1]}); border-top-color: {t['accent']}; color: {t['btn_text_hover']}; }}
QPushButton:pressed {{ background: {t['bg']}; border-top-color: {t['card_border']}; }}
QPushButton:disabled {{ color: {t['faint']}; border-color: {t['border_soft']}; }}
QPushButton:checked {{ background: qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 {t['accent_grad'][0]}, stop:1 {t['accent_grad'][1]}); color: {t['on_accent']}; border-color: {t['accent_border']}; font-weight:600; }}
QPushButton#refreshBtn {{ background: qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 {t['accent_grad'][0]}, stop:1 {t['accent_grad'][1]}); color: {t['on_accent']}; border: 1px solid {t['accent_border']}; font-weight:600; }}
QPushButton#navBtn {{ background: transparent; color: {t['sub']}; border:none; border-radius: $dp8; font-weight:500; }}
QPushButton#navBtn:hover {{ background: {t['raised']}; color: {t['text']}; }}
QPushButton#navBtn:checked {{ background: {t['raised']}; color: {t['sel_fg']}; border-left: 2px solid {t['accent']}; font-weight:600; }}
QPushButton#indBtn {{ background: {t['panel']}; color: {t['sub']}; border: 1px solid {t['border']}; border-top: 1px solid {t['border_top']}; border-radius: $dp4; padding: $dp3 $dp12; font-size: $fs11; }}
QPushButton#indBtn:hover {{ color: {t['text']}; border-top-color: {t['accent']}; }}
QPushButton#indBtn:checked {{ background: qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 {t['accent_grad'][0]}, stop:1 {t['accent_grad'][1]}); color: {t['on_accent']}; border-color: {t['accent_border']}; font-weight:600; }}
"""


def _graphite_template(t: dict) -> str:
    extra = f"""
/* graphite: cold-steel plate controls + recessed inputs + header rail */
QPushButton {{
    background: qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 {t['btn_grad'][0]}, stop:1 {t['btn_grad'][1]});
    color: {t['btn_text']}; border: 1px solid {t['border']}; border-top: 1px solid {t['border_top']};
    border-bottom: 1px solid {t['border_top']}; border-radius: $dp{t['radius_btn']};
    padding: $dp4 $dp12; font-size: $fs12; font-weight: 500;
}}
QPushButton:hover {{ background: qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 {t['btn_grad_hover'][0]}, stop:1 {t['btn_grad_hover'][1]}); border-top-color: {t['accent']}; color: {t['btn_text_hover']}; }}
QPushButton:pressed {{ background: {t['bg']}; border-top-color: {t['border']}; }}
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox {{
    background: qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 {t['raised']}, stop:0.6 {t['panel']}, stop:1 {t['raised']});
    color: {t['text']}; border: 1px solid {t['border_soft']}; border-top: 1px solid {t['border']};
    border-bottom: 1px solid {t['border_top']}; border-radius: $dp6; padding: $dp5 $dp10; font-size: $fs12;
}}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus {{ border-color: {t['accent']}; }}
QHeaderView::section {{
    background: qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 {t['raised']}, stop:0.6 {t['panel']}, stop:1 {t['raised']});
    color: {t['sub']}; border: none; border-bottom: 1px solid {t['border']};
    border-right: 1px solid {t['border_soft']}; padding: $dp5 $dp9; font-weight:600; font-size:$fs10; letter-spacing:0.5px;
}}
QHeaderView::section:hover {{ color: {t['text']}; border-bottom-color: {t['accent']}; }}
QTableCornerButton::section {{ background: {t['panel']}; border:none; border-bottom:1px solid {t['border']}; }}
QTableWidget::item:selected, QListWidget::item:selected, QTreeWidget::item:selected {{
    background: qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 {t['sel_bg']}, stop:1 rgba(0,0,0,0.18));
    color: {t['sel_fg']};
}}
"""
    return _shared_parts(t) + extra


def _obsidian_template(t: dict) -> str:
    # machined inner-well depth: sunken panels + engraved labels via multiple insets
    extra = f"""
/* obsidian: machined inner well for cards */
QFrame#card {{
    border: 1px solid #000000;
    border-top: 1px solid {t['card_border_top']};
    background: qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 {t['card_stops'][0]}, stop:0.5 {t['card_stops'][1]}, stop:1 {t['card_stops'][2]});
    border-radius: $dp{t['radius_card']};
}}
QFrame#card:hover {{ border-top-color: {t['card_hover_border']}; }}
QListWidget, QTableWidget, QTreeWidget, QPlainTextEdit, QTextEdit {{
    border: 1px solid #000000; border-top: 1px solid {t['card_border_top']}; border-radius: $dp6;
}}
/* obsidian: machined recessed controls — metal edge + sunk well */
QPushButton {{
    background: qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 {t['btn_grad'][0]}, stop:0.58 {t['btn_grad'][1]}, stop:1 {t['btn_grad'][0]});
    color: {t['btn_text']}; border: 1px solid #050607; border-top: 1px solid #000;
    border-bottom: 1px solid {t['btn_border_top']}; border-left: 1px solid #050607; border-right: 1px solid #050607;
    border-radius: $dp{t['radius_btn']}; padding: $dp4 $dp12; font-size: $fs12; font-weight: 500;
}}
QPushButton:hover {{
    background: qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 {t['btn_grad_hover'][0]}, stop:1 {t['btn_grad_hover'][1]});
    border-top-color: {t['accent']}; border-bottom-color: {t['card_hover_border']}; color: {t['btn_text_hover']};
}}
QPushButton:pressed {{ background: {t['bg']}; border-top-color: {t['btn_border_top']}; border-bottom-color: #000; }}
QPushButton:checked {{ background: qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 {t['accent_grad'][0]}, stop:1 {t['accent_grad'][1]}); color: {t['on_accent']}; border-color: {t['accent_border']}; font-weight:600; }}
QPushButton:disabled {{ color: {t['faint']}; border-color: {t['border_soft']}; }}
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox {{
    background: qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 {t['btn_grad'][0]}, stop:0.6 {t['btn_grad'][1]}, stop:1 {t['btn_grad'][0]});
    color: {t['text']}; border: 1px solid #050607; border-top: 1px solid #000;
    border-bottom: 1px solid {t['btn_border_top']}; border-left: 1px solid #050607; border-right: 1px solid #050607;
    border-radius: $dp6; padding: $dp5 $dp10; font-size: $fs12;
}}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus {{ border-color: {t['accent']}; border-bottom-color: {t['accent_hover']}; }}
QPushButton#refreshBtn {{ background: qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 {t['accent_grad'][0]}, stop:0.5 {t['accent_grad'][0]}, stop:1 {t['accent_grad'][1]}); color: {t['on_accent']}; border: 1px solid #000; border-top: 1px solid {t['accent_hover']}; border-bottom: 1px solid #000; font-weight:600; }}
QPushButton#indBtn {{ background: qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 {t['panel']}, stop:0.6 {t['bg']}, stop:1 {t['panel']}); color: {t['sub']}; border: 1px solid #050607; border-top: 1px solid #000; border-bottom: 1px solid {t['btn_border_top']}; border-radius: $dp4; padding: $dp3 $dp12; font-size: $fs11; }}
QPushButton#indBtn:hover {{ color: {t['text']}; border-top-color: {t['accent']}; }}
QPushButton#indBtn:checked {{ background: qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 {t['accent_grad'][0]}, stop:1 {t['accent_grad'][1]}); color: {t['on_accent']}; border-color: {t['accent_border']}; font-weight:600; }}
/* obsidian: micro-recessed table header rail + selected-row grooves */
QHeaderView::section {{
    background: qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 {t['panel']}, stop:0.62 {t['bg']}, stop:1 {t['panel']});
    color: {t['sub']}; border: none;
    border-bottom: 1px solid #000;
    border-right: 1px solid #050607;
    padding: $dp5 $dp9; font-weight: 600; font-size: $fs10; letter-spacing: 0.5px;
}}
QHeaderView::section:hover {{ color: {t['text']}; border-bottom-color: {t['accent']}; }}
QTableCornerButton::section {{ background: qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 {t['panel']}, stop:1 {t['bg']}); border: none; border-bottom: 1px solid #000; }}
QTableWidget::item:selected, QListWidget::item:selected, QTreeWidget::item:selected {{
    background: qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 {t['sel_bg']}, stop:1 rgba(0,0,0,0.35));
    color: {t['sel_fg']};
}}
"""
    return _shared_parts(t) + extra


def _ivory_template(t: dict) -> str:
    extra = f"""
/* ivory: paper deboss — ink-chip buttons, debossed inputs, embossed header rail */
QPushButton {{
    background: qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 {t['btn_grad'][0]}, stop:1 {t['btn_grad'][1]});
    color: {t['btn_text']}; border: 1px solid {t['border_top']}; border-top: 1px solid #FFFFFF;
    border-bottom: 1px solid {t['border_top']}; border-radius: $dp{t['radius_btn']};
    padding: $dp4 $dp12; font-size: $fs12; font-weight: 500;
}}
QPushButton:hover {{ background: qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 {t['btn_grad_hover'][0]}, stop:1 {t['btn_grad_hover'][1]}); border-top-color: {t['accent']}; color: {t['btn_text_hover']}; }}
QPushButton:pressed {{ background: {t['btn_grad'][1]}; border-top-color: {t['border_top']}; }}
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox {{
    background: qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 {t['panel']}, stop:0.6 {t['overlay']}, stop:1 {t['panel']});
    color: {t['text']}; border: 1px solid {t['border']}; border-top: 1px solid {t['border_top']};
    border-bottom: 1px solid #FFFFFF; border-radius: $dp6; padding: $dp5 $dp10; font-size: $fs12;
}}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus {{ border-color: {t['accent']}; border-bottom-color: {t['accent_hover']}; }}
QHeaderView::section {{
    background: qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 #FFFFFF, stop:0.6 {t['raised']}, stop:1 #FFFFFF);
    color: {t['sub']}; border: none; border-bottom: 1px solid {t['border_top']};
    border-right: 1px solid {t['border_soft']}; padding: $dp5 $dp9; font-weight:600; font-size:$fs10; letter-spacing:0.5px;
}}
QHeaderView::section:hover {{ color: {t['text']}; border-bottom-color: {t['accent']}; }}
QTableCornerButton::section {{ background: {t['panel']}; border:none; border-bottom:1px solid {t['border_top']}; }}
QTableWidget::item:selected, QListWidget::item:selected, QTreeWidget::item:selected {{
    background: qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 {t['sel_bg']}, stop:1 rgba(0,0,0,0.05));
    color: {t['sel_fg']};
}}
"""
    return _shared_parts(t) + extra


# Backwards-compat: pre-built default global stylesheet (kept in sync by build_style)
STYLE = build_style(FONT_BASE)
