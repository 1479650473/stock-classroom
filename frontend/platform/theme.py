# -*- coding: utf-8 -*-
"""Global stylesheet and color constants for stock-classroom."""

FONT_BASE = 13


def fs(size: int) -> str:
    """Return scaled CSS font-size string, e.g. fs(13) -> '13px'."""
    scaled = round(size * FONT_BASE / 13)
    return f"{scaled}px"


def fsi(size: int) -> int:
    """Return scaled font-size as integer (for QFont use)."""
    return round(size * FONT_BASE / 13)


def build_style(base_fs: int = 13) -> str:
    """Build the global QSS stylesheet with given base font-size."""
    global FONT_BASE
    FONT_BASE = base_fs

    scale = base_fs / 13
    s = _TEMPLATE
    for sz in range(8, 37):
        scaled = round(sz * scale)
        s = s.replace(f"$fs{sz}", f"{scaled}px")
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
    border-radius: 8px;
}
QFrame#card:hover {
    border-color: #30363D;
}

/* ── Lists ── */
QListWidget {
    background: #0D1117;
    color: #E6EDF3;
    border: 1px solid #21262D;
    border-radius: 6px;
    outline: none;
}
QListWidget::item {
    padding: 6px 12px;
    border-radius: 4px;
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
    border-radius: 6px;
    gridline-color: #1A1F28;
}
QTableWidget::item {
    padding: 4px 10px;
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
    border-bottom: 2px solid #21262D;
    padding: 6px 10px;
    font-weight: 600;
    font-size: $fs12;
}
QHeaderView::section:horizontal {
    border-right: 1px solid #1A1F28;
}

/* ── Line Edit ── */
QLineEdit {
    background: #161B22;
    color: #E6EDF3;
    border: 1px solid #30363D;
    border-radius: 6px;
    padding: 6px 14px;
    font-size: $fs12;
}
QLineEdit:focus {
    border-color: #D4A574;
}
QLineEdit[placeholderText] {
    color: #484F58;
}

/* ── Push Button ── */
QPushButton {
    background: #1C2128;
    color: #C9D1D9;
    border: 1px solid #30363D;
    border-radius: 6px;
    padding: 5px 16px;
    font-size: $fs12;
}
QPushButton:hover {
    background: #252A35;
    border-color: #484F58;
}
QPushButton:pressed {
    background: #161B22;
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

/* ── Nav Buttons (sidebar style) ── */
QPushButton#navBtn {
    background: transparent;
    color: #8B949E;
    border: none;
    border-radius: 6px;
    padding: 8px 12px;
    font-size: $fs14;
    text-align: left;
}
QPushButton#navBtn:hover {
    background: #1C2128;
    color: #C9D1D9;
}
QPushButton#navBtn:checked {
    background: rgba(212, 165, 116, 0.08);
    color: #D4A574;
    border-left: 3px solid #D4A574;
}

/* ── Indicator Buttons (segmented control) ── */
QPushButton#indBtn {
    background: #161B22;
    color: #8B949E;
    border: 1px solid #30363D;
    border-radius: 4px;
    padding: 3px 14px;
    font-size: $fs12;
}
QPushButton#indBtn:checked {
    background: rgba(212, 165, 116, 0.10);
    color: #D4A574;
    border-color: #D4A574;
}

/* ── CheckBox ── */
QCheckBox {
    color: #8B949E;
    font-size: $fs12;
    spacing: 6px;
}
QCheckBox::indicator {
    width: 14px;
    height: 14px;
    border: 1px solid #30363D;
    border-radius: 3px;
    background: #161B22;
}
QCheckBox::indicator:checked {
    background: #D4A574;
    border-color: #D4A574;
}
QCheckBox::indicator:hover {
    border-color: #484F58;
}

/* ── ComboBox ── */
QComboBox {
    background: #161B22;
    color: #E6EDF3;
    border: 1px solid #30363D;
    border-radius: 6px;
    padding: 4px 10px;
    font-size: $fs12;
}
QComboBox:hover { border-color: #484F58; }
QComboBox::drop-down { border: none; width: 24px; }
QComboBox QAbstractItemView {
    background: #161B22;
    color: #E6EDF3;
    border: 1px solid #30363D;
    selection-background-color: rgba(212, 165, 116, 0.12);
    selection-color: #D4A574;
}

/* ── Tree Widget ── */
QTreeWidget {
    background: #0D1117;
    color: #C9D1D9;
    border: 1px solid #21262D;
    border-radius: 6px;
    outline: none;
}
QTreeWidget::item {
    padding: 4px 8px;
    border-radius: 3px;
}
QTreeWidget::item:selected {
    background: rgba(212, 165, 116, 0.12);
    color: #D4A574;
}
QTreeWidget::item:hover:!selected {
    background: #1C2128;
}
QTreeWidget::branch:!has-children:!has-siblings:adjoins-item {
    border: none;
}

/* ── ScrollBar ── */
QScrollBar:vertical {
    background: #0D1117;
    width: 8px;
    margin: 0;
    border-radius: 4px;
}
QScrollBar::handle:vertical {
    background: #30363D;
    min-height: 30px;
    border-radius: 4px;
}
QScrollBar::handle:vertical:hover {
    background: #484F58;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0px;
}
QScrollBar:horizontal {
    background: #0D1117;
    height: 8px;
    margin: 0;
    border-radius: 4px;
}
QScrollBar::handle:horizontal {
    background: #30363D;
    min-width: 30px;
    border-radius: 4px;
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
    border: 1px solid #30363D;
    border-radius: 6px;
    padding: 6px 10px;
    font-size: $fs11;
}

/* ── Splitter ── */
QSplitter::handle {
    background: #21262D;
    width: 1px;
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
    border: none;
    border-radius: 6px;
    font-size: $fs16;
    padding: 2px 6px;
}
QPushButton#settingsBtn:hover {
    background: #1C2128;
    color: #C9D1D9;
}
"""

# Default style (built once at import)
STYLE = build_style(13)


COLORS = {
    "bg": "#0D1117",
    "panel": "#161B22",
    "border": "#21262D",
    "text": "#E6EDF3",
    "subtext": "#8B949E",
    "accent": "#D4A574",
    "rise": "#E54D2E",
    "fall": "#3FB950",
    "hover": "#1C2128",
    "ma5": "#FFA726",
    "ma10": "#FDBF6E",
    "ma20": "#CE93D8",
    "ma60": "#64B5F6",
    "dif": "#FF6B6B",
}
