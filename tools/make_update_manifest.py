"""Tool to create signed update manifests for browser.

Usage:
    python tools/make_update_manifest.py \
        --private-key key.hex --version 1.1.0 \
        --url https://example.com/browser-1.1.0.exe \
        --sha256 <package sha256 hex> \
        --out update.json

The private key is generated on first use (32 random bytes, hex file).
"""

from __future__ import annotations

import argparse
import json
import secrets
import sys
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


def canonical(manifest: dict) -> bytes:
    payload = {k: manifest[k] for k in sorted(manifest) if k != "signature"}
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--private-key", required=False, help="hex file; generated if missing")
    ap.add_argument("--version", required=True)
    ap.add_argument("--url", required=True)
    ap.add_argument("--sha256", required=True)
    ap.add_argument("--channel", default="stable")
    ap.add_argument("--notes", default="")
    ap.add_argument("--out", default="update.json")
    args = ap.parse_args()

    key_path = Path(args.private_key or "update-signing-key.hex")
    if key_path.exists():
        sk = Ed25519PrivateKey.from_private_bytes(bytes.fromhex(key_path.read_text().strip()))
    else:
        sk = Ed25519PrivateKey.generate()
        key_path.write_text(sk.private_bytes_raw().hex())
        print(f"Generated new signing key: {key_path} (keep it secret!)")

    manifest = {
        "version": args.version,
        "url": args.url,
        "sha256": args.sha256.lower(),
        "channel": args.channel,
        "notes": args.notes,
        "pubkey": sk.public_key().public_bytes_raw().hex(),
    }
    manifest["signature"] = sk.sign(canonical(manifest)).hex()
    Path(args.out).write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"Wrote signed manifest: {args.out}")
    print("Feed URL to configure in browser: the URL serving this JSON file.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
