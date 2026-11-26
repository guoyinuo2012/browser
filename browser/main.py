"""Entry point for browser.

    python main.py [urls...]        — start browser
    python main.py --private        — start a private window
    python -m browser [args]        — equivalent

Engine configuration happens before QApplication; crash recovery is offered
when the previous run did not exit cleanly.
"""

from __future__ import annotations

import argparse
import faulthandler
import os
import sys
import traceback

from . import constants
from . import engine_probe
from .app import AppState, configure_engine
from .core.session import crashed_last_run, load as load_session

configure_engine()

import PyQt6.QtWebEngineWidgets  # noqa: F401 — must precede QApplication
from PyQt6.QtWidgets import QApplication, QMessageBox


def _crash_log_path() -> str:
    """Where startup crashes are recorded (windowed exe has no console)."""
    try:
        from . import paths
        return str(paths.data_dir() / "crash.log")
    except Exception:
        return "crash.log"


def _log_crash(stage: str, exc: BaseException) -> None:
    try:
        with open(_crash_log_path(), "a", encoding="utf-8") as f:
            import time as _t
            f.write(f"\n=== {_t.strftime('%Y-%m-%d %H:%M:%S')} — {stage} ===\n")
            traceback.print_exc(file=f)
    except Exception:
        pass    # a crash log must never cause a second crash


def main() -> int:
    """Application entry point; returns a process exit code."""
    # frozen self-entrypoint: the engine probe child runs this and exits
    if "--engine-probe" in sys.argv:
        return engine_probe.run_probe_entrypoint()

    # fatal (native) crashes land in the log, not in the void
    try:
        fh = open(_crash_log_path(), "a", encoding="utf-8")
        faulthandler.enable(file=fh)
    except Exception:
        pass    # logging is best-effort

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

    # Engine pre-flight: catches the "Chromium fail-fasts silently" class of
    # environment problems (AV policy, GPU blocks, job objects) and turns a
    # silent crash into a readable message + crash.log entry.
    if not args.no_probe and engine_probe.should_probe():
        try:
            ok, flags, code = engine_probe.find_working_configuration()
        except Exception:
            _log_crash("engine probe", sys.exc_info()[1])
            ok, flags, code = False, [], -2
        if not ok:
            msg = engine_probe.restriction_message(code)
            _log_crash("engine probe failed", Exception(msg))
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

    try:
        return _run_app(args)
    except SystemExit:
        raise
    except BaseException as exc:
        _log_crash("startup", exc)
        raise


def _run_app(args) -> int:
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

    # Tor mode: make sure the proxy is up before windows open. Launch the
    # user's tor.exe if configured; otherwise warn honestly and continue
    # WITHOUT Tor (traffic would otherwise fail to connect or, worse, would
    # be silently disabled if we dropped the proxy flag).
    if state.settings.get("tor.enabled", False):
        tm = state.tor
        if not tm.is_running():
            tor_path = state.settings.get("tor.tor_path", "")
            if tor_path and os.path.isfile(tor_path):
                tm.launch_tor(tor_path, timeout=90)
        if not tm.is_running():
            warn = ("Tor mode is enabled, but no Tor proxy answered on "
                    "127.0.0.1:%d.\n\n" % tm.socks_port
                    + "browser is starting WITHOUT Tor — pages will not load "
                    "until Tor is available.\n\n"
                    "Start Tor (e.g. Tor Browser) or configure a tor.exe path "
                    "in browser://tor (menu → More tools → Tor status), "
                    "then turn Tor mode off if you prefer normal browsing.")
            QMessageBox.warning(None, constants.APP_NAME, warn)

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
    # stop a tor.exe we launched (never a foreign Tor service)
    try:
        state.tor.stop()
    except Exception:
        pass    # teardown must never block shutdown
    state.store.close()
    state.settings.save()


