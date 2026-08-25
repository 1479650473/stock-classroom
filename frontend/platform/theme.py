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

def qss_card(radius: int = 9) -> str:
    return (f"QFrame#card{{background:qlineargradient(x1:0,y1:0,x2:0,y2:1,"
            f"stop:0 #1A212D,stop:0.5 #151A24,stop:1 #11161E);"
            f"border:1px solid #1E2530;border-top:1px solid #37414E;border-radius:{dps(radius)};}}"
            f"QFrame#card:hover{{border-top-color:{C_ACCENT};border-color:#2B3441;}}")


def qss_btn() -> str:
    return (f"QPushButton{{background:qlineargradient(x1:0,y1:0,x2:0,y2:1,"
            f"stop:0 #232C38,stop:1 #1B222C);color:{C_TEXT};"
            f"border:1px solid #2A3340;border-top:1px solid #38424F;border-radius:{dps(6)};"
            f"padding:{dps(4)} {dps(12)};font-size:{fs(12)};font-weight:500;}}"
            f"QPushButton:hover{{background:qlineargradient(x1:0,y1:0,x2:0,y2:1,"
            f"stop:0 #2A3441,stop:1 #202831);border-top-color:{C_ACCENT};color:#F0E6D8;}}"
            f"QPushButton:pressed{{background:#161C25;border-top-color:#10141B;}}"
            f"QPushButton:disabled{{color:{C_FAINT};border-color:#1A2029;}}")


def qss_btn_accent() -> str:
    return (f"QPushButton{{background:qlineargradient(x1:0,y1:0,x2:0,y2:1,"
            f"stop:0 #C99763,stop:1 #B07F4E);color:{C_ON_ACCENT};border:none;"
            f"border-radius:{dps(6)};padding:{dps(5)} {dps(14)};font-size:{fs(12)};font-weight:700;}}"
            f"QPushButton:hover{{background:qlineargradient(x1:0,y1:0,x2:0,y2:1,"
            f"stop:0 #D8B189,stop:1 #BE9264);}}"
            f"QPushButton:pressed{{background:#A97C52;}}"
            f"QPushButton:disabled{{background:{C_OVERLAY};color:{C_FAINT};}}")


def qss_btn_accent_outline() -> str:
    return (f"QPushButton{{background:rgba(212,165,116,0.10);color:{C_ACCENT};"
            f"border:1px solid {C_ACCENT};border-top:1px solid rgba(212,165,116,0.55);"
            f"border-radius:{dps(6)};padding:{dps(4)} {dps(12)};font-size:{fs(12)};font-weight:600;}}"
            f"QPushButton:hover{{background:rgba(212,165,116,0.20);}}"
            f"QPushButton:disabled{{color:{C_FAINT};border-color:{C_BORDER_SOFT};background:transparent;}}")


def qss_input() -> str:
    return (f"QLineEdit{{background:qlineargradient(x1:0,y1:0,x2:0,y2:1,"
            f"stop:0 #1A212C,stop:1 #141A23);color:{C_TEXT};"
            f"border:1px solid #232B36;border-top:1px solid #2D3744;border-radius:{dps(6)};"
            f"padding:{dps(5)} {dps(10)};font-size:{fs(12)};}}"
            f"QLineEdit:focus{{border-color:{C_ACCENT};}}")


def qss_combo() -> str:
    return (f"QComboBox{{background:qlineargradient(x1:0,y1:0,x2:0,y2:1,"
            f"stop:0 #1A212C,stop:1 #141A23);color:{C_TEXT};"
            f"border:1px solid #232B36;border-top:1px solid #2D3744;border-radius:{dps(6)};"
            f"padding:{dps(4)} {dps(10)};font-size:{fs(12)};}}"
            f"QComboBox:hover{{border-top-color:{C_ACCENT};}}"
            f"QComboBox::drop-down{{border:none;width:{dps(24)};}}"
            f"QComboBox QAbstractItemView{{background:#141A23;color:{C_TEXT};"
            f"border:1px solid #2A3340;border-radius:{dps(5)};"
            f"selection-background-color:rgba(212,165,116,0.13);selection-color:#E8C9A0;outline:none;}}")


