# browser

A desktop web browser built on Chromium (via QtWebEngine), with a focus on
local-only data and privacy defaults. It renders real websites, supports
tabs, private windows, an ad blocker, a password vault, and an optional Tor
mode. It is written in Python and runs on Windows, macOS and Linux.

It does not support Chrome or Firefox extensions — the engine provides no
WebExtension APIs. It has its own small user-script system instead.

## Contents

- [Download](#download)
- [Run from source](#run-from-source)
- [Building](#building)
- [Usage](#usage)
- [Features](#features)
- [Tor mode](#tor-mode)
- [Privacy and data](#privacy-and-data)
- [Security](#security)
- [Limitations](#limitations)
- [Project layout](#project-layout)
- [Development](#development)
- [Changelog](#changelog)

## Download

A standalone Windows build (no Python required) is attached to the
[latest release](https://github.com/guoyinuo2012/browser/releases/latest):
`browser-1.0.3-standalone.zip`, about 239 MB. Unzip it anywhere and run
`browser.exe`, or use one of the launcher files in the folder:

| File | Purpose |
|---|---|
| `browser.exe` | Start the browser |
| `Start browser.bat` | Start with a console window (useful for diagnostics) |
| `Start browser (silent).vbs` | Start without a console flash |
| `Start private window.bat` | Start directly in a private window |

The build is not code-signed, so Windows SmartScreen may ask for
confirmation on first run.

## Run from source

Requires Python 3.10 or newer.

```
pip install PyQt6 PyQt6-WebEngine cryptography
python main.py
```

Other invocations:

```
python main.py --private          # private window
python main.py https://example.com
python -m browser --version
```

## Building

```
pip install pyinstaller
pyinstaller browser.spec
```

Output is a single folder in `dist/browser` with `browser.exe` plus
`_internal/`. For macOS, code-sign and notarize the `.app` bundle; for
Linux, wrap the output as an AppImage if desired. Details for each platform
are in the packaging notes at the end of this file.

## Usage

Command-line options:

| Option | Effect |
|---|---|
| `--private` | Open a private window |
| `--no-probe` | Skip the engine pre-flight check |
| `--version` | Print the version |
| `urls...` | Open these addresses in tabs |

Environment variables:

| Variable | Purpose |
|---|---|
| `BROWSER_DATA_DIR` | Override the data directory (portable use) |
| `BROWSER_DOWNLOADS_DIR` | Override the default download directory |
| `BROWSER_PROXY` | Proxy for the engine, e.g. `socks5://127.0.0.1:9050` |
| `BROWSER_PROBE=0` | Disable the engine pre-flight check |
| `QTWEBENGINE_CHROMIUM_FLAGS` | Extra Chromium flags (advanced) |

If the browser fails to start, look at `crash.log` in the data directory —
startup errors and engine failures are recorded there.

## Features

**Browsing.** Tabs (reorder, pin, groups, mute, duplicate, Ctrl+Tab cycling),
private windows with off-the-record profiles, session restore and crash
recovery, an address bar with search and history/bookmark/tab suggestions,
multiple search engines plus custom and keyword engines (`@g`, `@d`, ...),
bookmarks with folders and HTML import/export, history with search and
retention pruning, a downloads manager with pause/resume, per-host zoom,
find in page, reader mode, print to PDF, save page, screenshots, and
Chromium DevTools.

**Ad and tracker blocking.** A built-in filter engine implements the
practical core of Adblock Plus/uBlock syntax: `||host^` anchors, wildcards,
regex filters, `@@` exceptions, `$script`/`$third-party`/`$domain=` options,
`$important`, and element hiding. An offline list is bundled; EasyList,
EasyPrivacy, Peter Lowe's and uBlock filters are available as
subscriptions, fetched directly from their publishers when you enable them.
Blocking can be paused per site.

**Privacy controls.** Third-party cookie blocking (or all cookies),
anti-fingerprinting in two strengths, WebRTC policy, Do Not Track and
Global Privacy Control signals, popup blocking, clear-on-exit, and a
dashboard (`browser://privacy`) showing what was blocked.

**Passwords.** An encrypted local vault (PBKDF2-SHA256, 600k rounds +
AES-256-GCM), optional master password, auto-lock, autofill, a generator,
weak/reused password analysis, and CSV import/export.

**Security.** HTTPS-First upgrades, certificate errors always rejected (no
override exists in the code), a local safe-browsing list, download screening
with an optional local antivirus hook, mixed-content blocking, and signed
update manifests (Ed25519) if you configure an update feed.

**Extensions.** Bundled user-script extensions (video speed controls, a
per-site dark mode, consent banner hiding, selection freedom) plus
installable ones. They run inside the page context only and can be disabled
per site.

**Interface.** Dark/light/system theme, accent colors, font size,
high-contrast mode, vertical tabs, full keyboard shortcuts, and screen
reader support through Qt's accessibility stack.

## Tor mode

Optional and off by default. When enabled, all traffic — including DNS — is
routed through a local Tor SOCKS5 proxy (default `127.0.0.1:9050`), and
WebRTC is disabled since it bypasses proxies. browser can use a Tor that is
already running (Tor Browser's, the Tor service) or launch a `tor.exe` you
point it at, with its own data directory; a Tor instance started by browser
is stopped when browser exits.

Manage it at `browser://tor` (menu → More tools → Tor status) or in
Settings → Privacy → Tor. Changes apply after a restart. The dashboard
shows connection status and can test exit connectivity against
check.torproject.org through the proxy.

Note that this is not the Tor Browser. The engine is Chromium, so
fingerprinting resistance is weaker; use strict fingerprinting defenses
(Settings → Privacy) in Tor mode. Some sites block or challenge Tor exits.

## Privacy and data

browser has no telemetry, analytics, crash reporting, accounts or cloud
services. Nothing is uploaded at startup or in the background.

Data leaves the device only for things you do: loading websites, search
queries (your chosen engine, only if suggestions are enabled), filter-list
updates (the list publisher, only when you update), translations, and
update checks (only if you configure a feed).

All data stays in the platform data directory:

- Windows: `%APPDATA%\browser`
- macOS: `~/Library/Application Support/browser`
- Linux: `$XDG_DATA_HOME/browser` (default `~/.local/share/browser`)

Contents: `settings.json` (preferences), `store.db` (history, bookmarks,
download records — plaintext SQLite), `vault.bin` (passwords, encrypted)
and `profile/` (Chromium profile). Private windows never write history,
cookies or cache to disk.

Filter lists are bundled and evaluated locally. Anti-fingerprinting reduces
the available surface (timing noise, canvas and audio perturbation in
strict mode) but no browser setting makes you anonymous; your IP address,
ISP and account logins still identify you.

## Security

Rendering runs in Chromium's multi-process architecture with sandboxed
renderers. Certificate errors are always rejected — there is no override
path in the code and no "proceed anyway" button. HTTPS-First upgrades
typed and link navigations, with a 24-hour per-host fallback after a TLS
failure so a plain-HTTP retry is possible manually. Safe browsing checks
main-frame navigations against a bundled local list; a provider lookup
requires both an explicit consent checkbox and a user-supplied API key,
and is off by default. Downloads are classified before saving and never
executed automatically.

Sensitive site permissions (camera, microphone, location, screen capture)
can never be globally allowed; the decision is per site. Update manifests,
if you operate a feed, must be Ed25519-signed with key pinning on first
approval and downgrade refusal.

## Limitations

- No Chrome Web Store or Firefox add-on compatibility (user-script
  extensions only; no background workers or cross-tab APIs).
- The ad blocker covers the practical core of ABP/uBO syntax. Procedural
  cosmetic filters, `$redirect`/`$csp`/`$removeparam`/`$cookie` modifiers,
  `$badfilter` expansion and scriptlets are not supported; such rules are
  skipped, never mis-applied. Element hiding runs after page load, so
  placeholders may flash briefly.
- Mute works by muting media elements in the page; the engine exposes no
  per-tab volume API.
- Proxy and Tor changes apply after a restart.
- Without a master password the vault key is machine-local; the OS account
  is the security boundary in that case.
- CSV password export is plaintext by necessity and asks for confirmation.

## Project layout

```
main.py                    entry point
browser/
  main.py app.py           startup and application wiring
  settings.py storage.py   preferences (JSON) and history/bookmarks (SQLite)
  engine_probe.py          pre-flight engine check
  core/
    privacy.py security.py vault.py downloads.py search.py qr.py
    permissions.py extensions.py session.py updates.py tor.py
    filterengine.py adblock.py bookmarks_import.py share.py
  data/                    bundled filter lists and built-in extensions
  pages/                   browser:// internal pages and their handler
  ui/                      window, tabs, omnibox, dialogs, theme
  tests/                   unit and integration tests
tools/make_update_manifest.py   signs update manifests
tests/smoke_test.py        live checks for a running build
```

## Development

Run the test suite:

```
python -m unittest discover -s browser/tests -v
```

141 tests cover the privacy engine, cookie policy, HTTPS-First, safe
browsing, the vault (including master-password rotation), the filter
engine, QR encoding with Reed-Solomon self-checks, settings, sessions,
extensions, permissions, update signature verification, the Tor module
(against an in-process fake SOCKS5 server) and internal page rendering.

## License

MIT for the application code. See the headers of bundled components for
their terms.

## Changelog

**v1.0.3** — The engine pre-flight check now works inside the packaged exe
and records engine failures to `crash.log`; startup errors of any kind are
logged there. Probe runs by default (disable with `--no-probe`).

**v1.0.2** — Optional Tor mode: browser-wide SOCKS5 routing with DNS-leak
protection, WebRTC disable, `browser://tor` dashboard with exit test,
optional tor.exe launcher. Off by default.

**v1.0.1** — Fixed the startup crashes that prevented the window from
opening, a vault corruption bug on master-password change, several broken
internal pages, and a number of features that were present but not wired
(password clipboard, extension stylesheets, security badge, per-level
privacy presets).

**v1.0.0** — Initial release.

## Packaging notes

Windows: `pyinstaller browser.spec`, then optionally an Inno Setup/NSIS
installer; sign with `signtool` for SmartScreen trust.

macOS: `pyinstaller main.py --name browser --windowed --collect-all PyQt6
--collect-submodules browser`, then
`codesign --deep --force --sign "Developer ID Application: …"` and
`xcrun notarytool` for distribution.

Linux: same PyInstaller invocation; or repackage as AppImage/Flatpak.
QtWebEngine needs system GPU libraries at runtime (libEGL, libGL,
fontconfig).
