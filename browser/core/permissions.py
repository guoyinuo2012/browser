"""Permission manager for browser.

Features are the WebEngine permission types users care about. Each feature
has a global default (ask/allow/block) and per-site overrides. Sensitive
features (camera, microphone, location, screen) can never be globally
allowed from the settings page — they must be per-site decisions.
"""

from __future__ import annotations

from typing import Dict, Optional

from PyQt6.QtCore import QObject, pyqtSignal

FEATURES = {
    "camera": "Camera",
    "microphone": "Microphone",
    "location": "Location",
    "notifications": "Notifications",
    "clipboard_read": "Clipboard reading",
    "media_audio_video": "Camera and microphone",
    "desktop_video_capture": "Screen sharing",
    "desktop_audio_video_capture": "Screen sharing with audio",
    "midi": "MIDI devices",
    "midi_sysex": "MIDI devices (system exclusive)",
    "usb": "USB devices",
    "bluetooth": "Bluetooth devices",
    "geolocation": "Precise location",
    "mouse_lock": "Mouse lock (games)",
    "save_link": "Automatic downloads",
    "background_sync": "Background synchronization",
    "unknown": "Other",
}

SENSITIVE = {"camera", "microphone", "location", "media_audio_video",
             "desktop_video_capture", "desktop_audio_video_capture",
             "midi_sysex", "usb", "bluetooth", "clipboard_read"}

# Features offered on the permission settings page (user-manageable subset)
MANAGEABLE = ["camera", "microphone", "location", "notifications",
              "clipboard_read", "usb", "bluetooth", "background_sync",
              "save_link"]


class PermissionManager(QObject):
    """Backed by settings: permissions.global / permissions.sites."""

    changed = pyqtSignal()

    def __init__(self, settings):
        super().__init__()
        self.settings = settings

    def global_default(self, feature: str) -> str:
        g = self.settings.get("permissions.global", {})
        return g.get(feature, "ask")

    def set_global_default(self, feature: str, action: str) -> None:
        g = dict(self.settings.get("permissions.global", {}))
        g[feature] = action
        self.settings.set("permissions.global", g)
        self.changed.emit()

    def site_rule(self, origin: str, feature: str) -> Optional[str]:
        sites = self.settings.get("permissions.sites", {})
        return sites.get(origin, {}).get(feature)

    def set_site_rule(self, origin: str, feature: str, action: str) -> None:
        sites = dict(self.settings.get("permissions.sites", {}))
        entry = dict(sites.get(origin, {}))
        entry[feature] = action
        sites[origin] = entry
        self.settings.set("permissions.sites", sites)
        self.changed.emit()

    def reset_site(self, origin: str) -> None:
        sites = dict(self.settings.get("permissions.sites", {}))
        sites.pop(origin, None)
        self.settings.set("permissions.sites", sites)
        self.changed.emit()

    def all_sites(self) -> Dict[str, Dict[str, str]]:
        return dict(self.settings.get("permissions.sites", {}))

    def decide(self, origin: str, feature: str) -> str:
        """Returns 'allow' | 'block' | 'ask' for this origin/feature."""
        rule = self.site_rule(origin, feature)
        if rule:
            return rule
        # Sensitive features default to Ask even if a stray global allow exists.
        if feature in SENSITIVE and self.global_default(feature) == "allow":
            return "ask"
        return self.global_default(feature)


class PermissionRequestDialog:
    """Factory data for the permission prompt (UI builds the actual dialog)."""

    def __init__(self, origin: str, feature: str, manager: PermissionManager):
        self.origin = origin
        self.feature = feature
        self.manager = manager

    @property
    def label(self) -> str:
        return FEATURES.get(self.feature, self.feature)

    def answer(self, action: str, remember: bool) -> None:
        if remember:
            self.manager.set_site_rule(self.origin, self.feature, action)
