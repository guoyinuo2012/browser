"""browser:// URL scheme handler.

Routes internal URLs to page renderers in pages.py and performs actions.
Runs on the UI thread (WebEngine calls scheme handlers there by default),
so handlers must be fast — all renderers are plain string builders.
"""

from __future__ import annotations

import html
import os
import subprocess
import sys
import time
import datetime as _dt
from urllib.parse import parse_qs, unquote_plus, urlparse

from PyQt6.QtCore import QUrl, pyqtSignal
from PyQt6.QtWebEngineCore import QWebEngineUrlRequestJob, QWebEngineUrlSchemeHandler

from . import pages
from .. import paths
from ..constants import *
from ..core.permissions import FEATURES, MANAGEABLE
from ..core.qr import encode as qr_encode, to_svg


class Services:
    """Bundle of managers handed to the scheme handler. Filled at startup."""

    def __init__(self):
        self.settings = None            # browser.settings.Settings
        self.store = None               # browser.storage.Store
        self.vault = None               # browser.core.vault.Vault
        self.counters = None            # privacy Counters
        self.policy = None              # privacy PrivacyPolicy
        self.extensions = None          # ExtensionManager
        self.permissions = None         # PermissionManager
        self.adblock = None             # core.adblock.ListManager
        self.network = None             # AppState.nam -> QNetworkAccessManager
        self.engine_name = lambda: "DuckDuckGo"
        self.engine_search_url = lambda: "https://duckduckgo.com/?q={query}"
        self.open_file = lambda path: None          # QDesktopServices hook
        self.request_unlock = lambda: None          # native unlock dialog
        self.request_settings = lambda: None        # native settings dialog
        self.request_import_file = lambda kind: None  # native file picker
        self.current_url = lambda: ""               # active tab URL
        self.current_https = lambda: False
        self.current_cert = lambda: ""
        self.security = None            # SafeBrowsing
        self.downloader = None          # DownloadManager
        self.interceptor_logic = None   # PrivacyInterceptor (page security)
        self.tor = None                 # TorManager (optional Tor mode)


