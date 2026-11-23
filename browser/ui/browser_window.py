"""BrowserWindow — the main chrome for browser.

Owns: toolbar + omnibox, bookmarks bar, tab system (horizontal or vertical),
find bar, downloads panel, status bar, menus, keyboard shortcuts, session
management, permission/password prompts, devtools, popups and new windows.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Callable, List, Optional
from urllib.parse import quote_plus

from PyQt6.QtCore import (QPoint, QSize, Qt, QTimer, QUrl, pyqtSignal,
                          pyqtSlot)
from PyQt6.QtGui import QDesktopServices, QIcon, QPixmap
from PyQt6.QtWidgets import (
    QApplication, QCheckBox, QDialog, QFileDialog, QFrame, QHBoxLayout, QLabel,
    QLineEdit, QMainWindow, QMenu, QMessageBox, QPushButton, QSizePolicy,
    QStackedWidget, QStatusBar, QSystemTrayIcon, QTabBar, QTabWidget,
    QToolBar, QToolButton, QVBoxLayout, QWidget, QWidgetAction)

from ..constants import *
from ..core.bookmarks_import import export_bookmarks_html, import_bookmarks_html
from ..core.session import snapshot, save as save_session
from .omnibox import Omnibox
from .tab import WebTab
from . import dialogs as dlg


class TabBar(QTabBar):
    """Tab bar with drag reorder (built-in), middle-click close, context menu,
    pinned state, groups, and compact pinned rendering."""

    group_selected = pyqtSignal(int, str)
    tab_search_requested = pyqtSignal()

    def __init__(self, window: "BrowserWindow", parent=None):
        super().__init__(parent)
        self.window = window
        self.setMovable(True)
        self.setTabsClosable(True)
        self.setExpanding(False)
        self.setUsesScrollButtons(True)
        self.setElideMode(Qt.TextElideMode.ElideRight)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._context_menu)
        self._middle_close = True

    def mousePressEvent(self, ev) -> None:
        if self._middle_close and ev.button() == Qt.MouseButton.MiddleButton:
            idx = self.tabAt(ev.position().toPoint())
            if idx >= 0:
                self.window.close_tab(idx)
                return
        super().mousePressEvent(ev)

    def mouseDoubleClickEvent(self, ev) -> None:
        if self.tabAt(ev.position().toPoint()) < 0:
            self.window.new_tab()
        else:
            super().mouseDoubleClickEvent(ev)

    def _context_menu(self, pos: QPoint) -> None:
        idx = self.tabAt(pos)
        if idx < 0:
            return
        tab = self.window.tabs[idx]
        menu = QMenu(self)
        menu.addAction("New tab to the right", lambda: self.window.new_tab(after_current=True))
        menu.addAction("Duplicate tab", lambda: self.window.duplicate_tab(idx))
        menu.addSeparator()
        pin_menu = menu.addAction(("Unpin tab" if tab.pinned else "Pin tab"),
                                  lambda: self.window.toggle_pin(idx))
        mute_menu = menu.addAction(("Unmute tab" if tab.muted else "Mute tab"),
                                   lambda: self.window.toggle_mute(idx))
        menu.addSeparator()
        group_menu = menu.addMenu("Move to group")
        group_menu.addAction("No group", lambda: self.group_selected.emit(idx, ""))
        names = self.window.group_names()
        for g in names:
            group_menu.addAction(f"● {g}", lambda gg=g: self.group_selected.emit(idx, gg))
        group_menu.addSeparator()
        rename = group_menu.addAction("New group…")
        rename.triggered.connect(lambda: self._new_group(idx))
        menu.addSeparator()
        menu.addAction("Close tab", lambda: self.window.close_tab(idx))
        menu.addAction("Close other tabs", lambda: self.window.close_other_tabs(idx))
        menu.addAction("Close tabs to the right", lambda: self.window.close_tabs_right(idx))
        menu.addSeparator()
        menu.addAction("Search open tabs…", self.tab_search_requested)
        menu.addSeparator()
        menu.addAction("Reopen closed tab", self.window.restore_closed_tab)
        menu.exec(self.mapToGlobal(pos))

    def _new_group(self, idx: int) -> None:
        from PyQt6.QtWidgets import QInputDialog
        name, ok = QInputDialog.getText(self, "Tab group", "Group name:")
        if ok and name.strip():
            self.group_selected.emit(idx, name.strip()[:24])


class FindBar(QFrame):
    """In-page find widget attached to the current tab."""
    def __init__(self, window: "BrowserWindow", parent=None):
        super().__init__(parent)
        self.window = window
        self.setObjectName("Panel")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 6, 10, 6)
        self.edit = QLineEdit()
        self.edit.setObjectName("FindBar")
        self.edit.setPlaceholderText("Find in page")
        self.count = QLabel("")
        prev = QToolButton(); prev.setText("↑")
        nxt = QToolButton(); nxt.setText("↓")
        close = QToolButton(); close.setText("✕")
        lay.addWidget(self.edit, 1)
        lay.addWidget(self.count)
        lay.addWidget(prev)
        lay.addWidget(nxt)
        lay.addWidget(close)
        self.hide()
        self.edit.returnPressed.connect(lambda: self.find(False))
        prev.clicked.connect(lambda: self.find(True))
        nxt.clicked.connect(lambda: self.find(False))
        self.edit.textChanged.connect(lambda t: self.find(False, True))
        close.clicked.connect(self.close_bar)

    def open_bar(self) -> None:
        self.show()
        self.edit.setFocus()
        self.edit.selectAll()

    def close_bar(self) -> None:
        tab = self.window.current_tab
        if tab:
            tab.find_clear()
        self.hide()

    def find(self, backward: bool = False, reset: bool = False) -> None:
        tab = self.window.current_tab
        if not tab:
            return
        text = self.edit.text()

        def report(result) -> None:
            if result is None or not text:
                self.count.setText("")
                return
            try:
                self.count.setText(f"{result.activeMatchOrdinal()}/{result.numberOfMatches()}")
            except Exception:
                self.count.setText("")

        if reset:
            tab.find(text, callback=report)
        else:
            tab.find(text, backward=backward, callback=report)


class DownloadsPanel(QFrame):
    """Toolbar-attached live download progress panel."""
    def __init__(self, manager, store, window, parent=None):
        super().__init__(parent)
        self.manager = manager
        self.store = store
        self.window = window
        self.setObjectName("Panel")
        self.setFixedWidth(460)
        self.setWindowFlags(Qt.WindowType.Popup)
        lay = QVBoxLayout(self)
        head = QHBoxLayout()
        head.addWidget(QLabel("<b>Downloads</b>"))
        head.addStretch(1)
        clear_btn = QToolButton(); clear_btn.setText("Clear records")
        clear_btn.clicked.connect(self._clear_records)
        head.addWidget(clear_btn)
        all_btn = QToolButton(); all_btn.setText("All downloads")
        all_btn.clicked.connect(self._open_page)
        head.addWidget(all_btn)
        lay.addLayout(head)
        self.listw = QVBoxLayout()
        self.listw.setSpacing(4)
        lay.addLayout(self.listw)
        self.refresh()

    def _open_page(self) -> None:
        self.hide()
        self.window.open_internal(URL_DOWNLOADS)

    def _clear_records(self) -> None:
        self.store.clear_downloads()
        self.refresh()

    def refresh(self) -> None:
        while self.listw.count():
            it = self.listw.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
        for r in self.store.downloads(12):
            row = QFrame()
            rl = QHBoxLayout(row)
            rl.setContentsMargins(6, 4, 6, 4)
            name = os.path.basename(r["path"]) or r["url"][:40]
            lbl = QLabel(f"<b>{name}</b><br><span style='color:#9aa2b1'>{r['state']}"
                         + (f" — {r['danger']}" if r["danger"] else "") + "</span>")
            lbl.setTextFormat(Qt.TextFormat.RichText)
            rl.addWidget(lbl, 1)
            if r["state"] == "in_progress":
                item = self.manager.item(r["id"])
                if item:
                    pause = QToolButton(); pause.setText("⏸")
                    pause.clicked.connect(item.pause)
                    resume = QToolButton(); resume.setText("▶")
                    resume.clicked.connect(item.resume)
                    cancel = QToolButton(); cancel.setText("✕")
                    cancel.clicked.connect(item.cancel)
                    rl.addWidget(pause); rl.addWidget(resume); rl.addWidget(cancel)
            else:
                open_btn = QToolButton(); open_btn.setText("Open")
                path = r["path"]
                open_btn.clicked.connect(
                    lambda _=False, p=path: QDesktopServices.openUrl(
                        QUrl.fromLocalFile(p)))
                rl.addWidget(open_btn)
            self.listw.addWidget(row)
        if self.store.downloads(1) == []:
            self.listw.addWidget(QLabel("No downloads yet."))


class BrowserWindow(QMainWindow):
    """One browser window (normal or private)."""

    def __init__(self, app_state, private: bool = False, urls: Optional[List[str]] = None,
                 parent=None):
        super().__init__(parent)
        self.app_state = app_state          # AppState: shared managers + profiles
        self.private = private
        self.settings = app_state.settings
        self.store = app_state.store
        self.services = app_state.services
        self.tabs: List[WebTab] = []
        self.closed_tabs: List[dict] = []
        self._session_dirty = False

        self.setWindowTitle(f"{APP_NAME}" + (" — private" if private else ""))
        self.setWindowIcon(self._app_icon())
        self.resize(1280, 820)

        self.profile = app_state.private_profile if private else app_state.profile

        self.tabwidget = QTabWidget()
        self.tabwidget.setDocumentMode(True)
        self.tabwidget.tabBar().deleteLater()
        self.tabbar = TabBar(self)
        self.tabwidget.setTabBar(self.tabbar)
        self.tabwidget.setTabsClosable(True)
        self.tabwidget.setMovable(True)
        self.tabwidget.tabCloseRequested.connect(lambda i: self.close_tab(i))
        self.tabwidget.currentChanged.connect(self._on_tab_switched)

        self._build_toolbar()
        central = QWidget()
        v = QVBoxLayout(central)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)
        v.addWidget(self.toolbar)
        if not self.settings.get("appearance.compact_toolbar"):
            pass
        v.addWidget(self.tabwidget, 1)
        self.setCentralWidget(central)

        self.findbar = FindBar(self)
        self.statusBar().setVisible(True)

        self._apply_layout_mode()
        self._connect_session_autosave()

        # initial tab(s)
        if urls:
            for u in urls:
                self.new_tab(u if u else URL_HOME)
        else:
            self.new_tab(URL_HOME)
        self._add_shortcuts()
        self._apply_theme()

    # ------------------------------------------------------------------ #
    # tab plumbing
    # ------------------------------------------------------------------ #
    def _app_icon(self) -> QIcon:
        pm = QPixmap(64, 64)
        pm.fill(Qt.GlobalColor.transparent)
        from PyQt6.QtGui import QPainter, QColor, QFont
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setBrush(QColor("#4f8cff"))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(4, 4, 56, 56, 14, 14)
        p.setPen(QColor("white"))
        f = QFont(); f.setBold(True); f.setPointSize(24)
        p.setFont(f)
        p.drawText(pm.rect(), Qt.AlignmentFlag.AlignCenter, "b")
        p.end()
        return QIcon(pm)

    def current_tab(self) -> Optional[WebTab]:
        i = self.tabwidget.currentIndex()
        return self.tabs[i] if 0 <= i < len(self.tabs) else None

    def _make_tab(self, url: str = "") -> WebTab:
        tab = WebTab(self.profile, self.services, self)
        i = self.tabwidget.addTab(tab, "New tab")
        self.tabs.append(tab)
        tab.title_changed.connect(lambda t, tt=tab: self._on_title(tt, t))
        tab.url_changed.connect(lambda u, tt=tab: self._on_url(tt, u))
        tab.icon_changed.connect(lambda tt=tab: self._on_icon(tt))
        tab.load_started.connect(lambda tt=tab: self._on_load_started(tt))
        tab.load_progress.connect(lambda p, tt=tab: self._on_progress(tt, p))
        tab.load_finished.connect(lambda ok, tt=tab: self._on_load_finished(tt, ok))
        tab.status_message.connect(self._on_status)
        tab.popup_blocked.connect(self._on_popup_blocked)
        tab.save_password_prompt.connect(self._on_save_password)
        tab.permission_prompt.connect(self._on_permission_prompt)
        tab.close_requested.connect(lambda tt=tab: self.close_tab_for(tt))
        tab.fullscreen_requested.connect(self._on_fullscreen)
        tab.open_new_tab.connect(lambda u, bg, tt=tab: self.new_tab(u, background=bg))
        tab.open_new_window.connect(lambda u, priv: self._open_external_window(u, priv))
        if url:
            tab.load_url(url)
        return tab

    def new_tab(self, url: str = "", background: bool = False, after_current: bool = False) -> WebTab:
        tab = self._make_tab(url if url else (URL_HOME if self.settings.get(
            "general.new_tab_page") == "home" else "about:blank"))
        i = self.tabs.index(tab)
        if after_current and self.settings.get("tabs.new_tab_position", "end") != "end" or after_current:
            target = self.tabwidget.currentIndex() + 1
            self.tabwidget.moveTab(i, target)
            self.tabs.insert(target, self.tabs.pop(i))
            i = target
        if not background:
            self.tabwidget.setCurrentIndex(i)
        self._mark_session_dirty()
        self._update_tab_decorations()
        return tab

    def duplicate_tab(self, idx: int) -> None:
        t = self.tabs[idx]
        self.new_tab(t.url_string)

    def close_tab(self, idx: int) -> None:
        if idx < 0 or idx >= len(self.tabs):
            return
        tab = self.tabs[idx]
        multi = len(self.tabs) > 1
        if (not multi and not self.private
                and self.settings.get("general.ask_on_close_multiple_tabs") is False):
            pass
        if not multi and not self.private:
            # keep the window alive with a fresh tab
            self.closed_tabs.append({"url": tab.url_string, "title": tab.page.title()})
            self.tabs.pop(idx)
            self.tabwidget.removeTab(idx)
            tab.shutdown()
            self.new_tab(URL_HOME)
            return
        if not self.private and tab.url_string and tab.url_string != "about:blank":
            self.closed_tabs.append({"url": tab.url_string, "title": tab.page.title()})
        self.tabs.pop(idx)
        self.tabwidget.removeTab(idx)
        tab.shutdown()
        self._mark_session_dirty()
        self._update_tab_decorations()
        if not self.tabs and self.private:
            self.close()

    def close_tab_for(self, tab: WebTab) -> None:
        if tab in self.tabs:
            self.close_tab(self.tabs.index(tab))

    def close_other_tabs(self, idx: int) -> None:
        keep = self.tabs[idx]
        for t in list(self.tabs):
            if t is not keep:
                self.close_tab_for(t)

    def close_tabs_right(self, idx: int) -> None:
        for t in list(self.tabs[idx + 1:]):
            self.close_tab_for(t)

    def restore_closed_tab(self) -> None:
        if not self.closed_tabs:
            self._on_status("Nothing to reopen")
            return
        entry = self.closed_tabs.pop()
        self.new_tab(entry["url"] or URL_HOME)

    def toggle_pin(self, idx: int) -> None:
        tab = self.tabs[idx]
        tab.pinned = not tab.pinned
        self._update_tab_decorations()
        self._mark_session_dirty()

    def toggle_mute(self, idx: int) -> None:
        tab = self.tabs[idx]
        tab.set_muted(not tab.muted)
        self._update_tab_decorations()

    def group_names(self) -> List[str]:
        return sorted({t.group_name for t in self.tabs if t.group_name})

    def assign_group(self, idx: int, name: str) -> None:
        self.tabs[idx].group_name = name
        self._update_tab_decorations()
        self._mark_session_dirty()

    def _update_tab_decorations(self) -> None:
        for i, tab in enumerate(self.tabs):
            label = ""
            if tab.pinned:
                label = "📌 "
            if tab.muted:
                label += "🔇 "
            if tab.group_name:
                label += f"[{tab.group_name}] "
            self.tabwidget.setTabText(i, label + (tab.page.title() or "New tab"))
            self.tabwidget.setTabToolTip(i, tab.url_string)

    def _on_title(self, tab: WebTab, title: str) -> None:
        i = self.tabs.index(tab) if tab in self.tabs else -1
        if i >= 0:
            self._update_tab_decorations()
        if self.current_tab() is tab:
            self.setWindowTitle(f"{title} — {APP_NAME}" + (" (private)" if self.private else ""))
        self._mark_session_dirty()

    def _on_url(self, tab: WebTab, url: QUrl) -> None:
        if self.current_tab() is tab:
            self.omnibox.set_tab(tab)
            self._update_nav_buttons()
            self._update_star()
        self._mark_session_dirty()

    def _on_icon(self, tab: WebTab) -> None:
        i = self.tabs.index(tab) if tab in self.tabs else -1
        if i >= 0:
            try:
                self.tabwidget.setTabIcon(i, tab.view.icon())
            except Exception:
                pass    # tab may already be closing

    def _on_load_started(self, tab: WebTab) -> None:
        if self.current_tab() is tab:
            self._update_nav_buttons()

    def _on_progress(self, tab: WebTab, pct: int) -> None:
        if self.current_tab() is tab:
            self.statusBar().showMessage(f"Loading… {pct}%", 1500)

    def _on_load_finished(self, tab: WebTab, ok: bool) -> None:
        if self.current_tab() is tab:
            self._update_nav_buttons()
            self._update_star()
            self._update_security_badge()
        if tab in self.tabs:
            self._update_tab_decorations()

    def _on_status(self, text: str) -> None:
        self.statusBar().showMessage(text, 4000)

    def _on_tab_switched(self, _i: int) -> None:
        tab = self.current_tab()
        self.omnibox.set_tab(tab)
        self._update_nav_buttons()
        self._update_star()
        self._update_security_badge()

    # ------------------------------------------------------------------ #
    # toolbar & menus
    # ------------------------------------------------------------------ #
    def _build_toolbar(self) -> None:
        self.toolbar = QToolBar("Toolbar")
        self.toolbar.setObjectName("Toolbar")
        self.toolbar.setMovable(False)
        self.toolbar.setIconSize(QSize(18, 18))
        self.addToolBar(self.toolbar)

        def btn(text: str, tip: str, slot: Callable, obj: str = "") -> QToolButton:
            b = QToolButton()
            b.setText(text)
            b.setToolTip(tip)
            b.clicked.connect(slot)
            if obj:
                b.setObjectName(obj)
            return b

        self.back_btn = btn("←", "Back (Alt+←)", self._go_back)
        self.fwd_btn = btn("→", "Forward (Alt+→)", self._go_forward)
        self.reload_btn = btn("⟳", "Reload (F5)", self._reload)
        self.home_btn = btn("⌂", "Home (Alt+Home)", self._go_home)
        self.toolbar.addWidget(self.back_btn)
        self.toolbar.addWidget(self.fwd_btn)
        self.toolbar.addWidget(self.reload_btn)
        self.toolbar.addWidget(self.home_btn)

        self.omnibox = Omnibox(self.services)
        self.omnibox.navigate_requested.connect(self._navigate)
        self.omnibox.open_in_new_tab.connect(lambda u, bg: self.new_tab(u, background=bg))
        w = QWidget()
        wl = QHBoxLayout(w)
        wl.setContentsMargins(6, 0, 6, 0)
        wl.addWidget(self.omnibox)
        wl.setStretchFactor(self.omnibox, 1)
        self.toolbar.addWidget(w)
        self.toolbar.addWidget(btn("QR", "Show QR code for this page", self._show_qr))
        self.star_btn = btn("☆", "Bookmark this page (Ctrl+D)", self._toggle_bookmark)
        self.toolbar.addWidget(self.star_btn)
        self.shield_btn = btn("🛡 0", "Privacy dashboard — trackers blocked this session",
                              lambda: self.open_internal(URL_PRIVACY))
        self.toolbar.addWidget(self.shield_btn)
        self.dl_btn = btn("⬇", "Downloads (Ctrl+J)", self._toggle_downloads)
        self.toolbar.addWidget(self.dl_btn)
        self.menu_btn = btn("≡", "Menu", self._show_menu)
        self.toolbar.addWidget(self.menu_btn)

        # bookmarks bar
        self.bookmarks_bar = QToolBar("BookmarksBar")
        self.bookmarks_bar.setObjectName("BookmarksBar")
        self.bookmarks_bar.setMovable(False)
        self.addToolBar(self.bookmarks_bar)
        self.bookmarks_bar.setVisible(self.settings.get("appearance.show_bookmarks_bar", True))
        self._rebuild_bookmarks_bar()

        self.services.open_tabs = self.open_tabs
        self.services.current_url = lambda: (self.current_tab().url_string
                                             if self.current_tab() else "")
        self.services.current_https = lambda: (self.current_tab().url_string.startswith("https://")
                                               if self.current_tab() else False)
        self.services.current_cert = lambda: ("Validated by Chromium" if
                                              (self.current_tab() and self.current_tab().url_string.startswith("https://"))
                                              else "")
        self.services.request_settings = lambda: self.open_settings()
        self.services.request_unlock = self._request_unlock
        self.services.request_import_file = self._import_export_dispatch
        self.services.open_file = lambda p: QDesktopServices.openUrl(QUrl.fromLocalFile(p))

    def _rebuild_bookmarks_bar(self) -> None:
        self.bookmarks_bar.clear()
        for row in self.store.children(None):
            if row["is_folder"]:
                btn = QToolButton()
                btn.setText(f"📁 {row['title']}")
                btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
                menu = QMenu(btn)
                for child in self.store.children(row["id"]):
                    if child["is_folder"]:
                        continue
                    act = menu.addAction(child["title"] or child["url"])
                    act.triggered.connect(lambda _=False, u=child["url"]: self._navigate(u))
                menu.addSeparator()
                menu.addAction("Open folder view",
                               lambda fid=row["id"]: self.open_internal(
                                   f"browser://bookmarks?folder={fid}"))
                btn.setMenu(menu)
                self.bookmarks_bar.addWidget(btn)
            else:
                btn = QToolButton()
                btn.setText(row["title"] or row["url"])
                btn.clicked.connect(lambda _=False, u=row["url"]: self._navigate(u))
                self.bookmarks_bar.addWidget(btn)

    def open_tabs(self) -> List[WebTab]:
        return [t for t in self.tabs if t is not None]

    # -- navigation actions ----------------------------------------------------
    def _go_back(self) -> None:
        t = self.current_tab()
        if t: t.back()

    def _go_forward(self) -> None:
        t = self.current_tab()
        if t: t.forward()

    def _reload(self) -> None:
        t = self.current_tab()
        if t: t.reload()

    def _go_home(self) -> None:
        t = self.current_tab()
        if t: t.home()

    def _update_nav_buttons(self) -> None:
        t = self.current_tab()
        if not t:
            return
        self.back_btn.setEnabled(t.page.history().canGoBack())
        self.fwd_btn.setEnabled(t.page.history().canGoForward())
        self.reload_btn.setText("✕" if t.page.isLoading() else "⟳")

    def _update_star(self) -> None:
        t = self.current_tab()
        if not t:
            return
        u = t.url_string
        self.star_btn.setText("★" if u and self.store.find_bookmark_by_url(u) else "☆")

    def _update_security_badge(self) -> None:
        t = self.current_tab()
        u = t.url_string if t else ""
        if u.startswith("https://"):
            self.security_label = "🔒"
        elif u.startswith("http://"):
            self.security_label = "⚠"
        else:
            self.security_label = ""

    def _navigate(self, text: str) -> None:
        t = self.current_tab()
        if not t:
            t = self.new_tab("")
        from ..core.search import normalize_input, BUILTIN_ENGINES, SearchEngine
        engine_name = self.settings.get("search.default_engine", "DuckDuckGo")
        engine = BUILTIN_ENGINES.get(engine_name)
        for ce in self.settings.get("search.custom_engines", []):
            if ce.get("name") == engine_name:
                engine = SearchEngine(ce["name"], ce["url"], ce.get("suggest_url", ""))
        engine = engine or BUILTIN_ENGINES["DuckDuckGo"]
        url, kind = normalize_input(text, engine)
        t.load_url(url)

    # -- bookmarks -----------------------------------------------------------
    def _toggle_bookmark(self) -> None:
        t = self.current_tab()
        if not t:
            return
        url, title = t.url_string, t.page.title() or t.url_string
        existing = self.store.find_bookmark_by_url(url)
        if existing:
            self.store.delete_bookmark(existing["id"])
            self._on_status("Bookmark removed")
        else:
            if self.store.duplicate_url_exists(url):
                self._on_status("A bookmark for this page already exists")
            else:
                self.store.add_bookmark(title, url)
                self._on_status("Bookmark added")
        self._update_star()
        self._rebuild_bookmarks_bar()
        self._mark_session_dirty()

    # -- menus ---------------------------------------------------------------
    def _show_menu(self) -> None:
        """Main (three-dots style) menu, mirroring the modern browser layout."""
        menu = QMenu(self)
        # -- quick window actions --------------------------------------- #
        top = menu.addMenu("New")
        top.addAction("New tab", "Ctrl+T", lambda: self.new_tab())
        top.addAction("New window", "Ctrl+N", self._new_window)
        top.addAction("New private window", "Ctrl+Shift+N", self._new_private_window)
        top.addAction("Open file\u2026", "Ctrl+O", self._open_file)

        # -- data sections (like the modern menu) ------------------------ #
        m = menu.addMenu("Passwords and autofill")
        m.addAction("Show saved passwords",
                    lambda: self.open_internal(URL_PASSWORDS))
        m.addAction("Password generator\u2026", lambda: self.open_internal(
            URL_PASSWORDS + "?action=generate"))
        m.addAction("Lock vault now", self._lock_vault)

        m = menu.addMenu("History")
        for entry in self._recent_history(8):
            m.addAction(entry["title"][:50] or entry["url"][:50],
                        lambda e=entry: self.new_tab(e["url"]))
        if m.actions():
            m.addSeparator()
        m.addAction("Show all history", "Ctrl+H",
                    lambda: self.open_internal(URL_HISTORY))

        m = menu.addMenu("Downloads")
        m.addAction("Show downloads", "Ctrl+J",
                    lambda: self.open_internal(URL_DOWNLOADS))
        m.addAction("Clear download records", self._clear_download_records)

        m = menu.addMenu("Bookmarks and lists")
        m.addAction("Bookmark this page", "Ctrl+D", self._toggle_bookmark)
        m.addAction("Show all bookmarks", "Ctrl+Alt+B",
                    lambda: self.open_internal(URL_BOOKMARKS))
        m.addSeparator()
        m.addAction("Import bookmarks (HTML)\u2026", self._import_bookmarks)
        m.addAction("Export bookmarks (HTML)\u2026", self._export_bookmarks)

        m = menu.addMenu("Tab groups")
        tab = self.current_tab()
        if tab is not None and self.tabs:
            idx = self.tabs.index(tab)
            gmenu = m.addMenu(f"Move \u201c{(tab.page.title() or 'This tab')[:30]}\u201d to group")
            gmenu.addAction("No group",
                            lambda: self.tabwidget.group_selected.emit(idx, ""))
            for g in self.group_names():
                gmenu.addAction(f"\u25cf {g}",
                                lambda gg=g, i=idx: self.tabwidget.group_selected.emit(i, gg))
            gmenu.addSeparator()
            gmenu.addAction("New group\u2026",
                            lambda: self.tabwidget._new_group(idx))
        hint = m.addAction("(Also available: right-click a tab)")
        hint.setEnabled(False)

        ext_menu = self._extensions_menu(menu)
        if ext_menu is None:
            ext_menu = QMenu("Extensions", menu)
            ext_menu.addAction("Manage extensions\u2026",
                               lambda: self.open_internal(URL_EXTENSIONS))
        menu.addMenu(ext_menu)

        menu.addAction("Delete browsing data\u2026", "Ctrl+Shift+Del",
                       self._open_clear_data)
        menu.addSeparator()

        # -- zoom row ---------------------------------------------------- #
        wa = QWidgetAction(menu)
        wa.setDefaultWidget(self._zoom_row_widget())
        menu.addAction(wa)
        menu.addSeparator()

        # -- page actions ------------------------------------------------ #
        menu.addAction("Print\u2026", "Ctrl+P", self._print)
        menu.addAction("Search this tab with Google Lens", self._search_lens)
        menu.addAction("Translate\u2026", self._translate)
        m = menu.addMenu("Find and edit")
        m.addAction("Find in page\u2026", "Ctrl+F", self.findbar.open_bar)
        m.addSeparator()
        m.addAction("Cut", "Ctrl+X", lambda: self._page_action(QWebEnginePage.WebAction.Cut))
        m.addAction("Copy", "Ctrl+C", lambda: self._page_action(QWebEnginePage.WebAction.Copy))
        m.addAction("Paste", "Ctrl+V", lambda: self._page_action(QWebEnginePage.WebAction.Paste))
        m.addAction("Select all", "Ctrl+A", lambda: self._page_action(QWebEnginePage.WebAction.SelectAll))

        m = menu.addMenu("Save, share and cast")
        m.addAction("Save page as\u2026", "Ctrl+S", self._save_page)
        m.addAction("Save as PDF\u2026", self._print_pdf)
        m.addSeparator()
        m.addAction("Copy page link", self._copy_page_link)
        m.addAction("Email link\u2026", self._email_link)
        m.addAction("QR code for this page", self._qr_current)
        m.addSeparator()
        cast = m.addAction("Cast\u2026")
        cast.setEnabled(False)
        cast.setToolTip("Not supported by this engine (QtWebEngine)")

        m = menu.addMenu("More tools")
        m.addAction("Developer tools", "F12", self._open_devtools)
        m.addAction("Inspect element", "Ctrl+Shift+I", self._inspect)
        m.addAction("View page source", "Ctrl+U", self._view_source)
        m.addAction("Screenshot visible page\u2026", self._screenshot)
        m.addAction("Reader mode", "Alt+R", self._reader_mode)
        m.addSeparator()
        m.addAction("Privacy dashboard", lambda: self.open_internal(URL_PRIVACY))
        m.addAction("Security dashboard", lambda: self.open_internal(URL_SECURITY))
        m.addAction("Permissions", lambda: self.open_internal(URL_PERMISSIONS))
        m.addSeparator()
        m.addAction("Search open tabs\u2026", "Ctrl+Shift+A", self._tab_search)
        vtabs = m.addAction("Vertical tabs")
        vtabs.setCheckable(True)
        vtabs.setChecked(self.settings.get("appearance.vertical_tabs"))
        vtabs.toggled.connect(self._toggle_vertical_tabs)

        # -- bottom row -------------------------------------------------- #
        menu.addSeparator()
        m = menu.addMenu("Help")
        m.addAction(f"About {APP_NAME}", lambda: self.open_internal(URL_ABOUT))
        m.addAction("Check for updates\u2026", self._check_updates)
        menu.addAction("Settings\u2026", "Ctrl+,", self.open_settings)
        menu.addAction("Exit", "Ctrl+Q", QApplication.instance().quit)
        menu.exec(self.menu_btn.mapToGlobal(QPoint(0, self.menu_btn.height())))

    def _recent_history(self, limit: int) -> list:
        try:
            return self.store.search_history("", limit)
        except Exception:
            return []

    def _zoom_row_widget(self) -> QWidget:
        row = QWidget()
        lay = QHBoxLayout(row)
        lay.setContentsMargins(10, 4, 10, 4)
        lay.addWidget(QLabel("Zoom"))
        lay.addStretch(1)
        t = self.current_tab()
        zoom_pct = int(round(t.view.zoomFactor() * 100)) if t is not None else 100
        out_btn = QPushButton("\u2212")
        out_btn.setFixedWidth(32)
        out_btn.clicked.connect(lambda: self.current_tab() and self.current_tab().zoom_out())
        lay.addWidget(out_btn)
        self._zoom_label = QLabel(f"{zoom_pct}%")
        self._zoom_label.setFixedWidth(44)
        self._zoom_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(self._zoom_label)
        in_btn = QPushButton("+")
        in_btn.setFixedWidth(32)
        in_btn.clicked.connect(lambda: self.current_tab() and self.current_tab().zoom_in())
        lay.addWidget(in_btn)
        fs_btn = QPushButton("\u26f6")
        fs_btn.setFixedWidth(32)
        fs_btn.setToolTip("Full screen (F11)")
        fs_btn.clicked.connect(lambda: self._toggle_fullscreen())
        lay.addWidget(fs_btn)
        return row

    def _refresh_zoom_label(self) -> None:
        t = self.current_tab()
        lbl = getattr(self, "_zoom_label", None)
        if lbl is not None and t is not None:
            lbl.setText(f"{int(round(t.view.zoomFactor() * 100))}%")

    def _search_lens(self) -> None:
        """Google Lens on this tab's best image (or the Lens upload page)."""
        t = self.current_tab()
        if t is None:
            return
        from PyQt6.QtGui import QDesktopServices
        from ..core.share import LENS_IMAGE_JS, lens_image_url, lens_page_url

        def go(img) -> None:
            QDesktopServices.openUrl(QUrl(
                lens_image_url(img) if img else lens_page_url()))
        t.page.runJavaScript(LENS_IMAGE_JS, go)

    def _copy_page_link(self) -> None:
        t = self.current_tab()
        if t is None:
            return
        title = t.page.title() or ""
        QApplication.clipboard().setText(
            f"{title}\n{t.url_string}" if title else t.url_string)

    def _email_link(self) -> None:
        t = self.current_tab()
        if t is None:
            return
        from PyQt6.QtGui import QDesktopServices
        from ..core.share import email_share_url
        QDesktopServices.openUrl(QUrl(email_share_url(
            t.url_string, t.page.title())))

    def _qr_current(self) -> None:
        t = self.current_tab()
        if t is None:
            return
        from urllib.parse import quote
        self.new_tab(f"{SCHEME_STR}://qr?url={quote(t.url_string, safe='')}")

    def _lock_vault(self) -> None:
        v = self.app_state.vault
        if v is not None and hasattr(v, "lock"):
            v.lock()

    def _extensions_menu(self, parent_menu) -> Optional[QMenu]:
        """Per-site quick toggles for extensions on the current page."""
        exts = self.app_state.extensions
        tab = self.current_tab()
        if exts is None or tab is None:
            return None
        u = tab.page.url()
        if u.scheme() not in ("http", "https"):
            return None
        host = u.host()
        menu = QMenu("Extensions", parent_menu)
        for ext in exts.all():
            label = ext.name
            act = menu.addAction(label)
            act.setCheckable(True)
            pref = exts.site_pref(ext.id, host)
            if ext.default_on:
                act.setChecked(pref is not False)
                act.setToolTip("Uncheck to disable on this site")
                act.toggled.connect(
                    lambda on, eid=ext.id, h=host:
                    exts.set_site_pref(eid, h, on if not on else None))
            else:
                act.setChecked(pref is True)
                act.setToolTip("Check to enable on this site")
                act.toggled.connect(
                    lambda on, eid=ext.id, h=host:
                    exts.set_site_pref(eid, h, True if on else None))
            act.toggled.connect(lambda _checked: self._reload_current())
        menu.addSeparator()
        menu.addAction("Manage extensions…",
                       lambda: self.open_internal(URL_EXTENSIONS))
        return menu

    def _reload_current(self) -> None:
        t = self.current_tab()
        if t:
            t.page.reload()

    def _page_action(self, action) -> None:
        t = self.current_tab()
        if t:
            t.page.triggerAction(action)

    def _new_window(self) -> None:
        self.app_state.open_window(private=False)

    def _new_private_window(self) -> None:
        self.app_state.open_window(private=True)

    def _open_external_window(self, url: str, private: bool) -> None:
        w = self.app_state.open_window(private=private and not self.private)
        if w is not self and url:
            w.new_tab(url)

    def handle_new_window(self, tab: WebTab, request) -> None:
        """Synchronous popup/new-window handling (must attach a page)."""
        from PyQt6.QtWebEngineCore import QWebEngineNewWindowRequest
        dest = request.destination()
        url = request.requestedUrl().toString()
        if dest == QWebEngineNewWindowRequest.DestinationType.InNewTab:
            new_tab = self.new_tab(url, background=True)
            request.openIn(new_tab.page)
        elif dest == QWebEngineNewWindowRequest.DestinationType.InNewDialog:
            w = self.app_state.open_window(private=self.private)
            new_tab = w.new_tab(url)
            request.openIn(new_tab.page)
        else:
            w = self.app_state.open_window(private=self.private)
            new_tab = w.new_tab(url)
            request.openIn(new_tab.page)

    # -- internal pages ----------------------------------------------------------
    def open_internal(self, url: str) -> None:
        t = self.current_tab()
        if not t:
            t = self.new_tab("")
        t.load_url(url)

    # -- prompts -----------------------------------------------------------------
    def _on_permission_prompt(self, origin: str, feature: str, respond: Callable) -> None:
        prompt = dlg.PermissionPromptDialog(origin, feature, self)
        prompt.exec()
        respond(prompt.result_action == "allow", prompt.remember)
        self._on_status(f"{origin}: {feature} "
                        f"{'allowed' if prompt.result_action == 'allow' else 'blocked'}")

    def _on_save_password(self, origin: str, username: str, password: str) -> None:
        if not self.settings.get("passwords.save_prompts", True):
            return
        if self.private:
            return   # never save passwords from private sessions
        d = dlg.SavePasswordDialog(origin, username, password, self)
        if d.exec() and d.save:
            self.app_state.vault.add(origin, d.final_username, d.final_password)
            self._on_status("Password saved (encrypted)")

    def _request_unlock(self) -> None:
        d = dlg.MasterPasswordDialog("unlock", self)
        if d.exec() and d.ok:
            if self.app_state.vault.unlock(d.value):
                self._on_status("Vault unlocked")
            else:
                QMessageBox.warning(self, APP_NAME, "Wrong password.")

    # -- downloads ---------------------------------------------------------------
    def _toggle_downloads(self) -> None:
        if getattr(self, "_dl_panel", None) and self._dl_panel.isVisible():
            self._dl_panel.hide()
            return
        self._dl_panel = DownloadsPanel(self.app_state.downloader, self.store, self)
        self._dl_panel.move(self.dl_btn.mapToGlobal(QPoint(0, self.dl_btn.height())))
        self._dl_panel.show()

    def _clear_download_records(self) -> None:
        self.store.clear_downloads()
        self._on_status("Download records cleared")

    def _on_download_warning(self, info: dict, callback: Callable) -> None:
        d = dlg.DangerDownloadDialog(info["filename"], info["danger"], info.get("note", ""), self)
        d.exec()
        callback(d.allowed)

    # -- find / fullscreen ------------------------------------------------------------
    def _toggle_fullscreen(self, on: Optional[bool] = None) -> None:
        if on is None:
            on = not self.isFullScreen()
        if on:
            self.showFullScreen()
        else:
            self.showNormal()

    def _reader_mode(self) -> None:
        t = self.current_tab()
        if t:
            t.enter_reader_mode(dark=self._is_dark())

    def _is_dark(self) -> bool:
        from .style import system_is_dark
        theme = self.settings.get("appearance.theme", "system")
        return True if theme == "dark" else (False if theme == "light" else system_is_dark())

    # -- page operations ------------------------------------------------------------
    def _open_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Open file")
        if path:
            self._navigate(QUrl.fromLocalFile(path).toString())

    def _save_page(self) -> None:
        t = self.current_tab()
        if not t:
            return
        name = (t.page.title() or "page").replace("/", "_")[:60]
        path, _ = QFileDialog.getSaveFileName(self, "Save page", f"{name}.mhtml",
                                              "Web page (*.mhtml *.html)")
        if path:
            t.save_page(path, complete=not path.endswith(".html"))
            self._on_status(f"Saved page to {path}")

    def _print(self) -> None:
        t = self.current_tab()
        if not t:
            return
        path, _ = QFileDialog.getSaveFileName(self, "Print to PDF", "page.pdf", "PDF (*.pdf)")
        if path:
            t.print_to_pdf(path)
            self._on_status(f"Printed to {path}")

    def _print_pdf(self) -> None:
        self._print()

    def _screenshot(self) -> None:
        t = self.current_tab()
        if not t:
            return
        path, _ = QFileDialog.getSaveFileName(self, "Screenshot", "screenshot.png", "PNG (*.png)")
        if path and t.screenshot(path):
            self._on_status(f"Screenshot saved to {path}")

    def _view_source(self) -> None:
        t = self.current_tab()
        if t and t.url_string.startswith(("http", "https")):
            self.new_tab("view-source:" + t.url_string)

    def _translate(self) -> None:
        t = self.current_tab()
        if t and t.url_string.startswith("http"):
            u = quote_plus(t.url_string)
            self.new_tab(f"https://translate.google.com/translate?sl=auto&u={u}")

    def _show_qr(self) -> None:
        t = self.current_tab()
        if not t or not t.url_string:
            return
        from ..core.qr import encode as qr_encode, to_svg
        svg = to_svg(qr_encode(t.url_string))
        import base64
        data = base64.b64encode(svg.encode()).decode()
        box = QDialog(self)
        box.setWindowTitle("QR code for this page")
        lay = QVBoxLayout(box)
        lbl = QLabel()
        pm = QPixmap()
        pm.loadFromData(svg.encode(), "image/svg+xml")
        lbl.setPixmap(pm.scaled(280, 280, Qt.AspectRatioMode.KeepAspectRatio,
                                Qt.TransformationMode.SmoothTransformation))
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(lbl)
        lay.addWidget(QLabel(t.url_string))
        box.setMinimumWidth(320)
        box.exec()

    def _tab_search(self) -> None:
        d = dlg.TabSearchDialog(self.tabs, self)
        if d.exec() and d.chosen is not None and 0 <= d.chosen < len(self.tabs):
            self.tabwidget.setCurrentIndex(d.chosen)

    def _open_devtools(self) -> None:
        t = self.current_tab()
        if not t:
            return
        if getattr(self, "_devtools_win", None) is None:
            self._devtools_win = DevToolsWindow(self)
        self._devtools_win.attach(t)
        self._devtools_win.show()
        self._devtools_win.raise_()

    def _inspect(self) -> None:
        t = self.current_tab()
        if t:
            t.page.triggerAction(QWebEnginePage.WebAction.InspectElement)
            self._open_devtools()

    # -- settings / data ---------------------------------------------------------------
    def open_settings(self) -> None:
        if getattr(self, "_settings_dlg", None) is None:
            self._settings_dlg = dlg.SettingsDialog(self.services, self)
            self._settings_dlg.theme_changed.connect(self._apply_theme)
            self._settings_dlg.setWindowFlag(Qt.WindowType.Window, True)
        self._settings_dlg.show()
        self._settings_dlg.raise_()

    def open_clear_data(self) -> None:
        d = dlg.ClearDataDialog(self.settings, self.store,
                                [self.app_state.profile, self.app_state.private_profile], self)
        d.exec()
        self._rebuild_bookmarks_bar()

    def _open_clear_data(self) -> None:
        self.open_clear_data()

    _profiles_vault = None

    def _import_export_dispatch(self, kind: str) -> None:
        if kind == "bookmarks_export":
            self._export_bookmarks()
        elif kind == "bookmarks_import":
            self._import_bookmarks()
        elif kind == "passwords_export":
            self._export_passwords()
        elif kind == "passwords_import":
            self._import_passwords()
        elif kind == "extension_install":
            self._install_extension()

    def _export_bookmarks(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "Export bookmarks", "bookmarks.html",
                                              "HTML (*.html)")
        if path:
            n = export_bookmarks_html(self.store, path)
            self._on_status(f"Exported {n} bookmarks")

    def _import_bookmarks(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Import bookmarks", "",
                                              "HTML (*.html *.htm)")
        if path:
            n = import_bookmarks_html(self.store, path)
            self._rebuild_bookmarks_bar()
            self._on_status(f"Imported {n} bookmarks")

    def _export_passwords(self) -> None:
        if not self.app_state.vault.is_unlocked():
            self._request_unlock()
            if not self.app_state.vault.is_unlocked():
                return
        if QMessageBox.warning(
                self, APP_NAME,
                "Export passwords to PLAINTEXT CSV?\nAnyone with this file can read every password.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No) \
                != QMessageBox.StandardButton.Yes:
            return
        path, _ = QFileDialog.getSaveFileName(self, "Export passwords", "passwords.csv",
                                              "CSV (*.csv)")
        if path:
            n = self.app_state.vault.export_csv(Path(path))
            self._on_status(f"Exported {n} passwords (plaintext!)")

    def _import_passwords(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Import passwords", "", "CSV (*.csv)")
        if path:
            n = self.app_state.vault.import_csv(Path(path))
            self._on_status(f"Imported {n} logins")

    def _install_extension(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Extension folder")
        if not folder:
            return
        try:
            ext = self.app_state.extensions.install(Path(folder))
            perms = ext.permissions
            if perms:
                if QMessageBox.question(
                        self, APP_NAME,
                        f"Extension “{ext.name}” requests permissions: {', '.join(perms)}.\n"
                        "Approve these sensitive permissions?") \
                        != QMessageBox.StandardButton.Yes:
                    self.app_state.extensions.remove(ext.id)
                    return
            if ext.wants_private():
                if QMessageBox.question(self, APP_NAME,
                                        f"Allow “{ext.name}” to run in private windows?") \
                        == QMessageBox.StandardButton.Yes:
                    self.app_state.extensions.set_allowed_in_private(ext.id, True)
            self._on_status(f"Installed extension {ext.name}")
        except (ValueError, json.JSONDecodeError) as exc:
            QMessageBox.warning(self, APP_NAME, f"Install failed: {exc}")

    def _check_updates(self) -> None:
        self.app_state.check_updates(self)

    # -- layout modes -----------------------------------------------------------------
    def _apply_layout_mode(self) -> None:
        vertical = self.settings.get("appearance.vertical_tabs")
        self.tabwidget.setTabPosition(
            QTabWidget.TabPosition.West if vertical else QTabWidget.TabPosition.North)
        self.tabbar.setObjectName("TabBarWest" if vertical else "TabBar")
        self.tabbar.setOrientation(
            Qt.Orientation.Vertical if vertical else Qt.Orientation.Horizontal)

    def _toggle_vertical_tabs(self, on: bool) -> None:
        self.settings.set("appearance.vertical_tabs", on)
        self._apply_layout_mode()

    def _toggle_bookmarks_bar(self, on: bool) -> None:
        self.bookmarks_bar.setVisible(on)
        self.settings.set("appearance.show_bookmarks_bar", on)

    # -- theme -------------------------------------------------------------------------
    def _apply_theme(self) -> None:
        from .style import build_qss
        qss = build_qss(self.settings.get("appearance.theme", "system"),
                        self.settings.get("appearance.accent", "#4f8cff"),
                        int(self.settings.get("appearance.font_size", 14)),
                        bool(self.settings.get("a11y.high_contrast")),
                        bool(self.settings.get("appearance.reduced_motion")))
        QApplication.instance().setStyleSheet(qss)

    # -- session -------------------------------------------------------------------------
    def _connect_session_autosave(self) -> None:
        self._session_timer = QTimer(self)
        self._session_timer.setSingleShot(True)
        self._session_timer.setInterval(3000)
        self._session_timer.timeout.connect(self._save_session_now)
        self.settings.observe(self._settings_observed)

    def _settings_observed(self, key, _value) -> None:
        if key in ("appearance.theme", "appearance.accent", "appearance.font_size",
                   "a11y.high_contrast", "appearance.reduced_motion"):
            self._apply_theme()
        if key == "appearance.vertical_tabs":
            self._apply_layout_mode()

    def _mark_session_dirty(self) -> None:
        self._session_dirty = True
        self._session_timer.start()

    def session_snapshot(self) -> List[List[dict]]:
        return snapshot([[{
            "url": t.url_string, "pinned": t.pinned, "group": t.group_name,
            "muted": t.muted, "private": t.is_private,
            "zoom": t.page.zoomFactor(),
        } for t in self.tabs if not t.is_private]])

    def _save_session_now(self) -> None:
        if not self._session_dirty:
            return
        self._session_dirty = False
        wins = [w.session_snapshot() for w in self.app_state.windows() if not w.private]
        save_session(self.settings, [w for w in wins if w])

    # -- privacy counters badge ------------------------------------------------------------
    def refresh_shield(self) -> None:
        trackers, cookies, ads, requests_, _sites = self.app_state.counters.snapshot()
        self.shield_btn.setText(f"🛡 {trackers + cookies + ads + requests_}")
        self.shield_btn.setToolTip(
            f"Privacy dashboard — {trackers} trackers, {cookies} cookies, "
            f"{requests_} requests blocked this session")

    # ------------------------------------------------------------------ #
    def closeEvent(self, event) -> None:
        multi = len(self.tabs) > 1
        if (multi and self.settings.get("general.ask_on_close_multiple_tabs")
                and not self.private):
            ret = QMessageBox.question(
                self, APP_NAME,
                f"Close {len(self.tabs)} tabs?",
                QMessageBox.StandardButton.Close | QMessageBox.StandardButton.Cancel)
            if ret != QMessageBox.StandardButton.Close:
                event.ignore()
                return
        self._save_session_now()
        for t in self.tabs:
            t.shutdown()
        self.tabs.clear()
        if self.private and self.app_state.private_window_count() <= 1:
            # Last private window closing: wipe the off-the-record profile.
            self.app_state.destroy_private_profile(self.profile)
        event.accept()


class DevToolsWindow(QDialog):
    """Floating DevTools window attached to a WebTab's page."""

    def __init__(self, parent: BrowserWindow):
        super().__init__(parent)
        self.setWindowTitle(f"{APP_NAME} — developer tools")
        self.resize(1000, 600)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        from PyQt6.QtWebEngineWidgets import QWebEngineView
        self.view = QWebEngineView()
        self.view.setPage(QWebEnginePage(parent.profile, self.view))
        lay.addWidget(self.view)
        self._attached: Optional[WebTab] = None

    def attach(self, tab: WebTab) -> None:
        if self._attached is tab and self.view.page().devToolsId():
            return
        self._attached = tab
        tab.page.setDevToolsPage(self.view.page())
