"""Native dialogs for browser: permission prompts, password dialogs,
downloads warnings, tab search, settings center, clear-data."""

from __future__ import annotations

import json
import time
from typing import List, Optional

from PyQt6.QtCore import Qt, QUrl, pyqtSignal
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout,
    QFrame, QHBoxLayout, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QMessageBox, QPushButton, QScrollArea,
    QSpinBox, QStackedWidget, QTableWidget, QTableWidgetItem, QVBoxLayout,
    QWidget, QDoubleSpinBox, )

from .. import paths
from ..constants import APP_NAME, APP_VERSION, URL_TOR
from ..core.permissions import FEATURES, MANAGEABLE, SENSITIVE
from ..core.search import BUILTIN_ENGINES
from ..core.vault import strength


def _hbox(*widgets, stretch=()) -> QHBoxLayout:
    lay = QHBoxLayout()
    lay.setSpacing(8)
    for i, w in enumerate(widgets):
        lay.addWidget(w, stretch[i] if i < len(stretch) else 0)
    return lay


class PermissionPromptDialog(QDialog):
    """Ask the user about a website permission."""

    def __init__(self, origin: str, feature: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"{APP_NAME} — permission request")
        self.setModal(True)
        self.setMinimumWidth(420)
        self.result_action = "block"   # allow | block
        self.remember = False

        label = FEATURES.get(feature, feature)
        icon = {"camera": "📷", "microphone": "🎤", "location": "📍",
                "notifications": "🔔", "clipboard_read": "📋",
                "desktop_video_capture": "🖥", "bluetooth": "🅱", "usb": "🔌"}.get(feature, "❔")
        body = QLabel(f"<div style='font-size:26px'>{icon}</div>"
                      f"<h3 style='margin:6px 0'>Allow <b>{origin}</b> to use {label.lower()}?</h3>"
                      f"<p style='color:#9aa2b1'>You can change this later in "
                      f"Settings → Permissions.</p>")
        body.setWordWrap(True)
        self.allow_btn = QPushButton("Allow")
        self.allow_btn.setDefault(True)
        self.block_btn = QPushButton("Block")
        self.remember_cb = QCheckBox("Remember this decision for this site")
        self.allow_btn.clicked.connect(lambda: self._done("allow"))
        self.block_btn.clicked.connect(lambda: self._done("block"))
        lay = QVBoxLayout(self)
        lay.addWidget(body)
        lay.addWidget(self.remember_cb)
        lay.addLayout(_hbox(self.block_btn, self.allow_btn, stretch=(1, 0)))

    def _done(self, action: str) -> None:
        self.result_action = action
        self.remember = self.remember_cb.isChecked()
        self.accept()


class SavePasswordDialog(QDialog):
    """Prompt shown when a login form is detected on a page."""
    def __init__(self, origin: str, username: str, password: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"{APP_NAME} — save password")
        self.setModal(True)
        self.save = False
        self.username_edit = QLineEdit(username)
        self.password_edit = QLineEdit(password)
        self.password_edit.setEchoMode(QLineEdit.EchoMode.Password)
        s = strength(password)
        label = ("very weak", "weak", "fair", "strong", "very strong")[s]
        note = QLabel(f"Strength: {label}")
        note.setStyleSheet("color:#9aa2b1")
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel(
            f"<b>{origin}</b><br>Do you want browser to save this login? "
            "It will be encrypted on this device only."))
        form = QFormLayout()
        form.addRow("Username", self.username_edit)
        form.addRow("Password", self.password_edit)
        lay.addLayout(form)
        lay.addWidget(note)
        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Save |
                                QDialogButtonBox.StandardButton.Discard)
        btns.accepted.connect(self._save)
        btns.rejected.connect(self.reject)
        lay.addWidget(btns)

    def _save(self) -> None:
        self.save = True
        self.accept()

    @property
    def final_username(self) -> str:
        return self.username_edit.text()

    @property
    def final_password(self) -> str:
        return self.password_edit.text()


class MasterPasswordDialog(QDialog):
    """Unlock the vault, or set / change / remove the master password."""

    def __init__(self, mode: str, parent=None):
        # mode: unlock | set | change
        super().__init__(parent)
        self.mode = mode
        self.ok = False
        self.value = ""
        self.setWindowTitle({ "unlock": "Unlock vault", "set": "Set master password",
                              "change": "Change master password" }[mode])
        self.setModal(True)
        self.setMinimumWidth(380)
        lay = QVBoxLayout(self)
        if mode == "unlock":
            lay.addWidget(QLabel("Enter your master password to unlock saved passwords."))
            self.edit = QLineEdit()
            self.edit.setEchoMode(QLineEdit.EchoMode.Password)
            lay.addWidget(self.edit)
        elif mode == "set":
            lay.addWidget(QLabel(
                "A master password re-encrypts all saved passwords under a key "
                "derived from it (PBKDF2, 600k rounds). If you forget it, saved "
                "passwords cannot be recovered."))
            self.edit = QLineEdit()
            self.edit.setEchoMode(QLineEdit.EchoMode.Password)
            self.edit.setPlaceholderText("New master password")
            self.edit2 = QLineEdit()
            self.edit2.setEchoMode(QLineEdit.EchoMode.Password)
            self.edit2.setPlaceholderText("Repeat")
            lay.addWidget(self.edit)
            lay.addWidget(self.edit2)
        else:
            self.old_edit = QLineEdit()
            self.old_edit.setEchoMode(QLineEdit.EchoMode.Password)
            self.old_edit.setPlaceholderText("Current master password")
            self.edit = QLineEdit()
            self.edit.setEchoMode(QLineEdit.EchoMode.Password)
            self.edit.setPlaceholderText("New master password (empty to disable)")
            self.edit2 = QLineEdit()
            self.edit2.setEchoMode(QLineEdit.EchoMode.Password)
            self.edit2.setPlaceholderText("Repeat new")
            lay.addWidget(self.old_edit)
            lay.addWidget(self.edit)
            lay.addWidget(self.edit2)
        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok |
                                QDialogButtonBox.StandardButton.Cancel)
        btns.accepted.connect(self._ok)
        btns.rejected.connect(self.reject)
        lay.addWidget(btns)

    def _ok(self) -> None:
        if self.mode == "unlock":
            self.value = self.edit.text()
            self.ok = True
        elif self.mode == "set":
            if self.edit.text() != self.edit2.text():
                QMessageBox.warning(self, APP_NAME, "Passwords do not match.")
                return
            self.value = self.edit.text()
            self.ok = True
        else:
            self.value = (self.old_edit.text(), self.edit.text())
            self.ok = True
        self.accept()


