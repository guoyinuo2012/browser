"""Extension system for browser.

browser supports *user-script extensions* (JavaScript/CSS injected into
matching pages), not Chrome/Firefox WebExtensions — QtWebEngine provides no
WebExtension APIs, so compatibility with Chrome Web Store or Firefox Add-ons
is explicitly NOT claimed.

An extension is a folder with:
    manifest.json  { id, name, version, description, permissions: [...],
                     matches: [...], inject_css: bool, all_frames: bool,
                     private_browsing: false }
    script.js      injected after document ready
    style.css      (optional)

Permissions meaning:
    page        — read/modify page content (implied by any script)
    network     — script may fetch() from any origin
    storage     — script may use localStorage
    private     — run in private windows (separate approval)

Sensitive permission approval is required at install time. Extensions are
stored in DATA/extensions/<id>/.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import List, Optional

from PyQt6.QtCore import QObject, pyqtSignal

VALID_PERMISSIONS = {"page", "network", "storage", "private", "clipboard"}

EXTENSIONS_DIR = "extensions"


class Extension:
    """A user-script extension: manifest metadata, code, permissions."""
    def __init__(self, folder: Path):
        self.folder = folder
        self.manifest: dict = {}
        self.load_manifest()

    def load_manifest(self) -> None:
        path = self.folder / "manifest.json"
        self.manifest = json.loads(path.read_text(encoding="utf-8"))

    @property
    def id(self) -> str:
        return self.manifest.get("id") or self.folder.name

    @property
    def builtin(self) -> bool:
        """Shipped with browser; cannot be removed, only disabled."""
        return bool(self.manifest.get("builtin", False))

    @property
    def default_on(self) -> bool:
        """False = per-site opt-in only (e.g. dark mode)."""
        return bool(self.manifest.get("default_on", True))

    @property
    def name(self) -> str:
        return self.manifest.get("name", self.id)

    @property
    def version(self) -> str:
        return str(self.manifest.get("version", "1.0"))

    @property
    def description(self) -> str:
        return self.manifest.get("description", "")

    @property
    def permissions(self) -> List[str]:
        return [p for p in self.manifest.get("permissions", []) if p in VALID_PERMISSIONS]

    @property
    def matches(self) -> List[str]:
        return list(self.manifest.get("matches", ["*://*/*"]))

    @property
    def all_frames(self) -> bool:
        return bool(self.manifest.get("all_frames", False))

    @property
    def script(self) -> str:
        p = self.folder / "script.js"
        return p.read_text(encoding="utf-8") if p.exists() else ""

    @property
    def css(self) -> str:
        p = self.folder / "style.css"
        return p.read_text(encoding="utf-8") if p.exists() else ""

    def has_permission(self, perm: str) -> bool:
        return perm in self.permissions

    def wants_private(self) -> bool:
        return "private" in self.permissions


class ExtensionManager(QObject):
    """Installs, removes, enables/disables and injects extensions."""

    changed = pyqtSignal()
    sensitive_permission_requested = pyqtSignal(object, list)  # (manifest, perms)

    def __init__(self, settings, data_dir: Path):
        super().__init__()
        self.settings = settings
        self.dir = data_dir / EXTENSIONS_DIR
        self.dir.mkdir(parents=True, exist_ok=True)
        self._extensions: dict[str, Extension] = {}
        self.refresh()

    # ------------------------------------------------------------------ #
    def refresh(self) -> None:
        self._extensions.clear()
        if self.dir.exists():
            for folder in sorted(self.dir.iterdir()):
                if folder.is_dir() and (folder / "manifest.json").exists():
                    try:
                        ext = Extension(folder)
                        self._extensions[ext.id] = ext
                    except (json.JSONDecodeError, OSError):
                        continue
        self.changed.emit()

    def all(self) -> List[Extension]:
        return list(self._extensions.values())

    def get(self, ext_id: str) -> Optional[Extension]:
        return self._extensions.get(ext_id)

    def is_enabled(self, ext_id: str) -> bool:
        return bool(self.settings.get("extensions.enabled", {}).get(ext_id, True))

    def site_pref(self, ext_id: str, host: str) -> Optional[bool]:
        """Per-site override: True/False, or None when unset."""
        prefs = self.settings.get("extensions.site_prefs", {}).get(ext_id, {})
        val = prefs.get(host)
        return None if val is None else bool(val)

    def set_site_pref(self, ext_id: str, host: str, on: Optional[bool]) -> None:
        all_prefs = dict(self.settings.get("extensions.site_prefs", {}))
        site = dict(all_prefs.get(ext_id, {}))
        if on is None:
            site.pop(host, None)
        else:
            site[host] = bool(on)
        if site:
            all_prefs[ext_id] = site
        else:
            all_prefs.pop(ext_id, None)
        self.settings.set("extensions.site_prefs", all_prefs)
        self.changed.emit()

    def toggle_site_pref(self, ext_id: str, host: str) -> bool:
        """Cycle unset->on->off->unset; returns the new pref value."""
        cur = self.site_pref(ext_id, host)
        nxt = {None: True, True: False, False: None}[cur]
        self.set_site_pref(ext_id, host, nxt)
        return bool(nxt) if nxt is not None else False

    def set_enabled(self, ext_id: str, enabled: bool) -> None:
        e = dict(self.settings.get("extensions.enabled", {}))
        e[ext_id] = enabled
        self.settings.set("extensions.enabled", e)
        self.changed.emit()

    def allowed_in_private(self, ext_id: str) -> bool:
        return ext_id in self.settings.get("extensions.allow_in_private", [])

    def set_allowed_in_private(self, ext_id: str, allowed: bool) -> None:
        cur = list(self.settings.get("extensions.allow_in_private", []))
        if allowed and ext_id not in cur:
            cur.append(ext_id)
        elif not allowed and ext_id in cur:
            cur.remove(ext_id)
        self.settings.set("extensions.allow_in_private", cur)
        self.changed.emit()

    # ------------------------------------------------------------------ #
    def install(self, source: Path) -> Extension:
        """Install from an extension folder. Raises ValueError on bad manifest."""
        source = Path(source)
        manifest_path = source / "manifest.json"
        if not manifest_path.exists():
            raise ValueError("manifest.json missing")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if not isinstance(manifest, dict) or not manifest.get("id") or not manifest.get("name"):
            raise ValueError("manifest needs id and name")
        perms = [p for p in manifest.get("permissions", []) if p not in VALID_PERMISSIONS]
        if perms:
            raise ValueError(f"unknown permissions: {perms}")
        ext_id = str(manifest["id"])
        if not _safe_id(ext_id):
            raise ValueError("invalid extension id")
        dest = self.dir / ext_id
        if dest.exists():
            shutil.rmtree(dest)
        shutil.copytree(source, dest)
        self.refresh()
        return self.get(ext_id)  # type: ignore[return-value]

    def remove(self, ext_id: str) -> None:
        ext = self._extensions.get(ext_id)
        if ext is not None and ext.builtin:
            raise ValueError("built-in extensions cannot be removed")
        folder = self.dir / ext_id
        if folder.exists():
            shutil.rmtree(folder)
        self._extensions.pop(ext_id, None)
        self.changed.emit()

    # ------------------------------------------------------------------ #
    # built-in extensions shipped in browser/data/builtin_extensions/
    def sync_builtins(self) -> None:
        """Install bundled extensions (and upgrade older copies).

        Enable state and site prefs survive upgrades because only the
        extension folder is replaced, never the settings keys.

        Returns the ids that were newly installed (not upgraded).
        """
        bundled = Path(__file__).resolve().parent.parent / "data" / "builtin_extensions"
        fresh: List[str] = []
        if not bundled.is_dir():
            return fresh
        for src in sorted(bundled.iterdir()):
            mf = src / "manifest.json"
            if not mf.is_file():
                continue
            try:
                manifest = json.loads(mf.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue
            ext_id = manifest.get("id", src.name)
            if not _safe_id(ext_id) or not manifest.get("name"):
                continue
            dest = self.dir / ext_id
            installed = None
            if dest.exists():
                try:
                    installed = Extension(dest)
                except (json.JSONDecodeError, OSError):
                    installed = None
            if installed is not None:
                if not installed.builtin:
                    continue                      # user ext took the id
                if installed.version == manifest.get("version", "1.0"):
                    continue                      # up to date
            fresh.append(ext_id)
            if dest.exists():
                shutil.rmtree(dest)
            shutil.copytree(src, dest)
        self.refresh()
        return fresh

    # ------------------------------------------------------------------ #
    def scripts_for(self, url: str, private: bool,
                    host: str = "") -> List[tuple[Extension, str]]:
        """Returns (ext, javascript) pairs to inject for a URL."""
        out = []
        for ext in self._extensions.values():
            if not self.is_enabled(ext.id):
                continue
            if private and not (ext.wants_private() and self.allowed_in_private(ext.id)):
                continue
            if not _matches(ext.matches, url):
                continue
            # per-site prefs: off wins, and opt-in extensions need on
            if host:
                pref = self.site_pref(ext.id, host)
                if pref is False:
                    continue
                if not ext.default_on and pref is not True:
                    continue
            js = ext.script
            if js:
                out.append((ext, js))
        return out

    def css_for(self, url: str, private: bool, host: str = "") -> str:
        """Combined stylesheet text from extensions active for this URL."""
        out = []
        for ext in self._extensions.values():
            if not self.is_enabled(ext.id):
                continue
            if private and not (ext.wants_private() and self.allowed_in_private(ext.id)):
                continue
            if not _matches(ext.matches, url):
                continue
            if host:
                pref = self.site_pref(ext.id, host)
                if pref is False:
                    continue
                if not ext.default_on and pref is not True:
                    continue
            css = ext.css
            if css:
                out.append(f"/* {ext.id} */\n{css}")
        return "\n\n".join(out)


def _safe_id(ext_id: str) -> bool:
    return bool(ext_id) and all(c.isalnum() or c in "-_" for c in ext_id) and len(ext_id) <= 64


def _matches(patterns: List[str], url: str) -> bool:
    from fnmatch import fnmatch
    for pat in patterns:
        pat = pat.strip()
        if not pat:
            continue
        if pat == "<all_urls>" or pat == "*":
            return True
        if fnmatch(url, pat):
            return True
        # scheme://host/* patterns
        if pat.endswith("/*") and url.startswith(pat[:-1]):
            return True
    return False
