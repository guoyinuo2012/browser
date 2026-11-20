"""Platform-correct data, cache, and download paths for browser.

Resolution order for the data directory:
1. BROWSER_DATA_DIR environment variable (also used by the test suite).
2. Windows: %APPDATA%/browser
3. macOS:   ~/Library/Application Support/browser
4. Linux:   $XDG_DATA_HOME/browser (default ~/.local/share/browser)

All user data stays local. browser never writes outside these directories.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


def _platform_data_dir() -> Path:
    if sys.platform == "win32":
        base = os.environ.get("APPDATA")
        if base:
            return Path(base) / "browser"
        return Path.home() / "AppData" / "Roaming" / "browser"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "browser"
    base = os.environ.get("XDG_DATA_HOME")
    if base:
        return Path(base) / "browser"
    return Path.home() / ".local" / "share" / "browser"


def data_dir() -> Path:
    """User data directory (respects BROWSER_DATA_DIR)."""
    env = os.environ.get("BROWSER_DATA_DIR")
    if env:
        return Path(env)
    return _platform_data_dir()


def cache_dir() -> Path:
    """Erasable cache directory."""
    env = os.environ.get("BROWSER_CACHE_DIR")
    if env:
        return Path(env)
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA")
        if base:
            return Path(base) / "browser" / "Cache"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Caches" / "browser"
    base = os.environ.get("XDG_CACHE_HOME")
    if base:
        return Path(base) / "browser"
    return Path.home() / ".cache" / "browser"


def config_file() -> Path:
    """Settings JSON file path."""
    return data_dir() / "settings.json"


def database_file() -> Path:
    """SQLite database file path."""
    return data_dir() / "store.db"


def vault_file() -> Path:
    """Encrypted password vault file path."""
    return data_dir() / "vault.bin"


def downloads_dir() -> Path:
    """Default download target directory."""
    env = os.environ.get("BROWSER_DOWNLOADS_DIR")
    if env:
        return Path(env)
    # Respect the OS per-user Downloads folder.
    if sys.platform == "win32":
        base = os.environ.get("USERPROFILE")
        if base:
            return Path(base) / "Downloads"
    return Path.home() / "Downloads"


def ensure_dirs() -> None:
    """Create all required data directories."""
    data_dir().mkdir(parents=True, exist_ok=True)
    cache_dir().mkdir(parents=True, exist_ok=True)


def default_profile_dir() -> Path:
    """Chromium profile storage directory."""
    return data_dir() / "profile"

def private_profile_dir() -> Path:
    """Off-the-record profiles must never touch disk; Qt requires a path anyway."""
    return cache_dir() / "private-profile"
