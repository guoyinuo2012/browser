"""Settings for browser — JSON-backed, observable, all local.

Every setting has a default; user values live in settings.json inside the
data directory. Import/export is supported. No telemetry is written anywhere.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any, Callable, Dict, List

from . import paths

# ---------------------------------------------------------------------------
# Defaults — grouped by settings section. Keep in sync with the Settings page.
# ---------------------------------------------------------------------------

DEFAULTS: Dict[str, Any] = {
    # -- General -------------------------------------------------------------
    "general.startup_page": "home",           # home | restore | blank | custom
    "general.custom_homepage": "https://duckduckgo.com",
    "general.new_tab_page": "home",           # home | blank
    "general.ask_on_close_multiple_tabs": True,
    "general.confirm_quit": False,
    "general.language": "system",
    # -- Appearance ----------------------------------------------------------
    "appearance.theme": "system",             # dark | light | system
    "appearance.accent": "#4f8cff",
    "appearance.font_size": 14,
    "appearance.reduced_motion": False,
    "appearance.vertical_tabs": False,
    "appearance.show_bookmarks_bar": True,
    "appearance.compact_toolbar": False,
    "appearance.wallpaper": "gradient",       # gradient | solid | none
    # -- Privacy -------------------------------------------------------------
    "privacy.level": "balanced",              # standard | balanced | strict
    "privacy.block_trackers": True,
    "privacy.block_third_party_cookies": True,
    "privacy.block_all_cookies": False,
    "privacy.cookies_clear_on_exit": False,
    "privacy.anti_fingerprinting": "light",   # off | light | strict
    "privacy.do_not_track": True,
    "privacy.global_privacy_control": True,
    "privacy.clear_on_exit": [],              # list of: history,cookies,cache
    "privacy.suggestions_in_omnibox": True,   # suggestions come from the search engine
    "privacy.webrtc_policy": "default",       # default | proxy_only | disable
    "privacy.block_popups": True,
    "adblock.enabled": True,
    "adblock.cosmetic": True,
    "adblock.disabled_sites": [],              # per-site pause (eTLD+1)
    "adblock.lists": [],                       # filled by core.adblock on first run
    # -- Security ------------------------------------------------------------
    "security.https_first": True,
    "security.safe_browsing": True,           # local threat lists, no uploads
    "security.safe_browsing_consent": False,  # explicit consent for any provider lookup
    "security.safe_browsing_api_key": "",
    "security.download_warnings": True,
    "security.block_mixed_content": True,
    "security.warn_insecure_password_fields": True,
    # -- Search --------------------------------------------------------------
    "search.default_engine": "DuckDuckGo",
    "search.custom_engines": [],              # [{name, url, suggest_url}]
    "search.show_suggestions": True,
    # -- Tabs ----------------------------------------------------------------
    "tabs.new_tab_position": "end",           # end | after_current
    "tabs.new_tab_background": False,
    "tabs.ctrl_tab_cycle": True,
    "tabs.middle_click_close": True,
    "tabs.confirm_closing_pinned_group": True,
    "tabs.tabs_per_group_limit": 0,
    # -- Downloads -----------------------------------------------------------
    "downloads.dir": "",                      # empty = OS Downloads folder
    "downloads.ask_where_to_save": False,
    "downloads.warn_dangerous": True,
    # -- Passwords -----------------------------------------------------------
    "passwords.save_prompts": True,
    "passwords.autofill": True,
    "passwords.auto_lock_minutes": 30,
    "passwords.use_master_password": False,
    # -- History -------------------------------------------------------------
    "history.enabled": True,
    "history.retention_days": 90,             # 0 = keep forever
    "history.private_never_recorded": True,   # informational (enforced, not settable)
    # -- Permissions ----------------------------------------------------------
    "permissions.global": {},                 # {feature: ask|allow|block}
    "permissions.sites": {},                  # {origin: {feature: allow|block}}
    # -- Accessibility ---------------------------------------------------------
    "a11y.page_zoom_default": 1.0,
    "a11y.font_scale": 1.0,
    "a11y.high_contrast": False,
    # -- Advanced --------------------------------------------------------------
    "advanced.javascript_enabled": True,
    "advanced.images_enabled": True,
    "advanced.spellcheck": True,
    "advanced.spellcheck_languages": "en-US",
    "advanced.proxy_mode": "system",          # system | none | manual
    "advanced.proxy_server": "",
    "advanced.scan_command": "",              # local AV hook, %p = file path
    "advanced.do_not_disturb_notifications": False,
    # -- Updates ---------------------------------------------------------------
    "updates.auto_check": True,
    "updates.manifest_url": "",               # user-provided signed manifest feed
    "updates.channel": "stable",
    # -- Extensions --------------------------------------------------------------
    "extensions.enabled": {},                 # {ext_id: bool}
    "extensions.allow_in_private": [],        # ext ids approved for private windows
    # -- Internal ---------------------------------------------------------------
    "internal.last_session": [],              # list of windows: list of {url, pinned, group}
    "internal.clean_exit": True,
    "internal.window_geometry": "",
    "internal.first_run_done": False,
    "internal.stats": {"trackers_blocked": 0, "cookies_blocked": 0, "requests_blocked": 0},
    "internal.stats_by_site": {},             # {origin: int}
    "internal.zoom_by_host": {},
}

_DESYNC_KEYS = {"internal.stats", "internal.stats_by_site", "internal.last_session",
                "internal.clean_exit", "internal.window_geometry", "internal.first_run_done"}


class Settings:
    """Thread-safe JSON settings store with change notification."""

    def __init__(self, path: Path | None = None):
        self._path = paths.config_file() if path is None else Path(path)
        self._lock = threading.RLock()
        self._values: Dict[str, Any] = {}
        self._observers: List[Callable[[str, Any], None]] = []
        self.load()

    # -- persistence --------------------------------------------------------
    def load(self) -> None:
        with self._lock:
            self._values = dict(DEFAULTS)
            p = self._path
            if p is not None and p.exists():
                try:
                    user = json.loads(p.read_text(encoding="utf-8"))
                    if isinstance(user, dict):
                        self._values.update(user)
                except (json.JSONDecodeError, OSError):
                    # Corrupt settings must not brick the browser; keep defaults
                    # and preserve the broken file for inspection.
                    try:
                        p.rename(p.with_suffix(".corrupt"))
                    except OSError:
                        pass

    def save(self) -> None:
        with self._lock:
            if self._path is None:
                return
            self._path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self._values, indent=2), encoding="utf-8")
            tmp.replace(self._path)

    # -- access -------------------------------------------------------------
    def get(self, key: str, default: Any = None) -> Any:
        with self._lock:
            if key in self._values:
                return self._values[key]
            return DEFAULTS.get(key, default)

    def set(self, key: str, value: Any, save: bool = True) -> None:
        with self._lock:
            self._values[key] = value
        if save:
            self.save()
        for cb in list(self._observers):
            try:
                cb(key, value)
            except Exception:
                pass    # an observer must never break setting changes

    def observe(self, cb: Callable[[str, Any], None]) -> None:
        self._observers.append(cb)

    def all(self) -> Dict[str, Any]:
        with self._lock:
            return dict(self._values)

    # -- bulk operations ------------------------------------------------------
    def export_json(self) -> str:
        with self._lock:
            export = {k: v for k, v in self._values.items()
                      if not k.startswith("internal.")}
        return json.dumps(export, indent=2)

    def import_json(self, text: str) -> int:
        data = json.loads(text)
        if not isinstance(data, dict):
            raise ValueError("settings export must be a JSON object")
        n = 0
        for k, v in data.items():
            if k in DEFAULTS and not k.startswith("internal."):
                self.set(k, v, save=False)
                n += 1
        self.save()
        return n

    def reset(self) -> None:
        with self._lock:
            self._values = dict(DEFAULTS)
        self.save()

    def clear_transient(self) -> None:
        """Remove per-run state before saving a portable copy."""
        for k in _DESYNC_KEYS:
            self._values.pop(k, None)

