"""Entry point for browser.

    python main.py [urls...]        — start browser
    python main.py --private        — start a private window
    python -m browser [args]        — equivalent

Engine configuration happens before QApplication; crash recovery is offered
when the previous run did not exit cleanly.
"""

from __future__ import annotations

import argparse
import os
import sys

from . import constants
from . import engine_probe
from .app import AppState, configure_engine
from .core.session import crashed_last_run, load as load_session

configure_engine()

import PyQt6.QtWebEngineWidgets  # noqa: F401 — must precede QApplication
from PyQt6.QtWidgets import QApplication, QMessageBox


def main() -> int:
    """Application entry point; returns a process exit code."""
    parser = argparse.ArgumentParser(prog=constants.APP_NAME,
                                     description="The privacy-first web browser")
    parser.add_argument("--private", action="store_true",
                        help="start with a private window")
    parser.add_argument("--no-probe", action="store_true",
                        help="skip the engine pre-flight probe")
    parser.add_argument("--version", action="version",
                        version=f"{constants.APP_NAME} {constants.APP_VERSION}")
    parser.add_argument("urls", nargs="*", help="URLs to open")
    args = parser.parse_args()

    # In restricted environments (CI sandboxes), Chromium fail-fasts silently.
    # Probe for a working flag set; bail out with a clear message if none.
    if not args.no_probe and engine_probe.should_probe():
        ok, flags, code = engine_probe.find_working_configuration()
        if not ok:
            msg = engine_probe.restriction_message(code)
            platform = os.environ.get("QT_QPA_PLATFORM", "")
            if platform in ("offscreen", "minimal"):
                # No user can click a dialog here; fail fast with the reason.
                print(msg, file=sys.stderr)
                return 2
            probe_app = QApplication(sys.argv)
            QMessageBox.critical(None, constants.APP_NAME, msg)
            return 2
        if flags:
            os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = " ".join(flags)

    app = QApplication(sys.argv)
    app.setApplicationName(constants.APP_NAME)
    app.setApplicationDisplayName(constants.APP_NAME)
    app.setOrganizationName("browser")
    app.setApplicationVersion(constants.APP_VERSION)

    state = AppState()

    # restore session unless starting fresh
    urls = args.urls
    if not urls and not args.private:
        startup = state.settings.get("general.startup_page", "home")
        if startup == "restore":
            saved = load_session(state.settings)
            urls = saved[0] if saved else []
            extra_windows = saved[1:]
        else:
            extra_windows = []
    else:
        extra_windows = []

    crashed = crashed_last_run(state.settings)
    if crashed and not args.private:
        offer = QMessageBox.question(
            None, constants.APP_NAME,
            "browser did not shut down cleanly last time.\n\nRestore your "
            "previous session? (Other open windows from last session will be "
            "reopened as well.)",
            QMessageBox.StandardButton.Restore | QMessageBox.StandardButton.Discard)
        if offer == QMessageBox.StandardButton.Restore:
            saved = load_session(state.settings)
            urls = saved[0] if saved else []
            extra_windows = saved[1:]
            state.settings.set("general.startup_page", "home", save=False)

    state.open_window(private=args.private,
                      urls=[u for u in (urls or []) if u] or None)
    for win_tabs in extra_windows:
        state.open_window(urls=[t["url"] for t in win_tabs])

    # history retention housekeeping
    state.store.prune_history(int(state.settings.get("history.retention_days", 90)))

    # periodic privacy-counter persistence + shield refresh
    def housekeeping() -> None:
        state.persist_counters()
        for w in state.windows():
            w.refresh_shield()
    
    from PyQt6.QtCore import QTimer
    hk = QTimer()
    hk.setInterval(5000)
    hk.timeout.connect(housekeeping)
    hk.start()

    # automatic update check: only against a feed the user configured and
    # only if enabled; runs quietly after the window is up.
    def _auto_update_check() -> None:
        if (state.settings.get("updates.auto_check", True)
                and state.settings.get("updates.manifest_url", "")):
            state.check_updates(None)

    QTimer.singleShot(30_000, _auto_update_check)

    # clear-on-exit rules live in close handlers; run them at quit too
    app.aboutToQuit.connect(state.persist_counters)
    app.aboutToQuit.connect(lambda: _on_quit(state))

    rc = app.exec()
    return rc


def _on_quit(state: AppState) -> None:
    from browser.core.session import mark_clean_exit
    mark_clean_exit(state.settings)
    if state.settings.get("privacy.cookies_clear_on_exit"):
        try:
            state.profile.cookieStore().deleteAllCookies()
            state.private_profile.cookieStore().deleteAllCookies()
        except RuntimeError:
            pass
    state.store.close()
    state.settings.save()


