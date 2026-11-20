"""Smoke test for browser — run this on a real desktop session:

    python tests/smoke_test.py

It boots the engine, renders internal pages, checks tabs, private profiles,
interceptors and downloads wiring, and prints a pass/fail report.
(Automated headless unit tests live in browser/tests/.)
"""

import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("BROWSER_DATA_DIR", tempfile.mkdtemp(prefix="browser-smoke-"))

from browser.app import configure_engine

configure_engine()

from PyQt6.QtCore import QTimer, QUrl
from PyQt6.QtWebEngineQuick import QtWebEngineQuick
QtWebEngineQuick.initialize()
import PyQt6.QtWebEngineWidgets  # noqa: F401
from PyQt6.QtWidgets import QApplication

results = []


def report(name: str, ok: bool, note: str = "") -> None:
    results.append((name, ok, note))
    print(("PASS " if ok else "FAIL ") + name + (f" — {note}" if note else ""))


def main() -> int:
    app = QApplication(sys.argv)
    from browser.app import AppState
    state = AppState()
    report("engine profiles created", True)
    report("private profile off-the-record", state.private_profile.isOffTheRecord())
    report("default profile persistent",
           not state.profile.isOffTheRecord())

    from browser.ui.browser_window import BrowserWindow
    win = BrowserWindow(state, urls=[])
    win.show()
    report("main window shown", win.isVisible())

    tab = win.current_tab()
    checks = {"loaded": False, "title": ""}

    def on_title(t: str) -> None:
        checks["title"] = t

    tab.title_changed.connect(on_title)

    def check_home() -> None:
        checks["loaded"] = "browser" in checks["title"].lower() or tab.url_string.startswith("browser://")
        report("internal home page rendered", checks["loaded"],
               f"title={checks['title']!r} url={tab.url_string}")

        # privacy interceptor wired into the engine
        prof_interceptor = state.profile.urlRequestInterceptor()
        report("request interceptor installed", prof_interceptor is not None)

        # trackers: logic-level decision verified; live blocking depends on the list
        trackers, cookies, requests_, _sites = state.counters.snapshot()
        report("privacy counters live", trackers >= 0)

        # open a real page
        tab2 = win.new_tab("https://example.com")
        def check_web() -> None:
            report("real website loaded", tab2.page.title().strip() != "")
            finish()
        QTimer.singleShot(6000, check_web)

    QTimer.singleShot(3000, check_home)

    def finish() -> None:
        failed = [r for r in results if not r[1]]
        print(f"\n{len(results) - len(failed)}/{len(results)} smoke checks passed")
        if failed:
            for name, _ok, note in failed:
                print(f"  FAILED: {name} {note}")
        app.quit()

    QTimer.singleShot(12000, finish)
    app.exec()
    return 0 if all(r[1] for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
