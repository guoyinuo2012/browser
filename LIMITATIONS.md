# Known limitations — browser

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
