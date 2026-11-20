# browser

**The privacy-first web browser.** A real, working desktop browser built on
Chromium (QtWebEngine) — full website rendering, tabs, private browsing,
tracker blocking, a password vault, bookmarks, history, downloads, and more.
Official name: `browser` (lowercase).

---

## Why this architecture

| Decision | Choice | Reason |
|---|---|---|
| Rendering engine | **Chromium via QtWebEngine 6.11** | Real website compatibility (the hard part of a browser), multi-process sandboxed renderer, mature TLS stack. Writing a new engine from scratch was rejected as infeasible and unsafe. |
| UI framework | **PyQt6 (Qt 6.11)** | Native cross-platform chrome (Windows/macOS/Linux), accessibility stack, theming. |
| Language | Python 3.10+ | Maintainable, no build toolchain required to run from source. |
| Storage | SQLite + AES-256-GCM vault | Local-only, no accounts, no cloud. |

`browser` does **not** run Chrome Web Store or Firefox extensions (the engine
provides no WebExtension APIs). It ships its own user-script extension system
instead; compatibility claims are never faked.

## Feature checklist

### Core browsing
- [x] Full website browsing (Chromium engine, JavaScript, WebGL, PDF viewer)
- [x] Multiple tabs — open/close/duplicate/reorder (drag), pin, group,
      rename groups, mute, search open tabs (Ctrl+Shift+A), middle-click close
- [x] Private windows (Ctrl+Shift+N) with **off-the-record profiles**:
      no persistent history, cookies, cache, or saved passwords; wiped on last
      private window close
- [x] Restore closed tabs (Ctrl+Shift+T), session restore, crash recovery
- [x] Vertical tabs layout option
- [x] Address bar (omnibox): URL detection, search, suggestions (from your
      chosen engine only, toggleable), open-tab/bookmark/history suggestions,
      keyword engines (`@g`, `@d`, `@b`, …), custom engines
- [x] Search engines: Google, Bing, DuckDuckGo, Brave, Startpage, Ecosia,
      Mojeek + custom; default fully configurable
- [x] QR code for the current page (offline QR encoder, no network)
- [x] Downloads manager: progress, pause/resume/cancel, speed/size,
      open/reveal in folder, danger warnings, records
- [x] Bookmarks: folders (nested), star toggle, bookmarks bar with folder
      menus, edit/delete, duplicate detection, Netscape HTML import/export
- [x] History: search, grouped by day, per-entry delete, range delete,
      retention pruning, private tabs never recorded
- [x] Password manager: PBKDF2 (600k rounds) + AES-256-GCM vault, master
      password option, auto-lock, generator, strength/weak/reused analysis,
      autofill, save prompts, CSV import/export, encrypted-at-rest
- [x] Website permissions: camera, mic, location, notifications, clipboard,
      USB, Bluetooth, background sync, downloads — global defaults +
      per-site overrides; sensitive permissions can never be globally allowed
- [x] Developer tools (F12 / Inspect Element, network+console+storage via
      Chromium DevTools), view source
- [x] Settings center (15 sections), settings import/export/reset
- [x] Reader mode, find in page, zoom (per-host persistence), print/PDF,
      save page (MHTML/HTML), screenshot, translate (via provider page),
      fullscreen, PiP via the page's own controls, DevTools

### Privacy
- [x] **Built-in extensions** (bundled, disable-able per site, can't be
      removed): Video Speed Controls ([ ] 0 keys + OSD), Dark Reader Lite
      (per-site dark mode), Consent Banner Hider (hide-only, never clicks),
      Selection Freedom (re-enables copy/right-click)
- [x] **Built-in ad blocker (uBlock Origin style)**: ABP/uBO filter syntax
      engine — `||host^` rules, wildcards, regex filters, `@@` whitelists,
      `$script/$image/$third-party/$domain=` options, `$important`,
      element hiding (`##selector`, `#@#` exceptions); bundled offline
      list + one-click subscriptions (EasyList, EasyPrivacy, Peter Lowe's,
      uBlock filters); per-site pause; stats in the shield counter and
      `browser://adblock`
