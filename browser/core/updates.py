"""Update checking for browser.

Security model:
  * Update feeds are user-configured URLs serving a signed JSON manifest.
  * Manifest fields: version, url, sha256, signature (Ed25519, hex),
    pubkey (Ed25519 public key, hex), channel, notes.
  * The manifest signature must verify against the *pinned* public key in
    the manifest itself AND the pinned key must match the key stored in the
    local trust file the first time the user approves a feed. This prevents
    key substitution on later checks.
  * Version comparison refuses downgrades.
  * Nothing is installed automatically: the user downloads and runs the
    installer. browser verifies the signature and hash before recommending.

Default state: update checking is enabled but the feed URL is empty, so no
network requests occur until the user configures a trusted feed.
"""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Optional, Tuple

TRUST_FILE = "update_trust.json"


def _load_trust(data_dir: Path) -> dict:
    p = data_dir / TRUST_FILE
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def _save_trust(data_dir: Path, trust: dict) -> None:
    p = data_dir / TRUST_FILE
    p.write_text(json.dumps(trust, indent=2), encoding="utf-8")


def parse_manifest(text: bytes) -> Tuple[Optional[dict], str]:
    """Returns (manifest, error)."""
    try:
        m = json.loads(text.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None, "manifest is not valid JSON"
    required = ("version", "url", "sha256", "signature", "pubkey")
    missing = [k for k in required if not m.get(k)]
    if missing:
        return None, f"manifest missing fields: {missing}"
    return m, ""


def verify_manifest(manifest: dict, trust: dict) -> Tuple[bool, str]:
    """Verify signature + trust pinning + downgrade protection."""
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

    pubkey_hex = manifest.get("pubkey", "")
    signature_hex = manifest.get("signature", "")
    try:
        pubkey_bytes = bytes.fromhex(pubkey_hex)
        signature = bytes.fromhex(signature_hex)
    except ValueError:
        return False, "malformed pubkey or signature encoding"
    if len(pubkey_bytes) != 32:
        return False, "public key must be Ed25519 (32 bytes)"

    pinned = trust.get("pubkey")
    if pinned and pinned != pubkey_hex:
        return False, ("update feed key changed since you trusted it. "
                       "If this is intentional, re-approve the feed in Settings → Advanced.")

    signed = json.dumps(
        {k: manifest[k] for k in sorted(manifest) if k != "signature"},
        sort_keys=True, separators=(",", ":")).encode("utf-8")
    try:
        Ed25519PublicKey.from_public_bytes(pubkey_bytes).verify(signature, signed)
    except InvalidSignature:
        return False, "signature verification failed — update rejected"

    current = _version_tuple(_CURRENT_VERSION)
    new = _version_tuple(manifest.get("version", ""))
    if new <= current:
        return False, f"version {manifest.get('version')} is not newer than {_CURRENT_VERSION}"
    return True, "update available and signature valid"


_CURRENT_VERSION = "1.0.0"


def set_current_version(v: str) -> None:
    """Feed the verifier the running app version (downgrade checks)."""
    global _CURRENT_VERSION
    _CURRENT_VERSION = v


def _version_tuple(v: str):
    try:
        return tuple(int(x) for x in str(v).split(".")[:4])
    except ValueError:
        return (0,)


def verify_package_hash(path: Path, expected_sha256: str) -> Tuple[bool, str]:
    """Check a downloaded update package against the manifest hash."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    actual = h.hexdigest().lower()
    if actual != expected_sha256.lower():
        return False, f"package hash mismatch ({actual[:16]}…)"
    return True, "package verified"


def approve_feed(data_dir: Path, pubkey_hex: str) -> None:
    """Pin an update feed's signing key after user confirmation."""
    _save_trust(data_dir, {"pubkey": pubkey_hex, "approved": time.time()})


def feed_trusted(data_dir: Path) -> bool:
    """True when the feed URL has a pinned signing key."""
    return bool(_load_trust(data_dir).get("pubkey"))
