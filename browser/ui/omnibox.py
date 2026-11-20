"""Omnibox — address bar with unified suggestions.

Sources (in priority order):
  1. direct URL / search classification
  2. open tabs (switch to tab)
  3. bookmarks
  4. history
  5. search engine suggestions (only when enabled in settings; requests go
     only to the user's chosen engine)

Security: the security indicator shows HTTPS state; insecure password
fields on http pages get an explicit warning icon.
"""

from __future__ import annotations

from typing import List, Optional

from PyQt6.QtCore import (QAbstractListModel, QModelIndex, Qt,
                          QUrl, pyqtSignal, QTimer, pyqtSlot)
from PyQt6.QtGui import QFont, QPainter, QPalette
from PyQt6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest
from PyQt6.QtWidgets import (QLineEdit, QListView, QStyledItemDelegate,
                             QVBoxLayout, QWidget)
from PyQt6.QtWidgets import QStyle, QStyleOptionViewItem

from ..core.search import normalize_input, parse_suggestions_osjson, BUILTIN_ENGINES

ROLE_KIND = Qt.ItemDataRole.UserRole + 1
ROLE_SUB = Qt.ItemDataRole.UserRole + 2


class SuggestionModel(QAbstractListModel):
    """List model backing omnibox suggestions."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.items: List[dict] = []

    def set_items(self, items: List[dict]) -> None:
        self.beginResetModel()
        self.items = items
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self.items)

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or not (0 <= index.row() < len(self.items)):
            return None
        it = self.items[index.row()]
        if role == Qt.ItemDataRole.DisplayRole:
            return it.get("title", "")
        if role == ROLE_KIND:
            return it.get("kind", "")
        if role == ROLE_SUB:
            return it.get("sub", "")
        if role == Qt.ItemDataRole.ToolTipRole:
            return it.get("url", "")
        return None


class SuggestionDelegate(QStyledItemDelegate):
    """Two-line styled rendering of suggestion rows."""
    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex):
        painter.save()
        r = option.rect.adjusted(8, 2, -8, -2)
        if option.state & QStyle.StateFlag.State_Selected:
            painter.setOpacity(0.9)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(option.palette.highlight())
            painter.drawRoundedRect(option.rect.adjusted(4, 1, -4, -1), 6, 6)
            painter.setOpacity(1.0)
        kind = index.data(ROLE_KIND) or ""
        icons = {"url": "🌐", "tab": "🗗", "bookmark": "⭐", "history": "🕘",
                 "search": "🔍", "engine": "🔍"}
        icon = icons.get(kind, "•")
        painter.setPen(option.palette.color(QPalette.ColorRole.Text))
        f = QFont(option.font)
        f.setBold(kind in ("url", "search"))
        painter.setFont(f)
        painter.drawText(r.adjusted(0, 0, -8, 0), Qt.AlignmentFlag.AlignVCenter,
                         f"{icon}  {index.data() or ''}")
        sub = index.data(ROLE_SUB) or ""
        if sub:
            f2 = QFont(option.font)
            f2.setPointSizeF(f2.pointSizeF() * 0.85)
            painter.setFont(f2)
            painter.setPen(option.palette.color(QPalette.ColorRole.PlaceholderText))
            painter.drawText(r, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight, sub)
        painter.restore()

    def sizeHint(self, option, index):
        from PyQt6.QtCore import QSize
        return QSize(option.rect.width(), 34)


class Omnibox(QLineEdit):
    """Address bar: URL detection, suggestions, keyboard handling."""
    navigate_requested = pyqtSignal(str)      # final url to load
    open_in_new_tab = pyqtSignal(str, bool)   # url, background
    cleared_data_shortcut = pyqtSignal()

    def __init__(self, services, parent=None):
        super().__init__(parent)
        self.services = services
        self.setObjectName("Omnibox")
        self.setPlaceholderText("Search or enter address")
        self.setClearButtonEnabled(True)
        self._current_tab = None

        self.popup = QListView()
        self.popup.setObjectName("Suggestions")
        self.popup.setEditTriggers(QListView.EditTrigger.NoEditTriggers)
        self.popup.setUniformItemSizes(False)
        self.popup.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.model_ = SuggestionModel(self)
        self.popup.setModel(self.model_)
        self.popup.setItemDelegate(SuggestionDelegate(self.popup))

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(150)
        self._timer.timeout.connect(self._refresh_suggestions)

        self._nam = QNetworkAccessManager(self)
        self._suggest_reply: Optional[QNetworkReply] = None

        self.textEdited.connect(self._on_edited)
        self.returnPressed.connect(self._on_return)
        self.popup.clicked.connect(self._on_clicked)
        self.cursorPositionChanged.connect(self._update_elide)

    # -- tab binding ---------------------------------------------------------
    def set_tab(self, tab) -> None:
        self._current_tab = tab
        if tab is None:
            self.clear()
        else:
            self.setText(tab.url_string)
            self.setCursorPosition(0)

    def _update_elide(self) -> None:
        # Keep the caret at the start for long URLs so the scheme is visible.
        if self.cursorPosition() == len(self.text()) and self.text().startswith("http"):
            pass

    # -- events -----------------------------------------------------------------
    def keyPressEvent(self, ev) -> None:
        key = ev.key()
        visible = self.popup.isVisible()
        if visible and key in (Qt.Key.Key_Down, Qt.Key.Key_Up):
            row = self.popup.currentIndex().row() if self.popup.currentIndex().isValid() else -1
            n = self.model_.rowCount()
            if key == Qt.Key.Key_Down:
                row = min(row + 1, n - 1)
            else:
                row = max(row - 1, -1)
            self.popup.setCurrentIndex(self.model_.index(max(row, 0), 0))
            return
        if key == Qt.Key.Key_Escape and visible:
            self._hide_popup()
            return
        if ev.modifiers() & Qt.KeyboardModifier.ControlModifier:
            if key == Qt.Key.Key_Return or key == Qt.Key.Key_Enter:
                idx = self.popup.currentIndex().row() if visible else -1
                if 0 <= idx < self.model_.rowCount():
                    it = self.model_.items[idx]
                    self.open_in_new_tab.emit(it["url"], ev.modifiers() &
                                              Qt.KeyboardModifier.ShiftModifier)
                    self._hide_popup()
                    return
        super().keyPressEvent(ev)

    def focusInEvent(self, ev) -> None:
        super().focusInEvent(ev)
        self.selectAll()

    # -- suggestions ----------------------------------------------------------
    def _on_edited(self, _text: str) -> None:
        self._timer.start()

    def _hide_popup(self) -> None:
        self.popup.hide()

    def _show_popup(self) -> None:
        if self.model_.rowCount() == 0:
            self._hide_popup()
            return
        self.popup.resize(self.width(), min(
            420, self.model_.rowCount() * 36 + 8))
        p = self.mapTo(self.window(), self.rect().bottomLeft())
        self.popup.move(self.window().mapToGlobal(p))
        self.popup.show()
        self.popup.raise_()

    def _refresh_suggestions(self) -> None:
        text = self.text().strip()
        engine_name = self.services.settings.get("search.default_engine", "DuckDuckGo")
        engine = BUILTIN_ENGINES.get(engine_name)
        for ce in self.services.settings.get("search.custom_engines", []):
            if ce.get("name") == engine_name:
                from ..core.search import SearchEngine
                engine = SearchEngine(ce["name"], ce["url"], ce.get("suggest_url", ""))
        engine = engine or BUILTIN_ENGINES["DuckDuckGo"]
        items: List[dict] = []
        if not text:
            self.model_.set_items(items)
            self._show_popup()
            return
        url, kind = normalize_input(text, engine)
        items.append({"title": url, "kind": "url" if kind != "search" else "search",
                      "sub": "Enter" if kind != "search" else f"Search {engine.name}",
                      "url": url})
        # open tabs
        low = text.lower()
        seen_urls = {url}
        try:
            for tab in self.services.open_tabs():
                u = tab.url_string
                if low in u.lower() or low in tab.page.title().lower():
                    if u not in seen_urls:
                        seen_urls.add(u)
                        items.append({"title": tab.page.title() or u, "kind": "tab",
                                      "sub": "Switch to tab", "url": u})
        except Exception:
            pass
        # bookmarks
        store = self.services.store
        for bm in store.walk():
            if (bm["url"] and low in bm["url"].lower()) or low in bm["title"].lower():
                if bm["url"] not in seen_urls:
                    seen_urls.add(bm["url"])
                    items.append({"title": bm["title"], "kind": "bookmark",
                                  "sub": "Bookmark", "url": bm["url"]})
        # history
        for r in store.search_history(text, 6):
            if r["url"] not in seen_urls:
                seen_urls.add(r["url"])
                items.append({"title": r["title"] or r["url"], "kind": "history",
                              "sub": "History", "url": r["url"]})
        items = items[:9]
        self.model_.set_items(items)
        self._show_popup()
        if (self.services.settings.get("search.show_suggestions", True)
                and self.services.settings.get("privacy.suggestions_in_omnibox", True)
                and kind == "search" and len(text) >= 3 and engine.suggestions(text)):
            self._fetch_engine_suggestions(text, engine, items)

    def _fetch_engine_suggestions(self, text: str, engine, base_items) -> None:
        if self._suggest_reply is not None:
            try:
                self._suggest_reply.abort()
            except RuntimeError:
                pass
            self._suggest_reply = None
        req = QNetworkRequest(QUrl(engine.suggestions(text)))
        req.setAttribute(QNetworkRequest.Attribute.RedirectPolicyAttribute,
                         QNetworkRequest.RedirectPolicy.NoLessSafeRedirectPolicy)
        reply = self._nam.get(req)
        self._suggest_reply = reply

        def done():
            self._suggest_reply = None
            data = bytes(reply.readAll())
            reply.deleteLater()
            sugg = parse_suggestions_osjson(data)
            if sugg and self.text().strip() == text:
                items = list(base_items)
                for s_ in sugg:
                    u = engine.search(s_)
                    items.append({"title": s_, "kind": "search",
                                  "sub": engine.name, "url": u})
                self.model_.set_items(items[:9])

        reply.finished.connect(done)

    # -- actions ----------------------------------------------------------------
    def _on_return(self) -> None:
        idx = self.popup.currentIndex().row() if self.popup.isVisible() else -1
        if 0 <= idx < self.model_.rowCount():
            it = self.model_.items[idx]
            self._hide_popup()
            self.navigate_requested.emit(it["url"])
            return
        text = self.text().strip()
        self._hide_popup()
        if text:
            self.navigate_requested.emit(text)

    def _on_clicked(self, index: QModelIndex) -> None:
        if index.isValid():
            it = self.model_.items[index.row()]
            self._hide_popup()
            self.navigate_requested.emit(it["url"])
