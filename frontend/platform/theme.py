# -*- coding: utf-8 -*-
"""Design system for stock-classroom — palette, scaling helpers, QSS fragments.

All panels should import colors/fragments from here instead of redefining
their own constants, so the whole app stays consistent and the font-size
setting applies everywhere.
"""

FONT_BASE = 13

# ──────────────────────────────────────────────────────────────
#  Palette
# ──────────────────────────────────────────────────────────────

C_BG = "#0D1117"        # app background
C_PANEL = "#161B22"     # cards / panels
C_RAISED = "#1C2128"    # hover / raised surface
C_OVERLAY = "#21262D"   # active surface
C_BORDER = "#2A3139"    # default border
C_BORDER_SOFT = "#21262D"
C_TEXT = "#E6EDF3"
C_SUBTEXT = "#8B949E"
C_FAINT = "#6E7681"
C_ACCENT = "#D4A574"    # brand gold
C_ACCENT_HOVER = "#E0B888"
C_ACCENT_DIM = "rgba(212,165,116,0.12)"
C_ON_ACCENT = "#1A1410"
C_UP = "#E5484D"        # A股红涨
C_DOWN = "#3FB950"      # A股绿跌
C_INFO = "#58A6FF"
C_WARN = "#D29922"

# Backwards-compatible map (kline widget etc.)
COLORS = {
    "bg": C_BG,
    "panel": C_PANEL,
    "border": C_BORDER_SOFT,
    "text": C_TEXT,
    "subtext": C_SUBTEXT,
    "accent": C_ACCENT,
    "rise": C_UP,
    "fall": C_DOWN,
    "hover": C_RAISED,
    "ma5": "#F0A56A",
    "ma10": "#5DADE2",
    "ma20": "#AF7AC5",
    "ma60": "#F7DC6F",
    "dif": "#FF6B6B",
}


# ──────────────────────────────────────────────────────────────
#  Scaling helpers
# ──────────────────────────────────────────────────────────────

def fs(size: int) -> str:
    """Return scaled CSS font-size string, e.g. fs(13) -> '21px' at base 21."""
    return f"{round(size * FONT_BASE / 13)}px"


def fsi(size: int) -> int:
    """Return scaled font-size as integer (for QFont use)."""
    return round(size * FONT_BASE / 13)


def dp(size: int) -> int:
    """Scale widget dimension by font ratio."""
    return round(size * FONT_BASE / 13)


def dps(size: int) -> str:
    """Return scaled dimension as CSS string, e.g. dps(30) -> '48px'."""
    return f"{dp(size)}px"


# ──────────────────────────────────────────────────────────────
#  Reusable QSS fragments (built with the current scale)
# ──────────────────────────────────────────────────────────────

def qss_card(radius: int = 8) -> str:
    return (f"QFrame#card{{background:{C_PANEL};border:1px solid {C_BORDER_SOFT};"
            f"border-radius:{dps(radius)};}}"
            f"QFrame#card:hover{{border-color:{C_BORDER};}}")


def qss_btn() -> str:
    return (f"QPushButton{{background:{C_RAISED};color:{C_TEXT};border:1px solid {C_BORDER};"
            f"border-radius:{dps(6)};padding:{dps(4)} {dps(12)};font-size:{fs(12)};}}"
            f"QPushButton:hover{{background:{C_OVERLAY};border-color:#484F58;}}"
            f"QPushButton:pressed{{background:{C_PANEL};}}"
            f"QPushButton:disabled{{color:{C_FAINT};border-color:{C_BORDER_SOFT};}}")


def qss_btn_accent() -> str:
    return (f"QPushButton{{background:{C_ACCENT};color:{C_ON_ACCENT};border:none;"
            f"border-radius:{dps(6)};padding:{dps(5)} {dps(14)};font-size:{fs(12)};font-weight:700;}}"
            f"QPushButton:hover{{background:{C_ACCENT_HOVER};}}"
            f"QPushButton:pressed{{background:#C89666;}}"
            f"QPushButton:disabled{{background:{C_OVERLAY};color:{C_FAINT};}}")


def qss_btn_accent_outline() -> str:
    return (f"QPushButton{{background:{C_ACCENT_DIM};color:{C_ACCENT};border:1px solid {C_ACCENT};"
            f"border-radius:{dps(6)};padding:{dps(4)} {dps(12)};font-size:{fs(12)};font-weight:600;}}"
            f"QPushButton:hover{{background:rgba(212,165,116,0.20);}}"
            f"QPushButton:disabled{{color:{C_FAINT};border-color:{C_BORDER_SOFT};background:transparent;}}")


