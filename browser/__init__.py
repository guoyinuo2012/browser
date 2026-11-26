"""
browser — a desktop web browser.

Built on QtWebEngine (Chromium). All data stays on the user's device:
no telemetry, no analytics, and no network activity beyond what the
user initiates. Optional Tor mode (off by default) routes all traffic
through a local Tor SOCKS5 proxy.

Package layout:

    core/       data + policy modules (privacy, security, storage, vault)
    ui/         native chrome UI (tabs, omnibox, toolbars, dialogs)
    pages/      browser:// internal page rendering
    data/       bundled filter lists and built-in extensions
"""

__app_name__ = "browser"
__version__ = "1.0.3"
