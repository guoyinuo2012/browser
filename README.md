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
- [x] **Modern three-dots menu**: passwords/autofill, history (with recent
      pages), downloads, bookmarks and lists, tab groups, extensions,
      delete-data, zoom row (−/+ %/fullscreen), print, Google Lens,
      translate, find-and-edit, save/share (copy link, email link, QR),
      more tools, help, settings, exit
- [x] **Page context menu (right-click)**: search selection with your
      engine, **search image with Google Lens**, open image/link in new
      tab, copy image/link address, save/print, inspect, view source

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

## Download the ready-made build

A standalone Windows build (no Python needed — unzip and run) is attached to
the v1.0.0 release: <https://github.com/guoyinuo2012/browser/releases/latest>
(`browser-1.0.0-standalone.zip`, ~228 MB compressed).

## Launching

After building (or unzipping the standalone package), start the browser
from the launcher files in the app folder:

| File | What it does |
|---|---|
| `browser.exe` | The browser itself (double-click) |
| `Start browser.bat` | Launches with a console window; forwards arguments |
| `Start browser (silent).vbs` | Launches with no console flash; forwards arguments |
| `Start private window.bat` | Launches directly into a private window |

These use relative paths, so the folder can be moved anywhere and the
launchers keep working.

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

117 tests cover: privacy blocking decisions, cookie policy, HTTPS-first,
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
  tests/  test_browser.py test_adblock.py test_builtin_extensions.py
  engine_probe.py           (sandbox-safe engine startup)
```

---

## Privacy guarantees

- All data stays in the platform data directory; no accounts, no sync.
- No telemetry, analytics, crash uploads, or tracking of any kind.
- Update checks are opt-in (empty feed by default) and signature-verified.
- Suggestions go only to your chosen search engine and can be disabled.
- Full details in the *Privacy policy* section below.

---

# Privacy policy and architecture

Last updated: v1.0.0

## What browser collects

**Nothing.** browser has no telemetry, no analytics, no crash reporting, no
advertising, no accounts, no cloud services, and no data selling. There is
no code path that uploads your data, and no "phone home" at startup.

## What leaves your device

Only what you explicitly do:

| Action | Who receives data |
|---|---|
| Loading a website | That website (and its servers) — as with any browser |
| Typing in the address bar | Your chosen search engine, **only** if omnibox suggestions are enabled (Settings → Privacy). Disable to send nothing until you press Enter |
| Safe Browsing provider lookups | **Nobody, by default.** Local lists are checked offline. A provider lookup requires typing an API key AND checking an explicit consent box |
| Enabling/updating an ad-block subscription | The list publisher you chose (EasyList, EasyPrivacy, etc.), over HTTPS, only when you enable or update it. The request contains nothing but the fetch itself — no identifiers, no browsing history |
| Update checks | Your configured update feed, only if you configure one |
| Translating a page | The translation provider you chose |
| Built-in extensions | Nobody. They are bundled JavaScript that runs only inside the page; they contain no network calls at all (test-verified) |

## What is stored, and where

Everything lives in the platform data directory:

- Windows: `%APPDATA%\browser`
- macOS: `~/Library/Application Support/browser`
- Linux: `$XDG_DATA_HOME/browser` (default `~/.local/share/browser`)

| File / store | Contents | Protection |
|---|---|---|
| `settings.json` | Preferences | Plaintext (no secrets) |
| `store.db` | History, bookmarks, download records | Plaintext SQLite (local only) |
| `vault.bin` | Saved passwords | AES-256-GCM, PBKDF2-SHA256 (600k rounds) |
| `vault.key` | Machine-generated key (no master password set) | Mode 0600 file; see honest limitation below |
| profile/ | Chromium profile (cookies, cache) | OS user permissions |

Private windows use **off-the-record** Chromium profiles: cookies, cache and
history never touch the disk, and passwords are never saved or offered from
private sessions. When the last private window closes, in-memory state is
discarded and the profile object is destroyed.

## Blocking lists

Tracker, ad, and fingerprinting lists are bundled inside the application
(`browser/data/lists.py`) and evaluated **locally on every request** before a
connection is made. browser does not download filter lists by default and
sends nothing to list maintainers.

## Fingerprinting defenses

- Light: high-resolution timers rounded, hardware/thread counts coarse.
- Strict: canvas and audio read-back perturbation, plugin enumeration
  reduced, canvas reads gated.

**Honest limitation:** fingerprinting defenses reduce the surface but cannot
defeat all techniques (e.g. TLS fingerprinting, server-side heuristics).
browser does not claim anonymity.

## Honest limitation summary

No browser — including this one — makes you anonymous. Your IP address, ISP,
account logins, and advanced fingerprinting can still identify you. For
stronger anonymity use a reputable VPN or the Tor network. browser is
transparent about this in its privacy dashboard.

## Clearing data

Settings → Privacy → *Clear browsing data* (or Ctrl+Shift+Del): history,
cookies/site data, cache, download records — with time ranges. Passwords can
be deleted individually or the vault removed entirely (delete `vault.bin`).


---

# Security documentation

## Security architecture

### Process model
Rendering runs in Chromium's multi-process architecture: each site gets an
isolated renderer process; the network stack and GPU are separate. A crash
in one tab cannot corrupt browser's own state; browser detects renderer
terminations and offers recovery in the affected tab only.

### Certificate validation
- TLS validation is performed by Chromium's stack (OS trust store).
- Certificate errors **always** trigger `rejectCertificate`. There is no
  override path in the codebase: `CertGate.ALLOW_OVERRIDE = False` is
  immutable and no UI offers "proceed anyway". Users see a warning page with
  the reason and can only go back or retry.

### HTTPS-First
Typed and link navigations to `http://` are upgraded to `https://` before
load. If a host fails TLS, it is remembered for 24h so an explicit manual
retry can use plain http (never automatic, visible in the security page).
Local, private, and IP hosts are never upgraded.

