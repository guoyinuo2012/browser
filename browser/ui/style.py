"""Visual design system for browser (QSS) + system theme detection.

Palette: near-black surfaces, one accent color, 8px radius, subtle lines.
All colors are derived from a base + accent so custom accents retheme
everything, including internal pages.
"""

from __future__ import annotations

import sys


def _mix(c1: tuple, c2: tuple, t: float) -> str:
    r = round(c1[0] + (c2[0] - c1[0]) * t)
    g = round(c1[1] + (c2[1] - c1[1]) * t)
    b = round(c1[2] + (c2[2] - c1[2]) * t)
    return f"#{r:02x}{g:02x}{b:02x}"


def _hex_to_rgb(h: str) -> tuple:
    h = h.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    try:
        return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))
    except ValueError:
        return (79, 140, 255)


def system_is_dark() -> bool:
    """Detect the OS color scheme (dark preferred)."""
    try:
        import darkdetect
        v = darkdetect.isDark()
        if isinstance(v, str):              # older darkdetect returned strings
            return v.lower() != "light"
        return bool(v)
    except ImportError:
        pass
    if sys.platform == "win32":
        try:
            import winreg
            with winreg.OpenKey(
                    winreg.HKEY_CURRENT_USER,
                    r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize") as k:
                val, _ = winreg.QueryValueEx(k, "AppsUseLightTheme")
            return val == 0                 # 0 = dark apps
        except OSError:
            return True
    return True


def build_qss(theme: str, accent: str = "#4f8cff", font_size: int = 14,
              high_contrast: bool = False, reduced_motion: bool = False) -> str:
    """Build the full application stylesheet for a theme/accent."""
    dark = True if theme == "dark" else (False if theme == "light" else system_is_dark())
    if dark:
        bg, bg2, bg3 = (18, 20, 23), (25, 28, 33), (33, 37, 44)
        fg, fg_dim = (232, 234, 240), (154, 162, 177)
        line = (42, 47, 56)
        tab_active = (40, 44, 52)
    else:
        bg, bg2, bg3 = (245, 246, 248), (255, 255, 255), (238, 240, 244)
        fg, fg_dim = (26, 29, 35), (91, 98, 112)
        line = (223, 227, 234)
        tab_active = (255, 255, 255)
    a = _hex_to_rgb(accent)
    accent = _mix(a, (255, 255, 255), 0.0)
    accent_dim = _mix(a, (0, 0, 0) if dark else (255, 255, 255), 0.35)
    danger = "#ff5d5d"
    ok = "#3ecf8e"
    c = {
        "bg": _mix(bg, (0, 0, 0), 0), "bg2": _mix(bg2, (0, 0, 0), 0),
        "bg3": _mix(bg3, (0, 0, 0), 0), "fg": _mix(fg, (0, 0, 0), 0),
        "fg_dim": _mix(fg_dim, (0, 0, 0), 0), "line": _mix(line, (0, 0, 0), 0),
        "accent": accent, "accent_dim": accent_dim, "danger": danger, "ok": ok,
        "sel": _mix(a, fg, 0.85) if not dark else _mix(a, (10, 12, 16), 0.75),
        "tab_active": _mix(tab_active, (0, 0, 0), 0),
    }
    hc_border = "#808896" if high_contrast else c["line"]
    motion = "none" if reduced_motion else "120ms ease"
    return f"""
* {{
  font-size: {font_size}px;
}}
QWidget#MainWindow, QDialog {{ background: {c['bg']}; color: {c['fg']}; }}

/* ---------- toolbar ---------- */
QToolBar#Toolbar {{ background: {c['bg2']}; border: none; padding: 4px 8px; spacing: 4px; }}
QToolBar#Toolbar::separator {{ background: {c['line']}; width: 1px; margin: 6px 4px; }}
QToolButton {{ background: transparent; color: {c['fg']}; border: none;
  border-radius: 8px; padding: 6px 8px; }}
QToolButton:hover {{ background: {c['bg3']}; }}
QToolButton:pressed {{ background: {c['line']}; }}
QToolButton:disabled {{ color: {c['fg_dim']}; }}
QToolButton#menu-button {{ padding: 6px 10px; font-weight: 600; }}

/* ---------- omnibox ---------- */
QLineEdit#Omnibox {{ background: {c['bg3']}; color: {c['fg']};
  border: 1px solid {c['line']}; border-radius: 18px; padding: 6px 34px 6px 14px;
  selection-background-color: {c['accent']}; }}
QLineEdit#Omnibox:focus {{ border-color: {c['accent']}; background: {c['bg2']}; }}
QLineEdit#FindBar {{ background: {c['bg3']}; color: {c['fg']};
  border: 1px solid {c['line']}; border-radius: 8px; padding: 4px 8px; }}

/* ---------- tabs ---------- */
QTabBar::tear {{ width: 0; }}
QTabBar#TabBar {{ background: transparent; }}
QTabBar#TabBar::tab {{
  background: transparent; color: {c['fg_dim']};
  padding: 7px 12px; border: none; border-radius: 8px; margin: 3px 2px;
  min-width: 90px; max-width: 220px;
}}
QTabBar#TabBar::tab:hover {{ background: {c['bg3']}; color: {c['fg']}; }}
QTabBar#TabBar::tab:selected {{ background: {c['tab_active']}; color: {c['fg']};
  border: 1px solid {c['line']}; }}
QTabBar#TabBar::tab[pinned="true"] {{ min-width: 44px; max-width: 44px; }}
QTabBar#TabBar::close-button {{ subcontrol-position: right; }}

/* vertical tabs */
QTabBar#TabBarWest::tab {{ max-width: 260px; min-width: 200px; text-align: left; }}

QTabWidget::pane {{ border: none; }}

/* ---------- lists / menus ---------- */
QMenu {{ background: {c['bg2']}; color: {c['fg']}; border: 1px solid {hc_border};
  border-radius: 10px; padding: 6px; }}
QMenu::item {{ padding: 7px 28px 7px 14px; border-radius: 6px; }}
QMenu::item:selected {{ background: {c['accent_dim']}; }}
QMenu::separator {{ height: 1px; background: {c['line']}; margin: 5px 8px; }}
QMenu::icon {{ padding-left: 8px; }}

QListView#Suggestions {{ background: {c['bg2']}; color: {c['fg']};
  border: 1px solid {c['line']}; border-radius: 12px; padding: 4px; }}
QListView#Suggestions::item {{ padding: 8px 12px; border-radius: 8px; }}
QListView#Suggestions::item:selected {{ background: {c['accent_dim']}; }}

/* ---------- dialogs / settings ---------- */
QDialog {{ background: {c['bg']}; }}
QListWidget#SettingsNav {{ background: {c['bg2']}; border: none;
  border-right: 1px solid {c['line']}; padding: 8px 4px; outline: none; }}
QListWidget#SettingsNav::item {{ padding: 9px 14px; border-radius: 8px; margin: 2px 6px; color: {c['fg_dim']}; }}
QListWidget#SettingsNav::item:selected {{ background: {c['accent_dim']}; color: {c['fg']}; }}
QStackedWidget, QScrollArea {{ background: {c['bg']}; }}
QLabel#SettingsH1 {{ font-size: 20px; font-weight: 700; }}
QLabel#SectionLabel {{ font-size: 13px; color: {c['fg_dim']}; font-weight: 600;
  text-transform: uppercase; letter-spacing: 1px; margin-top: 14px; }}

/* ---------- widgets ---------- */
QPushButton {{ background: {c['bg3']}; color: {c['fg']}; border: 1px solid {hc_border};
  border-radius: 8px; padding: 6px 14px; }}
QPushButton:hover {{ border-color: {c['accent']}; }}
QPushButton:default {{ background: {c['accent']}; color: #ffffff; border-color: {c['accent']}; }}
QPushButton:disabled {{ color: {c['fg_dim']}; }}
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox {{ background: {c['bg3']}; color: {c['fg']};
  border: 1px solid {hc_border}; border-radius: 8px; padding: 5px 8px; }}
QComboBox QAbstractItemView {{ background: {c['bg2']}; color: {c['fg']};
  selection-background-color: {c['accent_dim']}; border: 1px solid {c['line']}; }}
QCheckBox, QRadioButton {{ color: {c['fg']}; spacing: 8px; }}
QCheckBox::indicator, QRadioButton::indicator {{ width: 16px; height: 16px; }}
QProgressBar {{ background: {c['bg3']}; border: none; border-radius: 4px; height: 6px;
  text-align: center; color: transparent; }}
QProgressBar::chunk {{ background: {c['accent']}; border-radius: 3px; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 0; }}
QScrollBar::handle:vertical {{ background: {c['line']}; border-radius: 5px; min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: {c['fg_dim']}; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; }}
QScrollBar::handle:horizontal {{ background: {c['line']}; border-radius: 5px; min-width: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
QToolTip {{ background: {c['bg2']}; color: {c['fg']}; border: 1px solid {c['line']};
  padding: 5px 8px; border-radius: 6px; }}
QStatusBar {{ background: {c['bg2']}; color: {c['fg_dim']}; border-top: 1px solid {c['line']}; }}
QTreeView, QListView, QTableWidget {{ background: {c['bg']}; color: {c['fg']};
  alternate-background-color: {c['bg2']}; }}
QHeaderView::section {{ background: {c['bg2']}; color: {c['fg_dim']};
  border: none; border-bottom: 1px solid {c['line']}; padding: 6px; }}

/* focus visibility for keyboard navigation */
QWidget:focus {{ outline: none; }}
QToolButton:focus, QPushButton:focus, QLineEdit:focus, QComboBox:focus {{
  border-color: {c['accent']};
}}
QTabBar::tab:focus {{ border-color: {c['accent']}; }}

/* bookmarks bar */
QToolBar#BookmarksBar {{ background: {c['bg2']}; border: none;
  border-bottom: 1px solid {c['line']}; padding: 2px 6px; spacing: 2px; }}
QToolBar#BookmarksBar QToolButton {{ padding: 4px 10px; color: {c['fg']}; max-width: 200px; }}

/* downloads popup / panels */
QWidget#Panel {{ background: {c['bg2']}; border: 1px solid {hc_border};
  border-radius: 12px; }}
"""
