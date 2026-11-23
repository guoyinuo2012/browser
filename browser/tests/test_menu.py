"""Tests for the share/Lens helpers and the new menu wiring."""

from __future__ import annotations

import unittest
from urllib.parse import urlparse, unquote


class ShareHelperTests(unittest.TestCase):
    def test_lens_image_url_quotes_and_anchors(self):
        from browser.core.share import lens_image_url
        url = lens_image_url("https://x.com/a b.png")
        self.assertTrue(url.startswith("https://lens.google.com/uploadbyurl?url="))
        parsed = urlparse(url)
        self.assertEqual(parsed.scheme, "https")
        self.assertIn("lens.google.com", parsed.netloc)
        self.assertEqual(unquote(parsed.query.split("=", 1)[1]),
                         "https://x.com/a b.png")

    def test_lens_empty_falls_back_to_upload_page(self):
        from browser.core.share import lens_image_url, lens_page_url
        self.assertEqual(lens_image_url(""), lens_page_url())

    def test_email_share(self):
        from browser.core.share import email_share_url
        u = email_share_url("https://example.com/p", "My Page")
        self.assertTrue(u.startswith("mailto:?subject="))
        self.assertIn("body=", u)
        # roundtrip
        import urllib.parse as up
        q = up.parse_qs(u.split("?", 1)[1])
        self.assertEqual(q["subject"][0], "My Page")
        self.assertEqual(q["body"][0], "https://example.com/p")

    def test_copyable_link(self):
        from browser.core.share import copyable_link
        self.assertEqual(copyable_link("https://a.com"), "https://a.com")
        self.assertEqual(copyable_link("https://a.com", "Title"),
                         "Title\nhttps://a.com")

    def test_lens_js_is_selfcontained(self):
        from browser.core.share import LENS_IMAGE_JS
        self.assertIn("og:image", LENS_IMAGE_JS)
        self.assertIn("querySelectorAll", LENS_IMAGE_JS)


class MenuStructureTests(unittest.TestCase):
    """The restructured main menu mirrors the modern browser layout."""

    def _window(self):
        import os, tempfile, importlib
        tmp = tempfile.mkdtemp()
        old = os.environ.get("BROWSER_DATA_DIR")
        os.environ["BROWSER_DATA_DIR"] = tmp
        from PyQt6.QtWebEngineQuick import QtWebEngineQuick
        QtWebEngineQuick.initialize()
        import PyQt6.QtWebEngineWidgets  # noqa: F401
        from PyQt6.QtWidgets import QApplication, QMainWindow
        app = QApplication.instance() or QApplication([])
        import browser.ui.browser_window as bw
        from browser import paths
        importlib.reload(paths)
        paths.ensure_dirs()
        from browser.settings import Settings
        from browser.storage import Store
        from browser.core.privacy import Counters, PrivacyPolicy
        from browser.pages.handler import Services

        svc = Services()
        svc.settings = Settings()
        svc.store = Store(paths.database_file())
        svc.counters = Counters()
        svc.policy = PrivacyPolicy.from_settings(svc.settings)
        svc.open_file = lambda p: None
        svc.request_unlock = lambda: None
        svc.request_settings = lambda: None
        svc.request_import_file = lambda kind: None
        svc.current_url = lambda: "https://example.com/a"
        svc.current_https = lambda: True
        svc.current_cert = lambda: ""

        class FakeState:
            settings = svc.settings
            store = svc.store
            counters = svc.counters
            policy = svc.policy
            vault = None
            extensions = None
            def windows(self): return []
            def persist_counters(self): pass

        class Sig:
            def connect(self, *a): pass
        class FakeAction:
            def __init__(self, *a): pass
            def setEnabled(self, v): pass
            def setToolTip(self, t): pass
            def setCheckable(self, v): pass
            def setChecked(self, v): pass
            toggled = Sig(); triggered = Sig()
            def actions(self): return []
        built = {}
        class FakeMenu(FakeAction):
            def __init__(self, *a, **k):
                if a and isinstance(a[0], str):
                    built[str(a[0])[:45]] = True
            def addMenu(self, *a, **k):
                if a and isinstance(a[0], str): built[str(a[0])[:45]] = True
                return FakeMenu()
            def addAction(self, *a, **k):
                for arg in a[:2]:
                    if isinstance(arg, str):
                        built[arg[:45]] = True
                return FakeAction()
            def addSeparator(self): pass
            def exec(self, *a, **k): built["<exec'd>"] = True
        win = QMainWindow.__new__(bw.BrowserWindow)
        QMainWindow.__init__(win)
        from PyQt6.QtWidgets import QTabWidget
        win.tabwidget = QTabWidget()
        win.tabs = []
        win.store = svc.store
        win.settings = svc.settings
        win.app_state = FakeState()
        win.findbar = type("FB", (), {"open_bar": lambda self: None})()
        win.closed_tabs = []
        win.private = False
        win.menu_btn = type("B", (), {
            "mapToGlobal": lambda self, p: None, "height": lambda self: 20})()
        bw.QMenu = FakeMenu
        class FakeWidgetAction:
            def __init__(self, m=None): pass
            def setDefaultWidget(self, w): built["<zoom row>"] = True
        bw.QWidgetAction = FakeWidgetAction
        def fake_zoom_row(self): built["<zoom row>"] = True; return object()
        bw.BrowserWindow._zoom_row_widget = fake_zoom_row
        win._show_menu()
        if old is not None:
            os.environ["BROWSER_DATA_DIR"] = old
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)
        return built

    def test_modern_menu_sections_present(self):
        built = self._window()
        expected = [
            "Passwords and autofill", "History", "Downloads",
            "Bookmarks and lists", "Tab groups", "Extensions",
            "Delete browsing data\u2026",
            "<zoom row>",
            "Print\u2026", "Search this tab with Google Lens",
            "Translate\u2026", "Find and edit", "Save, share and cast",
            "More tools", "Help", "Settings\u2026", "Exit",
        ]
        missing = [x for x in expected if x not in built]
        self.assertEqual(missing, [])

    def test_share_entries_present(self):
        built = self._window()
        for item in ("Copy page link", "Email link\u2026",
                     "QR code for this page"):
            self.assertIn(item, built)

    def test_tab_groups_and_recent_history(self):
        built = self._window()
        self.assertIn("Tab groups", built)
        self.assertIn("Show all history", built)
        self.assertIn("Ctrl+J", built)          # downloads shortcut shown
        self.assertIn("Ctrl+Shift+Del", built)  # clear data shortcut shown


if __name__ == "__main__":
    unittest.main()