### Safe browsing
- Default: bundled local threat list (phishing/malware domains), evaluated
  offline for every main-frame navigation. Matches are blocked with a
  warning page (`browser://blocked`).
- Provider lookups (e.g. Google Safe Browsing) require: explicit consent
  checkbox **and** a user-supplied API key. Default: off. Browsing history
  is never sent anywhere without this double opt-in.

### Downloads
- Filenames are classified before saving: executables/scripts/disk images →
  strong warning dialog; archives/office docs → caution note.
- browser never executes downloads automatically.
- Optional local antivirus hook: user-defined command template (`%p`) run on
  completion (Settings → Downloads). Runs locally only.
- "file-hosting service" sources are flagged in download records.

### Password vault
- PBKDF2-HMAC-SHA256, 600,000 iterations, 16-byte random salt per write.
- AES-256-GCM (authenticated encryption) with the vault header bound as
  associated data (tamper detection).
- Optional master password re-derives the key from the secret; without it,
  a machine key (0600 file) is used. The OS user account is the real
  boundary in that case — the master password is recommended and advertised
  in Settings → Passwords.
- Auto-lock after configurable inactivity (default 30 min).
- Weak/reused password detection; CSV export demands confirmation because
  CSV is plaintext by definition.

### Extensions
- User-script extensions only. Installation validates the manifest,
  rejects unknown permissions, and requires explicit approval for
  `network`/`clipboard`/`private` capabilities. Private-window execution is
  separately approved per extension and revocable.
- Extensions do not get native API access; they get page-context JavaScript
  only.

### Updates
- Update manifests must be Ed25519-signed; the signing key is pinned on
  first approval and later key changes are refused loudly.
- Version comparison refuses downgrades; package hashes verified before
  recommendation. Nothing is installed automatically, ever.

### Permissions
- Camera, microphone, location, screen capture, clipboard, USB, Bluetooth:
  default "ask", per-site rules, and a structural rule that these can never
  be globally "allow" — the decision is per-site and user-confirmed.

## Reporting

Security issues in browser's own code should be disclosed responsibly to the
project maintainer. Issues in Chromium itself belong to the upstream project.


---

# Building and packaging

*Run from source is covered above. Environment variables:*

| Variable | Purpose |
|---|---|
| `BROWSER_DATA_DIR` | Override data directory (tests, portable use) |
| `BROWSER_DOWNLOADS_DIR` | Override default download directory |
| `BROWSER_PROXY` | Proxy for the engine, e.g. `socks5://127.0.0.1:9050` |
| `QTWEBENGINE_CHROMIUM_FLAGS` | Advanced: extra Chromium flags |

---

## Building a distributable

### Windows (single-folder or installer)

```bash
pip install pyinstaller
pyinstaller main.py --name browser --windowed --noconfirm ^
  --collect-all PyQt6 --collect-all PyQt6.QtWebEngineCore ^
  --collect-all PyQt6.QtWebEngineWidgets --collect-submodules browser
```

Output in `dist/browser/browser.exe`. Wrap with Inno Setup / NSIS for an
installer and code-sign the binary with your certificate (`signtool`).
Code-signing is required for SmartScreen trust; without it Windows shows the
standard unsigned-binary warning.

#### macOS

```bash
pyinstaller main.py --name browser --windowed --collect-all PyQt6 \
  --collect-submodules browser
codesign --deep --force --sign "Developer ID Application: YOUR NAME" dist/browser.app
```

For distribution outside the App Store, notarize with `xcrun notarytool`.
PyQt6's WebEngine framework must be inside the bundle (PyInstaller
`--collect-all PyQt6` handles this).

#### Linux

