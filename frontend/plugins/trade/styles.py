# -*- coding: utf-8 -*-
"""Trade plugin styles — re-exported from the central theme.

Kept as a thin shim so existing imports (`from .styles import C_BG, ...`)
keep working while all values stay in sync with the design system.
"""

from frontend.platform.theme import (
    C_BG, C_PANEL, C_TEXT, C_SUBTEXT, C_ACCENT,
    C_UP, C_DOWN,
)

C_BORDER = "#21262D"
C_GREEN = C_DOWN
C_RED = C_UP
