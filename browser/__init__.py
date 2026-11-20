"""
browser — a privacy-first desktop web browser.

Official name: browser (lowercase, single word).

Built on QtWebEngine (Chromium) with a modular architecture:

    engine/     application bootstrap and engine configuration
    core/       data + policy modules (privacy, security, storage, vaults)
    ui/         native chrome UI (tabs, omnibox, toolbars, dialogs)
    pages/      browser:// internal page rendering
    data/       bundled threat/block lists
"""

__app_name__ = "browser"
__version__ = "1.0.0"