- [x] Tracker/ads/fingerprinting blocking via bundled curated lists
      (checked locally — no list downloads, no telemetry)
- [x] Third-party cookie blocking (per-site overrides), block-all mode,
      clear-on-exit
- [x] Anti-fingerprinting: light (timing/thread noise) and strict
      (canvas/audio perturbation, plugin hiding) modes
- [x] WebRTC disable policy
- [x] DNT + Global Privacy Control signals
- [x] Popup blocking (user-initiated popups still work)
- [x] Privacy dashboard: trackers/cookies/requests blocked, per-site
      breakdown, protection level, honest limitations statement

### Security
- [x] HTTPS-First upgrade with remembered fallbacks (never silent)
- [x] Certificate errors: **always rejected**; custom warning page with
      details. No bypass path exists.
- [x] Safe browsing: local phishing/malware list; provider lookups require
      explicit consent + user-supplied API key (off by default)
- [x] Download screening: executable warnings, suspicious file types,
      local-AV scan hook, nothing ever auto-executed
- [x] Mixed-content blocking
- [x] Security dashboard: connection state, cert info, download warnings,
      protection settings
- [x] Signed update manifests (Ed25519, key pinning, downgrade refusal) —
      fully offline until you configure a feed

### Productivity / platform
- [x] Dark / light / system theme, six accent colors, UI font size,
      reduced motion, high-contrast borders
- [x] Keyboard-only navigation, visible focus, screen-reader support via Qt
- [x] Cross-platform: Windows 10/11, macOS, Linux

## Run from source

Requirements: Python 3.10+ and QtWebEngine.

```bash
pip install PyQt6 PyQt6-WebEngine cryptography
python main.py                  # normal window
python main.py --private        # private window
python main.py https://example.com
```

## Tests

```bash
python -m unittest discover -s browser/tests -v
```

109 tests cover: privacy blocking decisions, cookie policy, HTTPS-first,
safe browsing, download classification, cert gate, vault crypto
(encrypted-at-rest, master password, auto-lock, CSV roundtrip), storage
(history/bookmarks/downloads), tracker lists, URL detection, QR encoding
(Reed-Solomon syndromes, spec format constants), settings persistence,
session save/restore, crash flag, bookmark HTML roundtrip, extensions
(manifest validation, matching, private-mode gating), permissions policy,
update signature verification (tamper, downgrade, key pinning), and internal
page rendering (XSS escaping, no password leakage).

## Project layout

```
main.py                 entry point
browser/
  constants.py paths.py settings.py storage.py app.py
  core/   privacy.py security.py vault.py downloads.py search.py qr.py
          permissions.py extensions.py session.py updates.py
          bookmarks_import.py
          filterengine.py       (ABP/uBO filter syntax engine)
          adblock.py            (list subscriptions + per-site pause)
          extensions.py         (user scripts; built-ins sync from data/)
  data/   lists.py              (bundled tracker/threat lists)
          abp_builtin.txt       (bundled ad/tracker filter list)
          builtin_extensions/   (Video Speed, Dark Reader, Banner Hider,
                                 Selection Freedom)
  pages/  pages.py handler.py (browser:// internal pages incl. adblock)
  ui/     browser_window.py omnibox.py tab.py dialogs.py style.py
  tests/  test_browser.py test_adblock.py
```

## Privacy guarantees

- All data stays in the platform data directory; no accounts, no sync.
- No telemetry, analytics, crash uploads, or tracking of any kind.
- Update checks are opt-in (empty feed by default) and signature-verified.
- Suggestions go only to your chosen search engine and can be disabled.
- See `PRIVACY.md` and `SECURITY.md` for the full policy.