def qss_input() -> str:
    return (f"QLineEdit{{background:{C_PANEL};color:{C_TEXT};border:1px solid {C_BORDER};"
            f"border-radius:{dps(6)};padding:{dps(5)} {dps(10)};font-size:{fs(12)};}}"
            f"QLineEdit:focus{{border-color:{C_ACCENT};}}")


def qss_combo() -> str:
    return (f"QComboBox{{background:{C_PANEL};color:{C_TEXT};border:1px solid {C_BORDER};"
            f"border-radius:{dps(6)};padding:{dps(4)} {dps(10)};font-size:{fs(12)};}}"
            f"QComboBox:hover{{border-color:#484F58;}}"
            f"QComboBox::drop-down{{border:none;width:{dps(24)};}}"
            f"QComboBox QAbstractItemView{{background:{C_PANEL};color:{C_TEXT};"
            f"border:1px solid {C_BORDER};selection-background-color:{C_ACCENT_DIM};"
            f"selection-color:{C_ACCENT};outline:none;}}")


def qss_spinbox() -> str:
    return (f"QSpinBox,QDoubleSpinBox{{background:{C_PANEL};color:{C_TEXT};"
            f"border:1px solid {C_BORDER};border-radius:{dps(6)};"
            f"padding:{dps(4)} {dps(8)};font-size:{fs(12)};}}"
            f"QSpinBox:focus,QDoubleSpinBox:focus{{border-color:{C_ACCENT};}}")


def qss_table() -> str:
    return (f"QTableWidget{{background:{C_BG};color:{C_TEXT};border:1px solid {C_BORDER_SOFT};"
            f"border-radius:{dps(6)};gridline-color:{C_BORDER_SOFT};font-size:{fs(12)};}}"
            f"QTableWidget::item{{padding:{dps(3)} {dps(8)};border-bottom:1px solid #1A1F28;}}"
            f"QTableWidget::item:selected{{background:{C_ACCENT_DIM};color:{C_ACCENT};}}"
            f"QTableWidget::item:hover:!selected{{background:{C_RAISED};}}"
            f"QHeaderView::section{{background:{C_PANEL};color:{C_SUBTEXT};border:none;"
            f"border-bottom:1px solid {C_BORDER};padding:{dps(5)} {dps(8)};"
            f"font-weight:600;font-size:{fs(11)};}}")


def qss_list() -> str:
    return (f"QListWidget{{background:{C_PANEL};color:{C_TEXT};border:1px solid {C_BORDER};"
            f"border-radius:{dps(6)};font-size:{fs(12)};outline:none;}}"
            f"QListWidget::item{{padding:{dps(4)} {dps(8)};}}"
            f"QListWidget::item:selected{{background:{C_ACCENT_DIM};color:{C_ACCENT};}}"
            f"QListWidget::item:hover:!selected{{background:{C_RAISED};}}")


def style_h1() -> str:
    return f"color:{C_TEXT};font-size:{fs(15)};font-weight:700;background:transparent;"


def style_h2() -> str:
    return f"color:{C_TEXT};font-size:{fs(13)};font-weight:600;background:transparent;"


def style_label() -> str:
    return f"color:{C_SUBTEXT};font-size:{fs(11)};background:transparent;"


def style_caption() -> str:
    return f"color:{C_FAINT};font-size:{fs(10)};background:transparent;"


def style_num(color: str = None, size: int = 15) -> str:
    return (f"color:{color or C_TEXT};font-size:{fs(size)};font-weight:700;"
            f"background:transparent;font-family:'Consolas','Segoe UI','Microsoft YaHei';")


# ──────────────────────────────────────────────────────────────
#  Global stylesheet
# ──────────────────────────────────────────────────────────────

def build_style(base_fs: int = 13) -> str:
    """Build the global QSS stylesheet with given base font-size."""
    global FONT_BASE
    FONT_BASE = base_fs

    scale = base_fs / 13
    s = _TEMPLATE
    for sz in range(8, 37):
        s = s.replace(f"$fs{sz}", f"{round(sz * scale)}px")
    for dm in range(2, 61):
        s = s.replace(f"$dp{dm}", f"{round(dm * scale)}px")
    return s