class SchemeHandler(QWebEngineUrlSchemeHandler):
    """Serves browser:// URLs and dispatches internal page actions."""
    blocked_page_requested = pyqtSignal(str, str)   # url, reason

    def __init__(self, services: Services, parent=None):
        super().__init__(parent)
        self.s = services

    # ------------------------------------------------------------------ #
    def requestStarted(self, job: QWebEngineUrlRequestJob) -> None:  # noqa: N802
        url: QUrl = job.requestUrl()
        host = url.host().decode() if isinstance(url.host(), bytes) else url.host()
        path = url.path()
        try:
            html_out, mime, redirect = self._route(host, path, url)
        except Exception as exc:  # never let an internal error kill the tab
            html_out, mime, redirect = self._error_reply(str(exc)), "text/html", None
        if redirect:
            job.redirect(QUrl(redirect))
            return
        job.reply(mime.encode() if isinstance(mime, str) else mime,
                  html_out.encode() if isinstance(html_out, str) else html_out)

    def _error_reply(self, detail: str) -> str:
        """Internal error page (never crashes the scheme handler)."""
        body = f"""<div class=\"card\" style=\"margin-top:40px\">
<h2 style=\"margin-top:0\">Internal page error</h2>
<p class=\"mono small\">{html.escape(detail)}</p>
<p><a class=\"btn\" href=\"browser://home\">Go home</a></p></div>"""
        return pages.page("Error", body)

    # ------------------------------------------------------------------ #
    def _route(self, host: str, path: str, url: QUrl):
        q = parse_qs(url.query())
        g = lambda k, d="": q.get(k, [d])[0]  # noqa: E731
        s = self.s

        if host == "home":
            if path == "/search" or "q" in q:
                return "", "text/html", pages.search_redirect(g("q"), s.engine_search_url())
            return pages.home(s.settings, s.engine_name(), s.engine_search_url()), "text/html", None

        if host == "about":
            from PyQt6.QtCore import QT_VERSION_STR
            return pages.about_page(APP_VERSION, QT_VERSION_STR,
                                    str(paths.data_dir())), "text/html", None

        if host == "qr":
            target = g("url")
            if not target:
                return pages.message_page("QR code", "No URL to encode."), "text/html", None
            matrix = qr_encode(target)
            return to_svg(matrix), "image/svg+xml", None

        if host == "blocked":
            return pages.blocked(g("url"), unquote_plus(g("reason")), g("kind", "threat")), "text/html", None

        if host == "error":
            return pages.error_page(g("url"), g("title", "Cannot reach this site"),
                                    g("desc", "The website is unavailable.")), "text/html", None

        if host == "certerror":
            return pages.cert_error(g("url"), g("detail")), "text/html", None

        if host == "message":
            return pages.message_page(g("title"), g("text"), g("back", "browser://home")), "text/html", None

        if host == "history":
            return self._history(g)
        if host == "bookmarks":
            return self._bookmarks(g)
        if host == "downloads":
            return self._downloads(g)
        if host == "passwords":
            return self._passwords(g)
        if host == "privacy":
            return self._privacy()
        if host == "security":
            return self._security()
        if host == "extensions":
            return self._extensions(g)
        if host == "adblock":
            return self._adblock(g)
        if host == "permissions":
            return self._permissions(g)
        if host == "tor":
            return self._tor(g)
        if host == "settings":
            s.request_settings()
            return pages.message_page(
                "Settings", "The settings window has been opened.",
                "browser://home", "Done"), "text/html", None

        return pages.message_page("Not found", f"Unknown internal page: {host}"), "text/html", None

    # ------------------------------------------------------------------ #
    def _history(self, g):
        s = self.s
        action = g("action")
        if action == "clear_confirmed":
            s.store.clear_history()
            s.counters.reset()
        elif action == "clear" and g("confirm") == "1":
            return pages.history_confirm_clear(), "text/html", None
        elif action == "clear_last_hour":
            s.store.delete_history_range(time.time() - 3600, time.time() + 60)
        elif action == "clear_last_day":
            start = (_dt.datetime.now() - _dt.timedelta(days=1)).timestamp()
            s.store.delete_history_range(start, time.time() + 60)
        q = g("q")
        groups = s.store.history_grouped_by_day(q)
        return pages.history_page(groups, q, s.store.history_count()), "text/html", None

    # ------------------------------------------------------------------ #
    def _bookmarks(self, g):
        s = self.s
        action = g("action")
        if action == "delete":
            s.store.delete_bookmark(g("id"))
        elif action == "add_folder":
            s.store.add_folder("New folder")
        elif action == "export_html":
            s.request_import_file("bookmarks_export")
        elif action == "import_html":
            s.request_import_file("bookmarks_import")
        elif action == "edit":
            bm = s.store.get_bookmark(g("id"))
            if bm and not bm["is_folder"]:
                dup = s.store.duplicate_url_exists(bm["url"], exclude=bm["id"])
                return pages.bookmark_edit_page(bm["id"], bm["title"], bm["url"], dup), "text/html", None
        elif action == "save_edit":
            bm = s.store.get_bookmark(g("id"))
            if bm:
                s.store.update_bookmark(bm["id"], g("title"), g("url"))
        folder = g("folder")
        parent = folder if folder else None
        nodes = s.store.children(parent)
        path = ""
        if parent:
            bm = s.store.get_bookmark(parent)
            path = bm["title"] if bm else ""
        return pages.bookmarks_page(nodes, parent_path=path), "text/html", None

    # ------------------------------------------------------------------ #
    def _downloads(self, g):
        s = self.s
        action = g("action")
        if action in ("open", "show"):
            rec = s.store.get_download(g("id"))
            if rec and os.path.exists(rec["path"]):
                if action == "open":
                    s.open_file(rec["path"])
                else:
                    self._reveal(rec["path"])
        elif action == "remove":
            s.store.remove_download(g("id"))
        rows = s.store.downloads()
        return pages.downloads_page(rows), "text/html", None

    @staticmethod
    def _reveal(path: str) -> None:
        folder = os.path.dirname(path)
        try:
            if sys.platform == "win32":
                subprocess.Popen(["explorer", "/select,", os.path.normpath(path)])
            elif sys.platform == "darwin":
                subprocess.Popen(["open", "-R", path])
            else:
                subprocess.Popen(["xdg-open", folder])
        except OSError:
            pass

    # ------------------------------------------------------------------ #
    def _passwords(self, g):
        s = self.s
        action = g("action")
        if action == "unlock":
            s.request_unlock()
            return pages.vault_unlock_prompt_page(), "text/html", None
        if not s.vault.is_initialized():
            s.vault.initialize(auto_lock_minutes=s.settings.get("passwords.auto_lock_minutes", 30))
        if not s.vault.is_unlocked():
            s.request_unlock()
            return pages.vault_unlock_prompt_page(), "text/html", None
        if action == "delete":
            try:
                s.vault.delete(int(g("id")))
            except (ValueError, IndexError):
                pass
        elif action == "reveal":
            try:
                idx = int(g("id"))
                entries = s.vault.all()
                if 0 <= idx < len(entries):
                    en = entries[idx]
                    return pages.password_revealed_page(
                        en["origin"], en["username"], en["password"]), "text/html", None
            except (ValueError, IndexError):
                pass
        elif action == "copy":
            try:
                idx = int(g("id"))
                entries = s.vault.all()
                if 0 <= idx < len(entries):
                    self._copy_password(entries[idx]["password"])
                    return pages.password_copied_page(), "text/html", None
            except (ValueError, IndexError):
                pass
        elif action == "generate":
            from ..core.vault import generate_password
            return pages.password_generator_page(generate_password()), "text/html", None
        elif action == "export_csv":
            s.request_import_file("passwords_export")
        elif action == "import_csv":
            s.request_import_file("passwords_import")
        entries = s.vault.all()
        for i, en in enumerate(entries):
            from ..core.vault import strength
            en["_strength"] = strength(en["password"])
        report = s.vault.report() if entries else {"weak": [], "reused": [], "total": 0}
        return pages.passwords_page(
            entries, report, locked=False,
            uses_master=s.vault.uses_master_password()), "text/html", None

    @staticmethod
    def _copy_password(password: str) -> None:
        """Copy to the system clipboard, auto-clearing it after 60 s so the
        plaintext never lingers."""
        from PyQt6.QtCore import QTimer
        from PyQt6.QtWidgets import QApplication
        cb = QApplication.clipboard()
        cb.setText(password)
        QTimer.singleShot(60_000, lambda: cb.clear()
                          if cb.text() == password else None)

    # ------------------------------------------------------------------ #
    def _privacy(self):
        s = self.s
        trackers, cookies, ads, requests_, sites = s.counters.snapshot()
        pol = s.policy
        lines = [
            ("Tracking protection", "on" if pol.block_trackers else "off"),
            ("Third-party cookies", "blocked" if pol.block_third_party_cookies else "allowed"),
            ("All cookies", "blocked" if pol.block_all_cookies else "first-party allowed"),
            ("Fingerprinting mitigation", pol.fingerprinting),
            ("Ad blocking", "on" if s.settings.get("adblock.enabled", True) else "off"),
            ("HTTPS-First", "on" if s.settings.get("security.https_first") else "off"),
            ("Do Not Track", "sent" if s.settings.get("privacy.do_not_track") else "not sent"),
            ("Global Privacy Control", "sent" if s.settings.get("privacy.global_privacy_control") else "not sent"),
        ]
        return pages.privacy_page(
            {"trackers": trackers, "cookies": cookies, "ads": ads,
             "requests": requests_},
            lines, sorted(sites.items(), key=lambda kv: -kv[1]),
            s.settings.get("privacy.level", "balanced")), "text/html", None

    # ------------------------------------------------------------------ #
    def _security(self):
        s = self.s
        url = s.current_url()
        https = url.startswith("https://")
        cert = s.current_cert() if https else ""
        settings_lines = [
            ("HTTPS-First", "on" if s.settings.get("security.https_first") else "off"),
            ("Safe Browsing (local lists)", "on" if s.settings.get("security.safe_browsing") else "off"),
            ("Download warnings", "on" if s.settings.get("security.download_warnings") else "off"),
            ("Mixed-content blocking", "on" if s.settings.get("security.block_mixed_content") else "off"),
        ]
        alerts = []
        if s.downloader is not None:
            for r in s.downloader.recent_warnings():
                alerts.append(r)
        note = ("Threat checks run against locally bundled lists. browser does "
                "not send your browsing history to any provider. Optional "
                "provider lookups require explicit consent in Settings → Security.")
        return pages.security_page(url, https, cert, alerts, settings_lines, note), "text/html", None

    # ------------------------------------------------------------------ #
    def _extensions(self, g):
        s = self.s
        action = g("action")
        if action == "toggle":
            eid = g("id")
            s.extensions.set_enabled(eid, not s.extensions.is_enabled(eid))
        elif action == "toggle_private":
            eid = g("id")
            s.extensions.set_allowed_in_private(eid, not s.extensions.allowed_in_private(eid))
        elif action == "remove" and g("confirm") == "1":
            try:
                s.extensions.remove(g("id"))
            except ValueError as exc:
                return pages.message_page(
                    "Cannot remove", str(exc), "browser://extensions"), "text/html", None
        elif action == "install":
            s.request_import_file("extension_install")
        elif action == "site_toggle":
            eid, host = g("id"), g("host") or _host_of(s.current_url())
            if eid and host:
                cur = s.extensions.site_pref(eid, host)
                ext = s.extensions.get(eid)
                if ext is not None:
                    # default_on: unset/on -> off ; opt-in: unset/off -> on
                    nxt = False if (ext.default_on and cur is not False) else True
                    s.extensions.set_site_pref(eid, host, nxt)
        elif action == "site_reset":
            s.extensions.set_site_pref(g("id"), g("host"), None)
        exts = s.extensions.all()
        enabled = s.settings.get("extensions.enabled", {})
        priv = s.settings.get("extensions.allow_in_private", [])
        return pages.extensions_page(
            exts, enabled, priv, current_site=_host_of(s.current_url()),
            site_prefs=s.settings.get("extensions.site_prefs", {})), "text/html", None


    # ------------------------------------------------------------------ #
    def _adblock(self, g):
        s = self.s
        ab = s.adblock
        action = g("action")

        if action == "master":
            s.settings.set("adblock.enabled", g("value") != "off")
        elif action == "cosmetic":
            s.settings.set("adblock.cosmetic", g("value") != "off")
        elif action == "toggle_list":
            ab.set_enabled(g("id"), g("value") != "off")
        elif action == "remove_list" and g("confirm") == "1":
            ab.remove(g("id"))
        elif action == "add_list":
            url = g("url", "").strip()
            if url.startswith("https://"):
                ab.add_custom(g("name", "").strip() or url, url)
        elif action == "update":
            ab.update(g("id"), s.network(),
                      lambda lid, ok, msg: None)
        elif action == "pause_site":
            site = g("site", "").strip()
            if site:
                ab.set_paused(site, True)
        elif action == "resume_site":
            ab.set_paused(g("site", ""), False)
        elif action == "reset_stats":
            s.counters.reset()

        stats = {"ads": s.counters.ads, "trackers": s.counters.trackers}
        current = s.current_url() or ""
        host = ""
        try:
            from urllib.parse import urlparse
            if current.startswith("http"):
                host = urlparse(current).netloc or ""
        except Exception:
            host = ""
        return pages.adblock_page(
            bool(s.settings.get("adblock.enabled", True)),
            bool(s.settings.get("adblock.cosmetic", True)),
            stats, ab.lists(), ab.paused_sites(), host), "text/html", None

    # ------------------------------------------------------------------ #
    def _permissions(self, g):
        from ..core.permissions import SENSITIVE, FEATURES
        s = self.s
        action = g("action")
        if action == "global":
            feature, value = g("feature"), g("value")
            if feature in FEATURES and value in ("allow", "ask", "block"):
                if not (feature in SENSITIVE and value == "allow"):
                    s.permissions.set_global_default(feature, value)
        elif action == "reset_site":
            s.permissions.reset_site(g("site"))
        return pages.permissions_page(
            {f: s.permissions.global_default(f) for f in MANAGEABLE},
            s.permissions.all_sites(), FEATURES,
            selected_site=g("site")), "text/html", None

    # ------------------------------------------------------------------ #
    def _tor(self, g):
        """Tor dashboard: opt-in toggles, status, tests, tor.exe launch."""
        s = self.s
        tm = s.tor
        if tm is None:
            return pages.message_page(
                "Tor", "Tor support is unavailable in this build."), "text/html", None
        action = g("action")
        notice = ""
        if action == "enable":
            s.settings.set("tor.enabled", True)
            # safety default: WebRTC bypasses proxies and would leak the real IP
            if s.settings.get("privacy.webrtc_policy", "default") == "default":
                s.settings.set("privacy.webrtc_policy", "disable")
            notice = "Tor mode will be active after you restart browser."
        elif action == "disable":
            s.settings.set("tor.enabled", False)
            notice = "Tor mode is off; it is fully removed after a restart."
        elif action == "test":
            tm.test_exit_async()
            notice = "Exit test started — reload this page in a few seconds for the result."
        elif action == "set_path":
            path = g("path", "").strip()
            s.settings.set("tor.tor_path", path)
            notice = "Tor path saved."
        elif action == "launch":
            path = s.settings.get("tor.tor_path", "")
            if tm.launch_tor(path, timeout=30):
                notice = "Tor launched and bootstrapped — proxy is reachable."
            else:
                notice = "Could not launch or bootstrap tor.exe — see its path setting."
        enabled = bool(s.settings.get("tor.enabled", False))
        running = tm.is_running()
        can_launch = bool(s.settings.get("tor.tor_path", "").strip())
        return pages.tor_page(
            enabled, running, tm.status_line(), tm.socks_port,
            s.settings.get("tor.tor_path", ""), can_launch, notice), "text/html", None

    # ------------------------------------------------------------------ #

def _host_of(url: str) -> str:
    """Hostname of a URL string ("" when not a website)."""
    try:
        return urlparse(url).hostname or "" if url.startswith("http") else ""
    except ValueError:
        return ""