def qss_spinbox() -> str:
    return (f"QSpinBox,QDoubleSpinBox{{background:qlineargradient(x1:0,y1:0,x2:0,y2:1,"
            f"stop:0 #1A212C,stop:1 #141A23);color:{C_TEXT};"
            f"border:1px solid #232B36;border-radius:{dps(6)};"
            f"padding:{dps(4)} {dps(8)};font-size:{fs(12)};}}"
            f"QSpinBox:focus,QDoubleSpinBox:focus{{border-color:{C_ACCENT};}}")


def qss_table() -> str:
    return (f"QTableWidget{{background:#10141B;color:{C_TEXT};border:1px solid #1E2530;"
            f"border-radius:{dps(8)};gridline-color:#141923;font-size:{fs(12)};}}"
            f"QTableWidget::item{{padding:{dps(4)} {dps(9)};border-bottom:1px solid #12161D;}}"
            f"QTableWidget::item:selected{{background:rgba(212,165,116,0.15);color:#F0D9BC;}}"
            f"QTableWidget::item:hover:!selected{{background:#1A212B;}}"
            f"QHeaderView::section{{background:qlineargradient(x1:0,y1:0,x2:0,y2:1,"
            f"stop:0 #1B222D,stop:1 #161C26);color:{C_SUBTEXT};border:none;"
            f"border-bottom:1px solid #232B36;padding:{dps(5)} {dps(9)};font-weight:600;"
            f"font-size:{fs(10)};letter-spacing:0.5px;}}")


def qss_list() -> str:
    return (f"QListWidget{{background:#12161E;color:{C_TEXT};border:1px solid #1E2530;"
            f"border-radius:{dps(6)};font-size:{fs(12)};outline:none;padding:{dps(3)};}}"
            f"QListWidget::item{{padding:{dps(4)} {dps(9)};border-radius:{dps(4)};}}"
            f"QListWidget::item:selected{{background:rgba(212,165,116,0.13);color:#E8C9A0;}}"
            f"QListWidget::item:hover:!selected{{background:#1B222C;}}")


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
   stock-classroom — Premium Dark Theme (global)
   ============================================================ */
QMainWindow, QWidget {
    background-color: #0D1117;
    color: #E6EDF3;
    font-family: "Segoe UI", "Microsoft YaHei";
    font-size: $fs13;
    selection-background-color: rgba(212, 165, 116, 0.20);
    selection-color: #F0D9BC;
}
/* ── Cards (matte gradient + top highlight bevel) ── */
QFrame#card {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 #1A212D, stop:0.5 #151A24, stop:1 #11161E);
    border: 1px solid #1E2530;
    border-top: 1px solid #37414E;
    border-radius: $dp9;
}
QFrame#card:hover {
    border-top-color: #D4A574;
    border-color: #2B3441;
}

/* ── Lists ── */
QListWidget {
    background: #12161E;
    color: #E6EDF3;
    border: 1px solid #1E2530;
    border-radius: $dp6;
    outline: none;
    padding: $dp3;
}
QListWidget::item {
    padding: $dp5 $dp10;
    border-radius: $dp4;
}
QListWidget::item:selected {
    background: rgba(212, 165, 116, 0.13);
    color: #E8C9A0;
}
QListWidget::item:hover:!selected {
    background: #1B222C;
}

/* ── Tables ── */
QTableWidget {
    background: #10141B;
    color: #E6EDF3;
    border: 1px solid #1E2530;
    border-radius: $dp7;
    gridline-color: #141923;
}
QTableWidget::item {
    padding: $dp4 $dp9;
    border-bottom: 1px solid #12161D;
}
QTableWidget::item:selected {
    background: rgba(212, 165, 116, 0.15);
    color: #F0D9BC;
}
QTableWidget::item:hover:!selected {
    background: #1A212B;
}
QHeaderView::section {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #1B222D, stop:1 #161C26);
    color: #98A1AF;
    border: none;
    border-bottom: 1px solid #232B36;
    padding: $dp5 $dp9;
    font-weight: 600;
    font-size: $fs10;
    letter-spacing: 0.5px;
}
QHeaderView::section:horizontal {
    border-right: 1px solid #161C26;
}
QTableCornerButton::section {
    background: #161C26;
    border: none;
}

