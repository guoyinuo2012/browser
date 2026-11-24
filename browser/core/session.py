"""Session persistence and crash detection for browser.

Session state (window/tab layout) is saved to settings.internal.last_session
whenever it changes and on exit. On startup, `clean_exit` tells whether the
previous run ended cleanly; if not, the startup page offers session restore
(crash recovery).
"""

from __future__ import annotations

from typing import Any, Dict, List


def snapshot(windows: List[List[Dict[str, Any]]]) -> List[List[Dict[str, Any]]]:
    """windows: list of windows; each a list of {url, pinned, group, muted, private}."""
    out: List[List[Dict[str, Any]]] = []
    for win in windows:
        tabs = []
        for t in win:
            tabs.append({
                "url": t.get("url", ""),
                "pinned": bool(t.get("pinned")),
                "group": t.get("group") or None,
                "muted": bool(t.get("muted")),
                "private": bool(t.get("private")),
                "zoom": t.get("zoom", 1.0),
            })
        out.append(tabs)
    return out


def save(settings, windows) -> None:
    """Write a session snapshot (sanitized) to the session file."""
    settings.set("internal.last_session", snapshot(windows), save=False)
    settings.set("internal.clean_exit", False, save=False)
    settings.save()


def mark_clean_exit(settings) -> None:
    """Record that the app exited normally (disables crash recovery)."""
    settings.set("internal.clean_exit", True, save=False)
    settings.save()


def load(settings) -> List[List[Dict[str, Any]]]:
    """Read the last session snapshot; returns [] if absent/corrupt."""
    data = settings.get("internal.last_session", [])
    if not isinstance(data, list):
        return []
    # sanitize
    out = []
    for win in data:
        if not isinstance(win, list):
            continue
        tabs = []
        for t in win:
            if not isinstance(t, dict):
                continue
            url = str(t.get("url", ""))
            if not url:
                continue
            try:
                zoom = float(t.get("zoom", 1.0))
            except (TypeError, ValueError):
                zoom = 1.0
            tabs.append({
                "url": url,
                "pinned": bool(t.get("pinned")),
                "group": t.get("group"),
                "muted": bool(t.get("muted")),
                "private": bool(t.get("private")),
                "zoom": zoom,
            })
        if tabs:
            out.append(tabs)
    return out


def crashed_last_run(settings) -> bool:
    """True when the previous run did not exit cleanly."""
    return not bool(settings.get("internal.clean_exit", True))
