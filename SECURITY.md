# Security documentation — browser

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
