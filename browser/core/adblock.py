"""Ad-block list management for browser.

Owns the filter lists (bundled + subscribed), rebuilds the compiled
:class:`FilterEngine`, mirrors settings, and tracks per-site pauses.

Design notes:
  * The bundled list loads instantly and works offline.
  * Community lists (EasyList, EasyPrivacy, ...) are *subscriptions*: the
    browser fetches them over HTTPS on the user's request only, directly
    from their publishers. Nothing about the user is sent beyond the
    request itself; no proxying, no telemetry.
  * List state lives in Settings under ``adblock.lists`` so it survives
    restarts and participates in export/reset like everything else.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable, Dict, List, Optional

from .filterengine import FilterEngine

BUILTIN_ID = "builtin"

BUILTIN_LIST_FILE = "abp_builtin.txt"      # packaged inside browser/data

DEFAULT_LISTS: List[dict] = [
    {"id": BUILTIN_ID, "name": "browser built-in (offline)",
     "url": "", "builtin": True},
    {"id": "easylist", "name": "EasyList (ads)",
     "url": "https://easylist.to/easylist/easylist.txt"},
    {"id": "easyprivacy", "name": "EasyPrivacy (trackers)",
     "url": "https://easylist.to/easylist/easyprivacy.txt"},
    {"id": "pgl", "name": "Peter Lowe's Ad servers",
     "url": "https://pgl.yoyo.org/adservers/serverlist.txt?hostformat=adblockplus"},
    {"id": "ublock-ads", "name": "uBlock filters – Ads",
     "url": "https://raw.githubusercontent.com/uBlockOrigin/uAssets/master/filters/filters.txt"},
    {"id": "ublock-badware", "name": "uBlock filters – Badware risks",
     "url": "https://raw.githubusercontent.com/uBlockOrigin/uAssets/master/filters/badware.txt"},
    {"id": "ublock-privacy", "name": "uBlock filters – Privacy",
     "url": "https://raw.githubusercontent.com/uBlockOrigin/uAssets/master/filters/privacy.txt"},
]


class ListManager:
    """State + async updating of ad-block lists; builds the FilterEngine."""

    def __init__(self, settings, data_dir, domain_of: Callable[[str], str]):
        self.settings = settings
        self.data_dir = data_dir                # .../adblock dir (created)
        self.domain_of = domain_of
        self.engine = FilterEngine()
        self._updating: Dict[str, bool] = {}
        self.on_lists_changed: Optional[Callable[[], None]] = None

    # ------------------------------------------------------------------ #
    # list state (settings-backed)
    def _state(self) -> List[dict]:
        st = self.settings.get("adblock.lists")
        if not st:                               # first run: defaults
            st = [dict(item, enabled=(item["id"] == BUILTIN_ID))
                  for item in DEFAULT_LISTS]
            self.settings.set("adblock.lists", st)
        return st

    def _save_state(self, st: List[dict]) -> None:
        self.settings.set("adblock.lists", st)

    def lists(self) -> List[dict]:
        """Merged view: state rows (incl. custom) + presets not yet added."""
        st = self._state()
        known = {row["id"] for row in st}
        out = list(st)
        for p in DEFAULT_LISTS:
            if p["id"] not in known:
                out.append({**p, "enabled": False, "not_installed": True})
        return out

    def builtin_path(self):
        # packaged with the app: browser/data/abp_builtin.txt
        return Path(__file__).resolve().parent.parent / "data" / BUILTIN_LIST_FILE

    def list_file(self, list_id: str):
        return self.data_dir / f"list_{list_id}.txt"

    def set_enabled(self, list_id: str, enabled: bool) -> None:
        st = self._state()
        for row in st:
            if row["id"] == list_id:
                row["enabled"] = bool(enabled)
                break
        else:
            for p in DEFAULT_LISTS:              # enabling an installed-less preset
                if p["id"] == list_id:
                    st.append({**p, "enabled": True})
                    break
        self._save_state(st)
        self.rebuild()

    def add_custom(self, name: str, url: str) -> str:
        import uuid
        lid = "custom_" + uuid.uuid4().hex[:8]
        st = self._state()
        st.append({"id": lid, "name": name or url, "url": url,
                   "enabled": True, "custom": True})
        self._save_state(st)
        self.rebuild()
        return lid

    def remove(self, list_id: str) -> None:
        st = [row for row in self._state() if row["id"] != list_id]
        self._save_state(st)
        try:
            self.list_file(list_id).unlink()
        except OSError:
            pass
        self.rebuild()

    def touch_updated(self, list_id: str, rule_count: int) -> None:
        import time
        st = self._state()
        for row in st:
            if row["id"] == list_id:
                row["last_updated"] = time.strftime("%Y-%m-%d %H:%M")
                row["rules"] = rule_count
        self._save_state(st)

    # ------------------------------------------------------------------ #
    # network fetching (async, direct to publisher, HTTPS)
    def update(self, list_id: str, nam, on_done: Callable[[str, bool, str], None]) -> None:
        """Fetch one list with `nam` (QNetworkAccessManager). Non-blocking."""
        st = self._state()
        row = next((r for r in st if r["id"] == list_id), None)
        if row is None or not row.get("url"):
            on_done(list_id, False, "not a subscription list")
            return
        if self._updating.get(list_id):
            return
        self._updating[list_id] = True

        from PyQt6.QtCore import QUrl
        from PyQt6.QtNetwork import QNetworkRequest

        req = QNetworkRequest(QUrl(row["url"]))
        req.setAttribute(QNetworkRequest.Attribute.RedirectPolicyAttribute,
                         QNetworkRequest.RedirectPolicy.NoLessSafeRedirectPolicy)
        rep = nam.get(req)
        rep.finished.connect(lambda _rep=rep, _lid=list_id:
                             self._fetch_done(_rep, _lid, on_done))

    def _fetch_done(self, rep, list_id: str, on_done) -> None:
        self._updating.pop(list_id, None)
        try:
            err = rep.error()
            if err != rep.NetworkError.NoError:
                on_done(list_id, False, f"network error {err}")
                return
            body = bytes(rep.readAll()).decode("utf-8", "replace")
            if len(body) < 64 or "Adblock" not in body[:400] and not any(
                    l.startswith(("||", "##", "!", "[")) for l in body.splitlines()[:20]):
                on_done(list_id, False, "not a valid filter list")
                return
            self.list_file(list_id).write_text(body, encoding="utf-8")
            n = self.rebuild()
            self.touch_updated(list_id, n)
            on_done(list_id, True, f"{n} rules")
        except Exception as exc:
            on_done(list_id, False, str(exc))
        finally:
            rep.deleteLater()

    # ------------------------------------------------------------------ #
    # the compiled engine
    def rebuild(self) -> int:
        eng = FilterEngine()
        st = self._state()
        for row in st:
            if not row.get("enabled"):
                continue
            try:
                if row["id"] == BUILTIN_ID:
                    eng.load_text(self.builtin_path().read_text("utf-8"))
                else:
                    f = self.list_file(row["id"])
                    if f.exists():
                        eng.load_text(f.read_text("utf-8"))
            except (OSError, UnicodeDecodeError):
                continue
        self.engine = eng
        self.refresh_pause_list()
        if self.on_lists_changed:
            self.on_lists_changed()
        return eng.rule_count

    # ------------------------------------------------------------------ #
    # per-site pause (the uBO "power button")
    def paused_sites(self) -> List[str]:
        return list(self.settings.get("adblock.disabled_sites", []))

    def is_paused(self, host: str) -> bool:
        root = self.domain_of(host)
        return root in self.settings.get("adblock.disabled_sites", [])

    def set_paused(self, host: str, paused: bool) -> None:
        sites = self.settings.get("adblock.disabled_sites", [])
        root = self.domain_of(host)
        if paused and root and root not in sites:
            sites.append(root)
        elif not paused and root in sites:
            sites.remove(root)
        self.settings.set("adblock.disabled_sites", sites)
        self.refresh_pause_list()

    def refresh_pause_list(self) -> None:
        self._paused_roots = frozenset(self.paused_sites())

    @property
    def paused_roots(self) -> frozenset:
        return self._paused_roots

    # ------------------------------------------------------------------ #
    def update_all_enabled(self, nam, on_done) -> None:
        for row in self.lists():
            if row.get("enabled") and row.get("url"):
                self.update(row["id"], nam, on_done)