_TEMPLATE = """
/* ============================================================
   stock-classroom — Premium Dark Theme
   ============================================================ */
QMainWindow, QWidget {
    background-color: #0D1117;
    color: #E6EDF3;
    font-family: "Segoe UI", "Microsoft YaHei";
    font-size: $fs13;
}
/* ── Cards ── */
QFrame#card {
    background: #161B22;
    border: 1px solid #21262D;
    border-radius: $dp8;
}
QFrame#card:hover {
    border-color: #2A3139;
}

/* ── Lists ── */
QListWidget {
    background: #0D1117;
    color: #E6EDF3;
    border: 1px solid #21262D;
    border-radius: $dp6;
    outline: none;
}
QListWidget::item {
    padding: $dp5 $dp10;
    border-radius: $dp4;
}
QListWidget::item:selected {
    background: rgba(212, 165, 116, 0.12);
    color: #D4A574;
}
QListWidget::item:hover:!selected {
    background: #1C2128;
}

/* ── Tables ── */
QTableWidget {
    background: #0D1117;
    color: #E6EDF3;
    border: 1px solid #21262D;
    border-radius: $dp6;
    gridline-color: #1A1F28;
}
QTableWidget::item {
    padding: $dp4 $dp8;
    border-bottom: 1px solid #1A1F28;
}
QTableWidget::item:selected {
    background: rgba(212, 165, 116, 0.12);
    color: #D4A574;
}
QTableWidget::item:hover:!selected {
    background: #1C2128;
}
QHeaderView::section {
    background: #161B22;
    color: #8B949E;
    border: none;
    border-bottom: 1px solid #2A3139;
    padding: $dp5 $dp8;
    font-weight: 600;
    font-size: $fs11;
}
QHeaderView::section:horizontal {
    border-right: 1px solid #1A1F28;
}

/* ── Line Edit ── */
QLineEdit {
    background: #161B22;
    color: #E6EDF3;
    border: 1px solid #2A3139;
    border-radius: $dp6;
    padding: $dp5 $dp10;
    font-size: $fs12;
}
QLineEdit:focus {
    border-color: #D4A574;
}
QLineEdit:disabled {
    color: #6E7681;
}

/* ── Text Edit ── */
QTextEdit, QPlainTextEdit {
    background: #161B22;
    color: #E6EDF3;
    border: 1px solid #2A3139;
    border-radius: $dp6;
    padding: $dp6;
    font-size: $fs12;
}
QTextEdit:focus, QPlainTextEdit:focus {
    border-color: #D4A574;
}

/* ── Push Button ── */
QPushButton {
    background: #1C2128;
    color: #C9D1D9;
    border: 1px solid #2A3139;
    border-radius: $dp6;
    padding: $dp4 $dp12;
    font-size: $fs12;
}
QPushButton:hover {
    background: #21262D;
    border-color: #484F58;
}
QPushButton:pressed {
    background: #161B22;
}
QPushButton:disabled {
    color: #6E7681;
}
QPushButton:checked {
    background: rgba(212, 165, 116, 0.10);
    color: #D4A574;
    border-color: #D4A574;
}

/* ── Refresh Button ── */
QPushButton#refreshBtn {
    background: rgba(212, 165, 116, 0.10);
    color: #D4A574;
    border: 1px solid #D4A574;
}
QPushButton#refreshBtn:hover {
    background: rgba(212, 165, 116, 0.18);
}

/* ── Nav Buttons (icon rail) ── */
QPushButton#navBtn {
    background: transparent;
    color: #8B949E;
    border: none;
    border-radius: $dp8;
    font-weight: 500;
}
QPushButton#navBtn:hover {
    background: #1C2128;
    color: #C9D1D9;
}
QPushButton#navBtn:checked {
    background: rgba(212, 165, 116, 0.12);
    color: #D4A574;
    font-weight: 600;
}

/* ── Indicator Buttons (segmented control) ── */
QPushButton#indBtn {
    background: #161B22;
    color: #8B949E;
    border: 1px solid #2A3139;
    border-radius: $dp4;
    padding: $dp3 $dp12;
    font-size: $fs11;
}
QPushButton#indBtn:hover {
    color: #C9D1D9;
    border-color: #484F58;
}
QPushButton#indBtn:checked {
    background: rgba(212, 165, 116, 0.12);
    color: #D4A574;
    border-color: #D4A574;
}

/* ── CheckBox ── */
QCheckBox {
    color: #C9D1D9;
    font-size: $fs12;
    spacing: $dp6;
}
QCheckBox::indicator {
    width: $dp14;
    height: $dp14;
    border: 1px solid #484F58;
    border-radius: $dp4;
    background: #161B22;
}
QCheckBox::indicator:checked {
    background: #D4A574;
    border-color: #D4A574;
}
QCheckBox::indicator:hover {
    border-color: #D4A574;
}

/* ── Radio ── */
QRadioButton {
    color: #C9D1D9;
    font-size: $fs12;
    spacing: $dp6;
}

/* ── ComboBox ── */
QComboBox {
    background: #161B22;
    color: #E6EDF3;
    border: 1px solid #2A3139;
    border-radius: $dp6;
    padding: $dp4 $dp10;
    font-size: $fs12;
}
QComboBox:hover { border-color: #484F58; }
QComboBox::drop-down { border: none; width: $dp24; }
QComboBox QAbstractItemView {
    background: #161B22;
    color: #E6EDF3;
    border: 1px solid #2A3139;
    selection-background-color: rgba(212, 165, 116, 0.12);
    selection-color: #D4A574;
    outline: none;
}

/* ── SpinBox ── */
QSpinBox, QDoubleSpinBox {
    background: #161B22;
    color: #E6EDF3;
    border: 1px solid #2A3139;
    border-radius: $dp6;
    padding: $dp4 $dp8;
    font-size: $fs12;
}
QSpinBox:focus, QDoubleSpinBox:focus { border-color: #D4A574; }

/* ── ProgressBar ── */
QProgressBar {
    background: #161B22;
    border: 1px solid #21262D;
    border-radius: $dp5;
    text-align: center;
    color: #8B949E;
    font-size: $fs10;
}
QProgressBar::chunk {
    background: #D4A574;
    border-radius: $dp4;
}

/* ── Tree Widget ── */
QTreeWidget {
    background: #0D1117;
    color: #C9D1D9;
    border: 1px solid #21262D;
    border-radius: $dp6;
    outline: none;
}
QTreeWidget::item {
    padding: $dp4 $dp6;
    border-radius: $dp3;
}
QTreeWidget::item:selected {
    background: rgba(212, 165, 116, 0.12);
    color: #D4A574;
}
QTreeWidget::item:hover:!selected {
    background: #1C2128;
}

/* ── Tab Widget ── */
QTabWidget::pane {
    border: 1px solid #21262D;
    border-radius: $dp6;
    background: #0D1117;
}
QTabBar::tab {
    background: transparent;
    color: #8B949E;
    padding: $dp6 $dp14;
    border-bottom: 2px solid transparent;
    font-size: $fs12;
}
QTabBar::tab:selected {
    color: #D4A574;
    border-bottom-color: #D4A574;
}
QTabBar::tab:hover:!selected {
    color: #C9D1D9;
}

/* ── ScrollBar ── */
QScrollBar:vertical {
    background: transparent;
    width: $dp10;
    margin: $dp2;
}
QScrollBar::handle:vertical {
    background: #2A3139;
    min-height: $dp32;
    border-radius: $dp5;
}
QScrollBar::handle:vertical:hover {
    background: #484F58;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0px;
}
QScrollBar:horizontal {
    background: transparent;
    height: $dp10;
    margin: $dp2;
}
QScrollBar::handle:horizontal {
    background: #2A3139;
    min-width: $dp32;
    border-radius: $dp5;
}
QScrollBar::handle:horizontal:hover {
    background: #484F58;
}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
    width: 0px;
}

/* ── ToolTip ── */
QToolTip {
    background: #1C2128;
    color: #E6EDF3;
    border: 1px solid #2A3139;
    border-radius: $dp6;
    padding: $dp5 $dp8;
    font-size: $fs11;
}

/* ── Menu ── */
QMenu {
    background: #161B22;
    color: #E6EDF3;
    border: 1px solid #2A3139;
    border-radius: $dp6;
    padding: $dp4;
}
QMenu::item {
    padding: $dp5 $dp16;
    border-radius: $dp4;
}
QMenu::item:selected {
    background: rgba(212, 165, 116, 0.12);
    color: #D4A574;
}

/* ── Splitter ── */
QSplitter::handle {
    background: #0D1117;
}
QSplitter::handle:hover {
    background: #2A3139;
}

/* ── StatusBar ── */
QStatusBar {
    background: #161B22;
    color: #8B949E;
    border-top: 1px solid #21262D;
    font-size: $fs11;
    padding: 2px 12px;
}

/* ── Scroll Area ── */
QScrollArea {
    border: none;
}

/* ── Settings Button ── */
QPushButton#settingsBtn {
    background: transparent;
    color: #8B949E;
    border: 1px solid transparent;
    border-radius: $dp6;
    font-size: $fs15;
    padding: 2px 6px;
}
QPushButton#settingsBtn:hover {
    background: #1C2128;
    color: #C9D1D9;
    border-color: #2A3139;
}

/* ── Agent Button ── */
QPushButton#agentBtn {
    background: rgba(212, 165, 116, 0.10);
    color: #D4A574;
    border: 1px solid rgba(212, 165, 116, 0.35);
    border-radius: $dp6;
    font-size: $fs14;
}
QPushButton#agentBtn:hover {
    background: rgba(212, 165, 116, 0.18);
    border-color: #D4A574;
}
"""

# Default style (built once at import)
STYLE = build_style(13)