/* ── Line Edit / Text Edit ── */
QLineEdit {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #1A212C, stop:1 #141A23);
    color: #E6EDF3;
    border: 1px solid #232B36;
    border-top: 1px solid #2D3744;
    border-radius: $dp6;
    padding: $dp5 $dp10;
    font-size: $fs12;
    selection-background-color: rgba(212, 165, 116, 0.30);
}
QLineEdit:focus { border-color: #D4A574; }
QLineEdit:disabled { color: #6E7681; }

QTextEdit, QPlainTextEdit {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #1A212C, stop:1 #141A23);
    color: #E6EDF3;
    border: 1px solid #232B36;
    border-top: 1px solid #2D3744;
    border-radius: $dp6;
    padding: $dp6;
    font-size: $fs12;
    selection-background-color: rgba(212, 165, 116, 0.30);
}
QTextEdit:focus, QPlainTextEdit:focus { border-color: #D4A574; }

/* ── Push Button (matte gradient + bevel) ── */
QPushButton {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #232C38, stop:1 #1B222C);
    color: #D5DCE5;
    border: 1px solid #2A3340;
    border-top: 1px solid #38424F;
    border-radius: $dp6;
    padding: $dp4 $dp12;
    font-size: $fs12;
    font-weight: 500;
}
QPushButton:hover {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #2A3441, stop:1 #202831);
    border-top-color: #D4A574;
    color: #F0E6D8;
}
QPushButton:pressed {
    background: #161C25;
    border-top-color: #10141B;
}
QPushButton:disabled { color: #5C6570; border-color: #1A2029; }
QPushButton:checked {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #C99763, stop:1 #B07F4E);
    color: #1A1410;
    border-color: #C99763;
    font-weight: 600;
}

/* ── Refresh Button (gold, primary) ── */
QPushButton#refreshBtn {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #D8B189, stop:1 #BE9264);
    color: #1A1410;
    border: 1px solid #C99763;
    border-top: 1px solid #E4C6A4;
    font-weight: 600;
}
QPushButton#refreshBtn:hover {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #E2BE97, stop:1 #CC9E72);
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
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #1C232D, stop:1 #171D26);
    color: #C9D1D9;
}
QPushButton#navBtn:checked {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #253040, stop:1 #1C2530);
    color: #E8C9A0;
    border-left: 2px solid #D4A574;
    font-weight: 600;
}

/* ── Indicator Buttons (segmented control) ── */
QPushButton#indBtn {
    background: #151A23;
    color: #8B949E;
    border: 1px solid #222A35;
    border-top: 1px solid #2C3542;
    border-radius: $dp4;
    padding: $dp3 $dp12;
    font-size: $fs11;
}
QPushButton#indBtn:hover { color: #D5DCE5; border-top-color: #D4A574; }
QPushButton#indBtn:checked {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #C99763, stop:1 #B07F4E);
    color: #1A1410;
    border-color: #C99763;
    font-weight: 600;
}