```bash
pyinstaller main.py --name browser --windowed --collect-all PyQt6 \
  --collect-submodules browser
```

Or package as Flatpak/AppImage. AppImage tooling can wrap the PyInstaller
output. QtWebEngine needs system GPU libraries at runtime
(libEGL, libGL, fontconfig).

## Update channel (optional)

browser never phones home. To operate your own update channel:

1. Host a manifest JSON:
   ```json
   {
     "version": "1.1.0",
     "url": "https://example.com/downloads/browser-1.1.0.exe",
     "sha256": "<hex of package>",
     "channel": "stable",
     "notes": "…",
     "pubkey": "<ed25519 public key hex>"
   }
   ```
2. Sign it: the signature field must be an Ed25519 signature (hex) over the
   canonical JSON of all fields except `signature`, sorted keys, compact
   separators (see `browser/core/updates.py`).
3. Users paste the feed URL in Settings → Advanced → Updates. The first
   check pins your key; later key changes are rejected.

`browser/tools/make_update_manifest.py` shows the exact signing procedure.

---

# Known limitations

browser is honest about what it cannot do. Every limitation below is a
consequence of the architecture, not an omission of effort.

## Engine-level limitations (inherited from QtWebEngine/Chromium)

1. **No Chrome/Firefox extension compatibility.** QtWebEngine exposes no
   WebExtension APIs. browser ships a user-script extension system instead
   and never claims WebExtension compatibility.
2. **No per-tab audio API.** Chromium/Qt provides no public per-page volume
   control; mute is implemented by muting media elements via script.
3. **Site isolation is Chromium-managed.** The engine provides process
   isolation; browser cannot tune its granularity.
4. **WebGPU support** depends on the Chromium build shipped by Qt; not
   guaranteed on all platforms.
5. **Proxy changes require restart.** Chromium reads proxy configuration at
   engine startup.
6. **WebRTC "disable" mode** is enforced by script (page-level
   RTCPeerConnection stub). Engine-internal WebRTC usage cannot be fully
   disabled through Qt's public API.
7. **Search suggestions** are fetched from your chosen engine when enabled.
   Brave Search and Startpage do not expose a public suggestion endpoint in
   this build (suggestions silently disabled for them).
8. **Built-in extensions are user scripts.** They run inside pages with
   the permissions listed on `browser://extensions` and send nothing
   anywhere, but they are not WebExtensions: no background workers, no
   cross-tab APIs, no Chrome/Firefox compatibility. Consent Banner Hider
   hides banners only — it never clicks "accept" on your behalf, so some
   sites may require manual interaction before content unlocks.
9. **Ad blocker vs. full uBlock Origin.** The built-in engine covers the
   practical core of ABP/uBO syntax (network filters with options,
   exceptions, `$important`, element hiding, regex filters). It does not
   support procedural cosmetic filters (`:has-text(...)`, `#?#` snippets),
   `$redirect`/`$csp`/`$removeparam`/`$cookie` modifiers, `$badfilter`
   expansion, or filter-list scriptlets. Rules using unsupported features
   are skipped (the list reports the skip count), never mis-applied.
   Cosmetic hiding is applied after page load (uBO-Lite style), so hidden
   ad placeholders may flash briefly before they disappear.

## Anti-fingerprinting limitations

- Defenses reduce the attack surface but cannot guarantee uniqueness
  prevention (TLS fingerprinting and server-side analysis remain).
- Strict mode perturbs canvas/audio read-back; pages that draw to canvas
  and read it back for legitimate rendering may see 1-bit noise.

## Password vault

- Without a master password, the vault is encrypted with a machine-local
  key. This protects against casual disk scraping but the OS account
  remains the true boundary. browser recommends enabling the master
  password (Settings → Passwords).
- CSV export is plaintext by necessity; the UI warns loudly and requires
  confirmation.

## Platform notes

- **Windows**: registering as the default browser requires user action in
  the OS settings panel (Settings → General → Default browser opens it).
- **macOS/Linux**: same — default-browser registration is OS-level.
- The official Python `PyQt6-WebEngine` wheels are the supported
  distribution channel; system-package builds of Qt may differ.
- **Sandboxed/CI environments**: Chromium fails fast when the surrounding
  process environment (e.g. Windows job-object limits in test sandboxes)
  denies its GPU/IPC needs. browser detects this with a pre-flight probe,
  tries GPU-less/no-sandbox/single-process fallbacks automatically, and if
  none are permitted exits cleanly (code 2) with an explanation instead of
  crashing silently. On a normal desktop the probe is skipped entirely and
  adds no startup cost.

## Not implemented (and not claimed)

- Chrome Web Store / Firefox Add-ons compatibility — see above.
- Built-in translation engine — translation opens the provider's page.
- Cloud sync — intentionally absent (privacy-first design).
- Tor integration — out of scope; use Tor Browser for that threat model.