class DangerDownloadDialog(QDialog):
    """Warning dialog for executables/risky downloads."""
    def __init__(self, filename: str, danger: str, note: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"{APP_NAME} — download warning")
        self.setModal(True)
        self.allowed = False
        lay = QVBoxLayout(self)
        head = QLabel(f"<div style='font-size:30px'>⚠</div>"
                      f"<h3 style='margin:6px 0'>This file may harm your computer</h3>")
        lay.addWidget(head)
        lay.addWidget(QLabel(f"<b>{filename}</b><br><br>{danger}"))
        if note:
            n = QLabel(note)
            n.setWordWrap(True)
            n.setStyleSheet("color:#ffb84f")
            lay.addWidget(n)
        lay.addWidget(QLabel(
            "browser never runs downloads automatically. If you did not expect "
            "this file, cancel the download."))
        save_btn = QPushButton("Keep (save anyway)")
        cancel_btn = QPushButton("Cancel download")
        cancel_btn.setDefault(True)
        save_btn.clicked.connect(self._allow)
        cancel_btn.clicked.connect(self.reject)
        lay.addLayout(_hbox(cancel_btn, save_btn, stretch=(1, 0)))

    def _allow(self) -> None:
        self.allowed = True
        self.accept()


class TabSearchDialog(QDialog):
    """Fuzzy-search dialog across open tabs."""
    def __init__(self, tabs, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Search tabs")
        self.setModal(True)
        self.resize(520, 380)
        self.chosen: Optional[int] = None
        self._tabs = list(tabs)
        lay = QVBoxLayout(self)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Type to filter open tabs…")
        self.listw = QListWidget()
        lay.addWidget(self.search)
        lay.addWidget(self.listw)
        self.search.textChanged.connect(self._filter)
        self.listw.itemDoubleClicked.connect(self._pick)
        self.search.returnPressed.connect(self._enter)
        self._filter("")

    def _filter(self, q: str) -> None:
        self.listw.clear()
        for i, tab in enumerate(self._tabs):
            if tab is None:
                continue
            hay = f"{tab.page.title()} {tab.url_string}".lower()
            if q.lower() in hay:
                item = QListWidgetItem(f"{tab.page.title() or 'New tab'}\n   {tab.url_string}")
                item.setData(Qt.ItemDataRole.UserRole, i)
                self.listw.addItem(item)
        if self.listw.count():
            self.listw.setCurrentRow(0)

    def _enter(self) -> None:
        it = self.listw.currentItem()
        if it:
            self._pick(it)

    def _pick(self, item) -> None:
        self.chosen = item.data(Qt.ItemDataRole.UserRole)
        self.accept()


class ClearDataDialog(QDialog):
    """Clear browsing data with time-range selection."""

    def __init__(self, settings, store, profiles, vault=None, counters=None,
                 parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"{APP_NAME} — clear browsing data")
        self.setModal(True)
        self.settings = settings
        self.store = store
        self.profiles = profiles   # list of QWebEngineProfile
        self.vault = vault
        self.counters = counters
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel("Choose what to clear:"))
        self.cb_history = QCheckBox("Browsing history")
        self.cb_cookies = QCheckBox("Cookies and site data")
        self.cb_cache = QCheckBox("Cached files")
        self.cb_downloads = QCheckBox("Download records (files are kept)")
        self.cb_passwords = QCheckBox("Saved passwords (cannot be undone)")
        for cb in (self.cb_history, self.cb_cookies, self.cb_cache, self.cb_downloads):
            cb.setChecked(True)
        lay.addWidget(self.cb_history)
        lay.addWidget(self.cb_cookies)
        lay.addWidget(self.cb_cache)
        lay.addWidget(self.cb_downloads)
        lay.addWidget(self.cb_passwords)
        row = QHBoxLayout()
        row.addWidget(QLabel("Time range:"))
        self.range_cb = QComboBox()
        self.range_cb.addItems(["Last hour", "Last day", "Last week", "All time"])
        row.addWidget(self.range_cb)
        row.addStretch(1)
        lay.addLayout(row)
        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok |
                                QDialogButtonBox.StandardButton.Cancel)
        btns.button(QDialogButtonBox.StandardButton.Ok).setText("Clear data")
        btns.accepted.connect(self._clear)
        btns.rejected.connect(self.reject)
        lay.addWidget(btns)

    def _clear(self) -> None:
        ranges = [3600, 86400, 7 * 86400, 0]
        seconds = ranges[self.range_cb.currentIndex()]
        cutoff_all = seconds == 0
        start = time.time() - seconds if not cutoff_all else 0
        end = time.time() + 60
        if self.cb_history.isChecked():
            if cutoff_all:
                self.store.clear_history()
            else:
                self.store.delete_history_range(start, end)
        if self.cb_downloads.isChecked():
            self.store.clear_downloads()
        if self.cb_passwords.isChecked():
            if self.vault is not None:
                try:
                    self.vault.clear_all()
                except Exception:
                    pass    # locked vault: nothing readable to clear
        if self.cb_cookies.isChecked() or self.cb_cache.isChecked():
            for prof in self.profiles:
                if prof.cookieStore() and not prof.isOffTheRecord():
                    if self.cb_cookies.isChecked():
                        prof.cookieStore().deleteAllCookies()
                    prof.cookieStore().deleteSessionCookies()
                if self.cb_cache.isChecked():
                    prof.clearHttpCache()
        if self.counters is not None:
            self.counters.reset()
        self.settings.set("internal.stats", {"trackers_blocked": 0,
                                             "cookies_blocked": 0,
                                             "ads_blocked": 0,
                                             "requests_blocked": 0}, save=False)
        self.settings.set("internal.stats_by_site", {}, save=False)
        self.settings.save()
        self.accept()


