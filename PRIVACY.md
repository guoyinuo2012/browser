# Privacy policy and architecture — browser

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