/* ── CheckBox ── */
QCheckBox { color: #C9D1D9; font-size: $fs12; spacing: $dp6; }
QCheckBox::indicator {
    width: $dp14;
    height: $dp14;
    border: 1px solid #3A4350;
    border-radius: $dp4;
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #1A212C, stop:1 #141A23);
}
QCheckBox::indicator:checked { background: #D4A574; border-color: #D4A574; }
QCheckBox::indicator:hover { border-color: #D4A574; }

/* ── Radio ── */
QRadioButton { color: #C9D1D9; font-size: $fs12; spacing: $dp6; }

/* ── ComboBox ── */
QComboBox {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #1A212C, stop:1 #141A23);
    color: #E6EDF3;
    border: 1px solid #232B36;
    border-top: 1px solid #2D3744;
    border-radius: $dp6;
    padding: $dp4 $dp10;
    font-size: $fs12;
}
QComboBox:hover { border-top-color: #D4A574; }
QComboBox::drop-down { border: none; width: $dp24; }
QComboBox QAbstractItemView {
    background: #141A23;
    color: #E6EDF3;
    border: 1px solid #2A3340;
    border-radius: $dp5;
    selection-background-color: rgba(212, 165, 116, 0.13);
    selection-color: #E8C9A0;
    outline: none;
}

/* ── SpinBox ── */
QSpinBox, QDoubleSpinBox {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #1A212C, stop:1 #141A23);
    color: #E6EDF3;
    border: 1px solid #232B36;
    border-radius: $dp6;
    padding: $dp4 $dp8;
    font-size: $fs12;
}
QSpinBox:focus, QDoubleSpinBox:focus { border-color: #D4A574; }

/* ── ProgressBar ── */
QProgressBar {
    background: #141A23;
    border: 1px solid #1E2530;
    border-radius: $dp5;
    text-align: center;
    color: #98A1AF;
    font-size: $fs10;
}
QProgressBar::chunk {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #D4A574, stop:1 #E0BE96);
    border-radius: $dp4;
}

/* ── Tree Widget ── */
QTreeWidget {
    background: #10141B;
    color: #C9D1D9;
    border: 1px solid #1E2530;
    border-radius: $dp6;
    outline: none;
}
QTreeWidget::item { padding: $dp4 $dp6; border-radius: $dp3; }
QTreeWidget::item:selected { background: rgba(212, 165, 116, 0.13); color: #E8C9A0; }
QTreeWidget::item:hover:!selected { background: #1A212B; }

/* ── Tab Widget ── */
QTabWidget::pane {
    border: 1px solid #1E2530;
    border-radius: $dp6;
    background: #0D1117;
}
QTabBar::tab {
    background: transparent;
    color: #8B949E;
    padding: $dp6 $dp14;
    border-bottom: 2px solid transparent;
    font-size: $fs11;
    letter-spacing: 0.5px;
    font-weight: 500;
}
QTabBar::tab:selected { color: #E8C9A0; border-bottom-color: #D4A574; }
QTabBar::tab:hover:!selected { color: #C9D1D9; }

/* ── ScrollBar (slim rounded, gold hover) ── */
QScrollBar:vertical {
    background: transparent;
    width: $dp9;
    margin: $dp2;
}
QScrollBar::handle:vertical {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #2A3340, stop:1 #232B37);
    min-height: $dp30;
    border-radius: $dp4;
}
QScrollBar::handle:vertical:hover { background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #C99763, stop:1 #A97C52); }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0px; }
QScrollBar:horizontal {
    background: transparent;
    height: $dp9;
    margin: $dp2;
}
QScrollBar::handle:horizontal {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #2A3340, stop:1 #232B37);
    min-width: $dp30;
    border-radius: $dp4;
}
QScrollBar::handle:horizontal:hover { background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #C99763, stop:1 #A97C52); }
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0px; }

/* ── ToolTip ── */
QToolTip {
    background: #1C222D;
    color: #E6EDF3;
    border: 1px solid #2A3340;
    border-top: 1px solid #38424F;
    border-radius: $dp5;
    padding: $dp5 $dp8;
    font-size: $fs11;
}

/* ── Menu ── */
QMenu {
    background: #141A23;
    color: #E6EDF3;
    border: 1px solid #2A3340;
    border-top: 1px solid #38424F;
    border-radius: $dp6;
    padding: $dp4;
}
QMenu::item { padding: $dp5 $dp16; border-radius: $dp4; }
QMenu::item:selected { background: rgba(212, 165, 116, 0.13); color: #E8C9A0; }

/* ── Splitter ── */
QSplitter::handle { background: #0D1117; }
QSplitter::handle:hover { background: #2A3340; }

/* ── StatusBar ── */
QStatusBar {
    background: #141A23;
    color: #98A1AF;
    border-top: 1px solid #1E2530;
    font-size: $fs11;
    padding: 2px 12px;
}

/* ── Scroll Area ── */
QScrollArea { border: none; }

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
    background: #1C232D;
    color: #C9D1D9;
    border-color: #2A3340;
}

/* ── Agent Button ── */
QPushButton#agentBtn {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #2A3441, stop:1 #1E2530);
    color: #E8C9A0;
    border: 1px solid rgba(212, 165, 116, 0.40);
    border-top: 1px solid rgba(212, 165, 116, 0.55);
    border-radius: $dp6;
    font-size: $fs14;
    font-weight: 600;
}
QPushButton#agentBtn:hover {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #344150, stop:1 #27313E);
    border-color: #D4A574;
}
"""

# Default style (built once at import)
STYLE = build_style(13)