# --------------------------------------------------------------------------- #
# Settings center
# --------------------------------------------------------------------------- #
class SettingsDialog(QDialog):
    """Settings organized into the 15 required sections."""

    theme_changed = pyqtSignal()

    def __init__(self, services, parent=None):
        super().__init__(parent)
        self.s = services
        self.settings = services.settings
        self.setWindowTitle(f"{APP_NAME} — settings")
        self.resize(900, 620)
        self.setModal(False)

        lay = QHBoxLayout(self)
        self.nav = QListWidget()
        self.nav.setObjectName("SettingsNav")
        self.stack = QStackedWidget()
        lay.addWidget(self.nav, 0)
        lay.addWidget(self.stack, 1)

        sections = [
            ("general", "⚙", "General"), ("appearance", "🎨", "Appearance"),
            ("privacy", "🛡", "Privacy"), ("security", "🔐", "Security"),
            ("search", "🔍", "Search"), ("tabs", "🗂", "Tabs"),
            ("downloads", "⬇", "Downloads"), ("passwords", "🔑", "Passwords"),
            ("bookmarks", "⭐", "Bookmarks"), ("history", "🕘", "History"),
            ("permissions", "✋", "Permissions"), ("extensions", "🧩", "Extensions"),
            ("accessibility", "♿", "Accessibility"), ("advanced", "🧪", "Advanced"),
            ("about", "ℹ", "About browser"),
        ]
        for key, icon, label in sections:
            item = QListWidgetItem(f"{icon}  {label}")
            item.setData(Qt.ItemDataRole.UserRole, key)
            self.nav.addItem(item)
            self.stack.addWidget(self._build(key, label))
        self.nav.currentRowChanged.connect(self.stack.setCurrentIndex)
        self.nav.setCurrentRow(0)

        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        btns.rejected.connect(self.close)
        btns.clicked.connect(self.close)
        outer = QVBoxLayout()
        outer.addLayout(lay, 1)
        outer.addWidget(btns)
        self.setLayout(outer)

    # helpers ---------------------------------------------------------------
    def _page(self) -> tuple[QWidget, QVBoxLayout]:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setSpacing(8)
        lay.setContentsMargins(24, 24, 24, 24)
        return page, lay

    def _title(self, lay, text: str) -> None:
        t = QLabel(text)
        t.setObjectName("SettingsH1")
        lay.addWidget(t)

    def _section(self, lay, text: str) -> None:
        s = QLabel(text)
        s.setObjectName("SectionLabel")
        lay.addWidget(s)

    def _check(self, key: str, label: str, tooltip: str = "") -> QCheckBox:
        cb = QCheckBox(label)
        cb.setChecked(bool(self.settings.get(key)))
        if tooltip:
            cb.setToolTip(tooltip)
        def toggled(v: bool) -> None:
            self.settings.set(key, v)
        cb.toggled.connect(toggled)
        return cb

    def _combo(self, key: str, options: List[tuple], label: str = "") -> QWidget:
        box = QWidget()
        row = QHBoxLayout(box)
        row.setContentsMargins(0, 0, 0, 0)
        if label:
            row.addWidget(QLabel(label))
        cb = QComboBox()
        values = [v for v, _ in options]
        labels = [t for _, t in options]
        cb.addItems(labels)
        current = self.settings.get(key)
        if current in values:
            cb.setCurrentIndex(values.index(current))
        def changed(i: int) -> None:
            self.settings.set(key, values[i])
        cb.currentIndexChanged.connect(changed)
        row.addWidget(cb)
        row.addStretch(1)
        return box

    def _build(self, key: str, label: str) -> QWidget:
        builder = getattr(self, f"_page_{key}", None)
        page, lay = self._page()
        if builder:
            builder(lay)
        else:
            self._title(lay, label)
        lay.addStretch(1)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(page)
        return scroll

    # -- 1 General -----------------------------------------------------------
    def _page_general(self, lay) -> None:
        self._title(lay, "General")
        self._section(lay, "Startup")
        lay.addWidget(self._combo(
            "general.startup_page",
            [("home", "Open the home page"), ("restore", "Restore previous session"),
             ("blank", "Open a blank page")], "On startup:"))
        self._section(lay, "New tab")
        lay.addWidget(self._combo("general.new_tab_page",
                                  [("home", "browser home"), ("blank", "Blank page")]))
        cb = QCheckBox("Ask before closing a window with multiple tabs")
        cb.setChecked(bool(self.settings.get("general.ask_on_close_multiple_tabs")))
        cb.toggled.connect(lambda v: self.settings.set("general.ask_on_close_multiple_tabs", v))
        lay.addWidget(cb)
        self._section(lay, "Default browser")
        default_btn = QPushButton("Check — set browser as your default")
        default_btn.setToolTip("Opens the OS default-apps panel (browser registers itself).")
        default_btn.clicked.connect(self._open_default_apps)
        lay.addWidget(default_btn)
        self._section(lay, "Data")
        row = QHBoxLayout()
        imp = QPushButton("Import settings…")
        exp = QPushButton("Export settings…")
        reset = QPushButton("Reset all settings")
        imp.clicked.connect(self._import_settings)
        exp.clicked.connect(self._export_settings)
        reset.clicked.connect(self._reset_settings)
        row.addWidget(imp); row.addWidget(exp); row.addWidget(reset); row.addStretch(1)
        lay.addLayout(row)
        p = QLabel(f"Data location: <code>{paths.data_dir()}</code> — all data stays on this device.")
        p.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        lay.addWidget(p)

    def _open_default_apps(self) -> None:
        import subprocess, sys
        try:
            if sys.platform == "win32":
                subprocess.Popen(["control", "/name", "Microsoft.DefaultPrograms"])
            elif sys.platform == "darwin":
                subprocess.Popen(["open", "x-apple.systempreferences:com.apple.preferences.extensions"])
            else:
                QDesktopServices.openUrl(QUrl("https://wiki.archlinux.org/title/Default_applications"))
        except OSError:
            pass

    def _import_settings(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Import settings", "",
                                              "JSON settings (*.json)")
        if path:
            try:
                n = self.settings.import_json(open(path, encoding="utf-8").read())
                QMessageBox.information(self, APP_NAME, f"Imported {n} settings.")
                self.theme_changed.emit()
            except (ValueError, OSError, json.JSONDecodeError) as exc:
                QMessageBox.warning(self, APP_NAME, f"Import failed: {exc}")

    def _export_settings(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "Export settings", "browser-settings.json",
                                              "JSON settings (*.json)")
        if path:
            with open(path, "w", encoding="utf-8") as f:
                f.write(self.settings.export_json())
            QMessageBox.information(self, APP_NAME, "Settings exported.")

    def _reset_settings(self) -> None:
        if QMessageBox.question(self, APP_NAME, "Reset ALL settings to defaults?") \
                == QMessageBox.StandardButton.Yes:
            self.settings.reset()
            self.theme_changed.emit()

    # -- 2 Appearance ---------------------------------------------------------
    def _page_appearance(self, lay) -> None:
        self._title(lay, "Appearance")
        self._section(lay, "Theme")
        lay.addWidget(self._combo("appearance.theme",
                                  [("system", "Automatic (system)"), ("dark", "Dark"),
                                   ("light", "Light")]))
        self._section(lay, "Accent color")
        row = QHBoxLayout()
        for name, hexv in [("Blue", "#4f8cff"), ("Purple", "#9b6bff"), ("Green", "#3ecf8e"),
                           ("Orange", "#ff9f43"), ("Red", "#ff5d5d"), ("Teal", "#2dd4bf")]:
            btn = QPushButton()
            btn.setFixedSize(34, 34)
            btn.setToolTip(name)
            btn.setStyleSheet(f"background:{hexv}; border-radius:17px; border:2px solid #8884")
            btn.clicked.connect(lambda _=False, h=hexv: self._set_accent(h))
            row.addWidget(btn)
        row.addStretch(1)
        lay.addLayout(row)
        self._section(lay, "Layout")
        lay.addWidget(self._check("appearance.vertical_tabs", "Vertical tabs (left side)"))
        lay.addWidget(self._check("appearance.show_bookmarks_bar", "Show bookmarks bar"))
        lay.addWidget(self._check("appearance.compact_toolbar", "Compact toolbar"))
        lay.addWidget(self._check("appearance.reduced_motion", "Reduced motion"))
        self._section(lay, "UI font size")
        spin = QSpinBox()
        spin.setRange(10, 20)
        spin.setValue(int(self.settings.get("appearance.font_size", 14)))
        spin.valueChanged.connect(lambda v: self.settings.set("appearance.font_size", v))
        row = QHBoxLayout(); row.addWidget(spin); row.addStretch(1); lay.addLayout(row)

    def _set_accent(self, hexv: str) -> None:
        self.settings.set("appearance.accent", hexv)
        self.theme_changed.emit()

    # -- 3 Privacy --------------------------------------------------------------
    def _page_privacy(self, lay) -> None:
        self._title(lay, "Privacy")
        self._section(lay, "Protection level")
        note = QLabel("Changing the level also sets the individual options below. "
                      "Balanced (default): blocks trackers and third-party cookies. "
                      "Strict additionally strengthens fingerprinting defenses and may "
                      "break some sites.")
        note.setWordWrap(True)
        note.setStyleSheet("color:#9aa2b1")
        lay.addWidget(note)

        def level_changed(value: str) -> None:
            """The level is a preset that drives the individual toggles."""
            presets = {
                "standard": {"privacy.block_trackers": False,
                             "privacy.block_third_party_cookies": False,
                             "privacy.anti_fingerprinting": "off"},
                "balanced": {"privacy.block_trackers": True,
                             "privacy.block_third_party_cookies": True,
                             "privacy.anti_fingerprinting": "light"},
                "strict":   {"privacy.block_trackers": True,
                             "privacy.block_third_party_cookies": True,
                             "privacy.anti_fingerprinting": "strict",
                             "privacy.block_popups": True},
            }
            for k, v in presets.get(value, {}).items():
                self.settings.set(k, v)
        combo_box = self._combo("privacy.level",
                                [("standard", "Standard"), ("balanced", "Balanced"),
                                 ("strict", "Strict")],
                                "Level:")
        for child in combo_box.findChildren(QComboBox):
            child.currentTextChanged.connect(level_changed)
        lay.addWidget(combo_box)
        self._section(lay, "Tracking protection")
        lay.addWidget(self._check("privacy.block_trackers", "Block known trackers, ads and fingerprinting scripts"))
        lay.addWidget(self._check("privacy.block_third_party_cookies", "Block third-party cookies"))
        lay.addWidget(self._check("privacy.block_all_cookies", "Block all cookies (breaks many sites)"))
        self._section(lay, "Ad blocking (uBlock-style filter lists)")
        lay.addWidget(self._check("adblock.enabled",
                                  "Enable ad & tracker blocking (filter lists)"))
        lay.addWidget(self._check("adblock.cosmetic",
                                  "Hide ad elements (cosmetic filters)"))
        lay.addWidget(QLabel("Lists are managed at browser://adblock — bundled "
                             "offline list plus optional EasyList / EasyPrivacy / "
                             "uBlock filters subscriptions."))
        self._section(lay, "Fingerprinting")
        lay.addWidget(self._combo("privacy.anti_fingerprinting",
                                  [("off", "Off"), ("light", "Light"), ("strict", "Strict")]))
        note2 = QLabel("Light randomizes timing/thread values. Strict additionally perturbs "
                       "canvas/audio fingerprints and hides plugins — some sites may look "
                       "or behave differently. No browser can defeat all fingerprinting; "
                       "this reduces, not removes, the risk.")
        note2.setWordWrap(True); note2.setStyleSheet("color:#9aa2b1")
        lay.addWidget(note2)
        self._section(lay, "Signals")
        lay.addWidget(self._check("privacy.do_not_track", "Send Do-Not-Track"))
        lay.addWidget(self._check("privacy.global_privacy_control", "Send Global Privacy Control"))
        self._section(lay, "WebRTC")
        lay.addWidget(self._combo("privacy.webrtc_policy",
                                  [("default", "Default (leaks local IPs to sites using WebRTC)"),
                                   ("disable", "Disable WebRTC in pages (strictest)")]))
        self._section(lay, "Pop-ups and suggestions")
        lay.addWidget(self._check("privacy.block_popups", "Block popup windows (links you click still open)"))
        lay.addWidget(self._check("privacy.suggestions_in_omnibox",
                                  "Send typed search text to the search engine for suggestions"))
        self._section(lay, "On exit")
        lay.addWidget(self._check("privacy.cookies_clear_on_exit", "Clear cookies when browser closes"))
        clear_btn = QPushButton("Clear browsing data now…")
        clear_btn.clicked.connect(lambda: self.s.open_clear_data())
        lay.addWidget(clear_btn)
        self._section(lay, "Tor (optional)")
        lay.addWidget(self._check("tor.enabled",
                                  "Route all traffic through a local Tor SOCKS5 proxy "
                                  "(applied at next start)"))
        tor_row = QHBoxLayout()
        tor_row.addWidget(QLabel("SOCKS5 port:"))
        tport = QSpinBox(); tport.setRange(1, 65535)
        tport.setValue(int(self.settings.get("tor.socks_port", 9050)))
        tport.valueChanged.connect(lambda v: self.settings.set("tor.socks_port", v))
        tor_row.addWidget(tport); tor_row.addStretch(1)
        lay.addLayout(tor_row)
        tor_path = QLineEdit(self.settings.get("tor.tor_path") or "")
        tor_path.setPlaceholderText("Path to tor.exe (optional — browser can launch it)")
        tor_path.editingFinished.connect(
            lambda: self.settings.set("tor.tor_path", tor_path.text().strip()))
        lay.addWidget(tor_path)
        tor_link = QLabel('Status, tests and warnings: <a href="browser://tor">browser://tor</a>')
        tor_link.setOpenExternalLinks(False)
        tor_link.linkActivated.connect(lambda _u: self.s.open_internal_page(URL_TOR))
        lay.addWidget(tor_link)
        tor_warn = QLabel("Warning: WebRTC is auto-disabled in Tor mode (it bypasses proxies "
                          "and would leak your IP). This is not the Tor Browser — enable "
                          "strict fingerprinting defenses for best results.")
        tor_warn.setWordWrap(True); tor_warn.setStyleSheet("color:#9aa2b1")
        lay.addWidget(tor_warn)

    # -- 4 Security ---------------------------------------------------------------
    def _page_security(self, lay) -> None:
        self._title(lay, "Security")
        self._section(lay, "Connections")
        lay.addWidget(self._check("security.https_first",
                                  "HTTPS-First: try https:// first for every site"))
        lay.addWidget(self._check("security.block_mixed_content", "Block insecure (mixed) content"))
        self._section(lay, "Safe browsing")
        lay.addWidget(self._check("security.safe_browsing",
                                  "Warn about dangerous sites (local threat lists, offline)"))
        note = QLabel("Checks run locally against a bundled list. browser does NOT "
                      "send your browsing history anywhere. A provider lookup would "
                      "require typing an API key below AND checking consent — disabled "
                      "by default.")
        note.setWordWrap(True); note.setStyleSheet("color:#9aa2b1")
        lay.addWidget(note)
        lay.addWidget(self._check("security.safe_browsing_consent",
                                  "I consent to lookups against my configured provider (explicit)"))
        self._section(lay, "Downloads")
        lay.addWidget(self._check("security.download_warnings",
                                  "Warn before saving executable/dangerous files"))
        self._section(lay, "Fixed behavior")
        never = QLabel("Certificate errors are always rejected, updates are "
                       "verified before being offered, and downloads are never "
                       "executed automatically.")
        never.setWordWrap(True); never.setStyleSheet("color:#9aa2b1")
        lay.addWidget(never)

    # -- 5 Search ---------------------------------------------------------------
    def _page_search(self, lay) -> None:
        self._title(lay, "Search")
        self._section(lay, "Default search engine")
        engines = list(BUILTIN_ENGINES.keys())
        customs = self.settings.get("search.custom_engines", [])
        all_names = engines + [c["name"] for c in customs]
        box = QWidget(); row = QHBoxLayout(box); row.setContentsMargins(0, 0, 0, 0)
        cb = QComboBox(); cb.addItems(all_names)
        cur = self.settings.get("search.default_engine")
        if cur in all_names:
            cb.setCurrentText(cur)
        cb.currentTextChanged.connect(lambda t: self.settings.set("search.default_engine", t))
        row.addWidget(QLabel("Engine:")); row.addWidget(cb); row.addStretch(1)
        lay.addWidget(box)
        self._section(lay, "Custom engines")
        self.custom_list = QListWidget()
        for c in customs:
            self.custom_list.addItem(f"{c['name']} — {c['url']}")
        lay.addWidget(self.custom_list)
        form = QFormLayout()
        self.ce_name = QLineEdit(); self.ce_name.setPlaceholderText("Name")
        self.ce_url = QLineEdit(); self.ce_url.setPlaceholderText("https://…search?q={query}")
        form.addRow(self.ce_name); form.addRow(self.ce_url)
        lay.addLayout(form)
        add = QPushButton("Add engine")
        add.clicked.connect(self._add_custom_engine)
        lay.addWidget(add)
        rem = QPushButton("Remove selected custom engine")
        rem.clicked.connect(self._remove_custom_engine)
        lay.addWidget(rem)
        lay.addWidget(self._check("search.show_suggestions", "Show suggestions in the address bar"))

    def _add_custom_engine(self) -> None:
        name, url = self.ce_name.text().strip(), self.ce_url.text().strip()
        if not name or "{query}" not in url:
            QMessageBox.warning(self, APP_NAME,
                                "Needs a name and a URL containing {query}.")
            return
        customs = list(self.settings.get("search.custom_engines", []))
        customs.append({"name": name, "url": url, "suggest_url": ""})
        self.settings.set("search.custom_engines", customs)
        self.custom_list.addItem(f"{name} — {url}")
        self.ce_name.clear(); self.ce_url.clear()

    def _remove_custom_engine(self) -> None:
        row = self.custom_list.currentRow()
        if row < 0:
            return
        customs = list(self.settings.get("search.custom_engines", []))
        if 0 <= row < len(customs):
            name = customs.pop(row)["name"]
            self.settings.set("search.custom_engines", customs)
            self.custom_list.takeItem(row)
            if self.settings.get("search.default_engine") == name:
                self.settings.set("search.default_engine", "DuckDuckGo")

    # -- 6 Tabs -------------------------------------------------------------------
    def _page_tabs(self, lay) -> None:
        self._title(lay, "Tabs")
        lay.addWidget(self._combo("tabs.new_tab_position",
                                  [("end", "New tabs open at the end"),
                                   ("after_current", "New tabs open next to the current tab")]))
        lay.addWidget(self._check("tabs.new_tab_background", "Open links in new tabs in the background"))
        lay.addWidget(self._check("tabs.middle_click_close", "Middle-click closes tabs"))
        lay.addWidget(self._check("tabs.ctrl_tab_cycle", "Ctrl+Tab cycles recent tabs"))
        lay.addWidget(self._check("tabs.confirm_closing_pinned_group", "Warn when closing groups with pinned tabs"))

    # -- 7 Downloads --------------------------------------------------------------
    def _page_downloads(self, lay) -> None:
        self._title(lay, "Downloads")
        dir_row = QHBoxLayout()
        self.dl_dir = QLineEdit(self.settings.get("downloads.dir") or "")
        self.dl_dir.setPlaceholderText(str(paths.downloads_dir()))
        browse = QPushButton("…")
        browse.setFixedWidth(40)
        browse.clicked.connect(self._pick_dl_dir)
        dir_row.addWidget(QLabel("Folder:")); dir_row.addWidget(self.dl_dir); dir_row.addWidget(browse)
        lay.addLayout(dir_row)
        self.dl_dir.editingFinished.connect(
            lambda: self.settings.set("downloads.dir", self.dl_dir.text().strip()))
        lay.addWidget(self._check("downloads.ask_where_to_save", "Ask where to save each file"))
        self._section(lay, "Local antivirus hook (optional)")
        note = QLabel("Optional command to scan completed downloads. %p is the file path. "
                      "Runs locally; example: MpCmdRun.exe -Scan -ScanType 3 -File %p")
        note.setWordWrap(True); note.setStyleSheet("color:#9aa2b1")
        lay.addWidget(note)
        scan = QLineEdit(self.settings.get("advanced.scan_command") or "")
        scan.editingFinished.connect(lambda: self.settings.set("advanced.scan_command", scan.text()))
        lay.addWidget(scan)

    def _pick_dl_dir(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "Download folder")
        if d:
            self.dl_dir.setText(d)
            self.settings.set("downloads.dir", d)

    # -- 8 Passwords ----------------------------------------------------------------
    def _page_passwords(self, lay) -> None:
        self._title(lay, "Passwords")
        lay.addWidget(self._check("passwords.save_prompts", "Offer to save passwords"))
        lay.addWidget(self._check("passwords.autofill", "Autofill saved passwords"))
        self._section(lay, "Master password")
        vault = self.s.vault
        uses = False
        try:
            uses = vault.uses_master_password() if vault.is_initialized() else False
        except Exception:
            pass
        state = QLabel("Master password is <b>on</b> — vault is re-encrypted under your password."
                       if uses else
                       "Master password is <b>off</b> — the vault is encrypted with a "
                       "machine key. Recommended: turn it on.")
        state.setWordWrap(True)
        lay.addWidget(state)
        row = QHBoxLayout()
        if uses:
            change = QPushButton("Change / remove master password…")
            change.clicked.connect(self._change_master)
            row.addWidget(change)
        else:
            enable = QPushButton("Enable master password…")
            enable.clicked.connect(self._enable_master)
            row.addWidget(enable)
        row.addStretch(1)
        lay.addLayout(row)
        self._section(lay, "Auto-lock")
        spin = QSpinBox(); spin.setRange(0, 480)
        spin.setValue(int(self.settings.get("passwords.auto_lock_minutes", 30)))
        spin.setSuffix(" min")
        spin.setSpecialValueText("Never (not recommended)")
        spin.valueChanged.connect(lambda v: (self.settings.set("passwords.auto_lock_minutes", v),
                                             vault.change_auto_lock(v)))
        row = QHBoxLayout(); row.addWidget(QLabel("Lock vault after inactivity:")); row.addWidget(spin)
        row.addStretch(1); lay.addLayout(row)

    def _enable_master(self) -> None:
        dlg = MasterPasswordDialog("set", self)
        if dlg.exec() and dlg.ok:
            if self.s.vault.set_master_password(dlg.value or None):
                QMessageBox.information(self, APP_NAME, "Master password enabled.")
                self.stack.setCurrentIndex(self.stack.currentIndex())  # refresh

    def _change_master(self) -> None:
        dlg = MasterPasswordDialog("change", self)
        if dlg.exec() and dlg.ok:
            old, new = dlg.value
            if self.s.vault.unlock(old) or not self.s.vault.uses_master_password():
                self.s.vault.set_master_password(new or None)
                QMessageBox.information(self, APP_NAME,
                                        "Master password updated." if new else
                                        "Master password removed.")

    # -- 9 Bookmarks -----------------------------------------------------------------
    def _page_bookmarks(self, lay) -> None:
        self._title(lay, "Bookmarks")
        lay.addWidget(self._check("appearance.show_bookmarks_bar", "Show bookmarks bar"))
        row = QHBoxLayout()
        exp = QPushButton("Export HTML…")
        imp = QPushButton("Import HTML…")
        exp.clicked.connect(lambda: self.s.do_bookmark_export())
        imp.clicked.connect(lambda: self.s.do_bookmark_import())
        row.addWidget(exp); row.addWidget(imp); row.addStretch(1)
        lay.addLayout(row)
        lay.addWidget(QLabel("Manage bookmarks in browser://bookmarks — "
                             "drag in the bookmarks bar to reorganize."))

    # -- 10 History --------------------------------------------------------------------
    def _page_history(self, lay) -> None:
        self._title(lay, "History")
        lay.addWidget(self._check("history.enabled", "Record browsing history (private tabs are never recorded)"))
        self._section(lay, "Retention")
        spin = QSpinBox(); spin.setRange(0, 3650)
        spin.setValue(int(self.settings.get("history.retention_days", 90)))
        spin.setSuffix(" days")
        spin.setSpecialValueText("Keep forever")
        spin.valueChanged.connect(lambda v: self.settings.set("history.retention_days", v))
        row = QHBoxLayout(); row.addWidget(QLabel("Delete history older than:")); row.addWidget(spin)
        row.addStretch(1); lay.addLayout(row)
        clear = QPushButton("Clear browsing data…")
        clear.clicked.connect(lambda: self.s.open_clear_data())
        lay.addWidget(clear)

    # -- 11 Permissions -------------------------------------------------------------------
    def _page_permissions(self, lay) -> None:
        self._title(lay, "Permissions")
        lay.addWidget(QLabel(
            "Global defaults. Camera, microphone, location and screen sharing can "
            "never be globally allowed — you approve them per site, every time."))
        pm = self.s.permissions
        table = QTableWidget(len(MANAGEABLE), 2)
        table.setHorizontalHeaderLabels(["Feature", "Default"])
        table.verticalHeader().setVisible(False)
        for r, f in enumerate(MANAGEABLE):
            table.setItem(r, 0, QTableWidgetItem(FEATURES.get(f, f)))
            combo = QComboBox()
            combo.addItems(["ask", "allow", "block"])
            combo.setCurrentText(pm.global_default(f))
            sensitive = f in SENSITIVE
            if sensitive:
                combo.model().item(1).setEnabled(False)  # no global allow
            def changed(text, feature=f, sensitive=sensitive):
                if sensitive and text == "allow":
                    return
                pm.set_global_default(feature, text)
            combo.currentTextChanged.connect(changed)
            table.setCellWidget(r, 1, combo)
        table.horizontalHeader().setStretchLastSection(True)
        table.setColumnWidth(0, 300)
        lay.addWidget(table)
        link = QLabel('Per-site overrides: <a href="browser://permissions">browser://permissions</a>')
        link.setOpenExternalLinks(False)
        link.linkActivated.connect(self.s.open_internal_page)
        lay.addWidget(link)

    # -- 12 Extensions -------------------------------------------------------------------
    def _page_extensions(self, lay) -> None:
        self._title(lay, "Extensions")
        lay.addWidget(QLabel("Manage on <a href=\"browser://extensions\">browser://extensions</a>"))
        note = QLabel("browser runs user-script extensions (JS/CSS injected into pages). "
                      "It does not run Chrome/Firefox WebExtensions — the engine "
                      "provides no such APIs, and browser does not claim otherwise.")
        note.setWordWrap(True); note.setStyleSheet("color:#9aa2b1")
        lay.addWidget(note)

    # -- 13 Accessibility -------------------------------------------------------------------
    def _page_accessibility(self, lay) -> None:
        self._title(lay, "Accessibility")
        self._section(lay, "Page zoom")
        dz = QDoubleSpinBox(); dz.setRange(0.5, 2.0); dz.setSingleStep(0.1)
        dz.setValue(float(self.settings.get("a11y.page_zoom_default", 1.0)))
        dz.valueChanged.connect(lambda v: self.settings.set("a11y.page_zoom_default", v))
        row = QHBoxLayout(); row.addWidget(QLabel("Default page zoom:")); row.addWidget(dz)
        row.addStretch(1); lay.addLayout(row)
        lay.addWidget(self._check("a11y.high_contrast", "High-contrast UI borders"))
        lay.addWidget(self._check("appearance.reduced_motion", "Reduced motion"))
        self._section(lay, "Platform features")
        lay.addWidget(QLabel("Screen readers, keyboard navigation and high-contrast "
                             "system themes are supported through the Qt accessibility "
                             "stack automatically."))

    # -- 14 Advanced ----------------------------------------------------------------------
    def _page_advanced(self, lay) -> None:
        self._title(lay, "Advanced")
        self._section(lay, "Page content")
        lay.addWidget(self._check("advanced.javascript_enabled", "Enable JavaScript"))
        lay.addWidget(self._check("advanced.images_enabled", "Load images"))
        lay.addWidget(self._check("advanced.spellcheck", "Enable spellcheck"))
        self._section(lay, "Network")
        lay.addWidget(self._combo("advanced.proxy_mode",
                                  [("system", "Use system proxy"),
                                   ("none", "No proxy (direct)"),
                                   ("manual", "Manual (set below; requires restart)")],
                                  "Proxy:"))
        proxy = QLineEdit(self.settings.get("advanced.proxy_server") or "")
        proxy.setPlaceholderText("http://127.0.0.1:8080")
        proxy.editingFinished.connect(lambda: self.settings.set("advanced.proxy_server", proxy.text().strip()))
        lay.addWidget(proxy)
        self._section(lay, "Updates")
        lay.addWidget(self._check("updates.auto_check", "Check for updates automatically"))
        lay.addWidget(QLabel("Update feed (signed manifests only):"))
        feed = QLineEdit(self.settings.get("updates.manifest_url") or "")
        feed.setPlaceholderText("https://example.com/browser-update.json (optional)")
        feed.editingFinished.connect(lambda: self.settings.set("updates.manifest_url", feed.text().strip()))
        lay.addWidget(feed)
        check_now = QPushButton("Check for updates now")
        check_now.clicked.connect(self.s.check_updates)
        lay.addWidget(check_now)
        self._section(lay, "Restart-required note")
        lay.addWidget(QLabel("Proxy changes apply after restarting browser."))

    # -- 15 About -------------------------------------------------------------------------
    def _page_about(self, lay) -> None:
        self._title(lay, f"About {APP_NAME}")
        from PyQt6.QtCore import QT_VERSION_STR
        about = QLabel(f"""
<div style="font-size:26px; font-weight:800">browser<span style="color:#4f8cff">.</span></div>
<p style="color:#9aa2b1">A desktop web browser focused on privacy</p>
<p>Version {APP_VERSION}<br>Engine: Chromium via QtWebEngine {QT_VERSION_STR}<br>
License: MIT (application code)</p>
<p style="color:#9aa2b1">All data stays on this device. No accounts, no telemetry.</p>""")
        about.setWordWrap(True)
        lay.addWidget(about)
