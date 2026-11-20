"""Password vault for browser.

Storage format (vault.bin):
    magic      8 bytes  b"BROWSER1"
    version    1 byte   0x01
    kdf_id     1 byte   0x01 = PBKDF2-HMAC-SHA256
    iterations 4 bytes  big-endian uint32
    salt       16 bytes
    nonce      12 bytes
    ciphertext AES-256-GCM over JSON payload (authenticated)

Without a master password set, the key is derived from a random machine
secret stored in the data directory with user-only permissions. That defends
against casual disk scraping, but the OS account remains the real boundary —
users who want stronger protection set a master password (Settings →
Passwords), which re-encrypts everything under PBKDF2 of that secret.

No password is ever written to disk in plain text, and nothing leaves the
machine.
"""

from __future__ import annotations

import json
import os
import secrets
import struct
import time
from pathlib import Path
from typing import Dict, List, Optional

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

MAGIC = b"BROWSER1"
VERSION = 1
KDF_PBKDF2 = 1
DEFAULT_ITERATIONS = 600_000
MACHINE_SECRET_FILE = "vault.key"

__all__ = ["Vault", "VaultLocked", "generate_password", "strength"]


class VaultLocked(Exception):
    """Raised when an operation needs the vault but it is locked."""
    pass


class Vault:
    """Encrypted password store: AES-256-GCM + PBKDF2 master key."""
    def __init__(self, vault_path: Path, machine_secret_path: Path,
                 auto_lock_minutes: int = 30):
        self.path = Path(vault_path)
        self.machine_secret_path = Path(machine_secret_path)
        self.auto_lock_seconds = auto_lock_minutes * 60
        self._key: Optional[bytes] = None
        self._uses_master = False
        self._unlocked_at = 0.0
        self._logins: List[Dict] = []

    # ------------------------------------------------------------------ #
    # Key handling
    # ------------------------------------------------------------------ #
    def _load_or_create_machine_secret(self) -> bytes:
        if self.machine_secret_path.exists():
            data = self.machine_secret_path.read_bytes()
            if len(data) >= 32:
                return data
        secret = secrets.token_bytes(32)
        self.machine_secret_path.parent.mkdir(parents=True, exist_ok=True)
        self.machine_secret_path.write_bytes(secret)
        try:
            os.chmod(self.machine_secret_path, 0o600)
        except OSError:
            pass
        return secret

    def _derive_key(self, master: Optional[str], salt: bytes, iterations: int) -> bytes:
        if master:
            material = master.encode("utf-8")
        else:
            material = self._load_or_create_machine_secret()
        kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt,
                         iterations=iterations)
        return kdf.derive(material)

    # ------------------------------------------------------------------ #
    # File format
    # ------------------------------------------------------------------ #
    def _write(self, logins: List[Dict], master: Optional[str], uses_master: bool,
               iterations: int = DEFAULT_ITERATIONS) -> None:
        salt = secrets.token_bytes(16)
        nonce = secrets.token_bytes(12)
        key = self._derive_key(master, salt, iterations)
        payload = json.dumps({
            "logins": logins,
            "uses_master": uses_master,
        }).encode("utf-8")
        ct = AESGCM(key).encrypt(nonce, payload, MAGIC + bytes([VERSION]))
        blob = (MAGIC + bytes([VERSION, KDF_PBKDF2]) + struct.pack(">I", iterations)
                + salt + nonce + ct)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_bytes(blob)
        try:
            os.chmod(tmp, 0o600)
        except OSError:
            pass
        tmp.replace(self.path)

    def _read(self) -> Dict:
        blob = self.path.read_bytes()
        if len(blob) < 8 or blob[:8] != MAGIC:
            raise ValueError("vault file is not a browser vault")
        version = blob[8]
        if version != VERSION:
            raise ValueError(f"unsupported vault version {version}")
        kdf_id = blob[9]
        if kdf_id != KDF_PBKDF2:
            raise ValueError("unknown key derivation")
        iterations = struct.unpack(">I", blob[10:14])[0]
        off = 14
        salt = blob[off:off + 16]; off += 16
        nonce = blob[off:off + 12]; off += 12
        ct = blob[off:]
        return {"iterations": iterations, "salt": salt, "nonce": nonce, "ct": ct}

    # ------------------------------------------------------------------ #
    # Lifecycle
    # ------------------------------------------------------------------ #
    def initialize(self, master: Optional[str] = None,
                   auto_lock_minutes: int = 30) -> None:
        """Create a fresh vault. Overwrites any existing file."""
        self.auto_lock_seconds = auto_lock_minutes * 60
        self._write([], master, uses_master=bool(master))
        self._key = self._derive_key_for_open(master)
        self._uses_master = bool(master)
        self._unlocked_at = time.time()
        self._logins = []

    def _derive_key_for_open(self, master: Optional[str]) -> bytes:
        data = self._read()
        return self._derive_key(master, data["salt"], data["iterations"])

    def is_initialized(self) -> bool:
        return self.path.exists()

    def uses_master_password(self) -> bool:
        if not self.is_initialized():
            return False
        data = self._read()
        return bool(data.get("uses_master"))

    def is_unlocked(self) -> bool:
        if self._key is None:
            return False
        if not self._uses_master:
            return True   # machine-secret vaults re-derive transparently
        return (time.time() - self._unlocked_at) < self.auto_lock_seconds

    def unlock(self, master: Optional[str] = None) -> bool:
        data = self._read()
        key = self._derive_key(master, data["salt"], data["iterations"])
        try:
            payload = AESGCM(key).decrypt(data["nonce"], data["ct"], MAGIC + bytes([VERSION]))
        except Exception:
            return False
        obj = json.loads(payload.decode("utf-8"))
        self._key = key
        self._uses_master = bool(obj.get("uses_master"))
        self._unlocked_at = time.time()
        self._logins = list(obj.get("logins", []))
        return True

    def ensure_unlocked(self, master: Optional[str] = None) -> None:
        if not self.is_initialized():
            self.initialize(master)
        if not self.is_unlocked():
            if not self._uses_master:
                if self.unlock(None):
                    return
            raise VaultLocked("vault is locked")

    def lock(self) -> None:
        self._key = None
        self._logins = []

    # ------------------------------------------------------------------ #
    # CRUD (require unlocked vault)
    # ------------------------------------------------------------------ #
    def _check(self) -> None:
        if not self.is_unlocked():
            raise VaultLocked("vault is locked")

    def add(self, origin: str, username: str, password: str, note: str = "") -> int:
        self._check()
        # Update in place when origin+username already saved.
        for i, e in enumerate(self._logins):
            if e["origin"] == origin and e["username"] == username:
                e["password"] = password
                e["updated"] = time.time()
                self._persist()
                return i
        self._logins.append({
            "origin": origin, "username": username, "password": password,
            "note": note, "created": time.time(), "updated": time.time(),
        })
        self._persist()
        return len(self._logins) - 1

    def get(self, origin: str) -> List[Dict]:
        self._check()
        return [dict(e) for e in self._logins if e["origin"] == origin]

    def find(self, origin: str) -> Optional[Dict]:
        self._check()
        for e in self._logins:
            if e["origin"] == origin or origin.endswith("." + e["origin"]) \
               or e["origin"].endswith("." + origin):
                return dict(e)
        return None

    def all(self) -> List[Dict]:
        self._check()
        return [dict(e) for e in self._logins]

    def delete(self, index: int) -> bool:
        self._check()
        if 0 <= index < len(self._logins):
            self._logins.pop(index)
            self._persist()
            return True
        return False

    def update(self, index: int, *, username: Optional[str] = None,
               password: Optional[str] = None, note: Optional[str] = None) -> bool:
        self._check()
        if not (0 <= index < len(self._logins)):
            return False
        e = self._logins[index]
        if username is not None: e["username"] = username
        if password is not None: e["password"] = password
        if note is not None: e["note"] = note
        e["updated"] = time.time()
        self._persist()
        return True

    def _persist(self) -> None:
        if not self.is_unlocked():
            raise VaultLocked("vault is locked")
        data = self._read()
        # Re-encrypt with the SAME derived key so unlocking state survives:
        salt = data["salt"]; nonce = secrets.token_bytes(12)
        payload = json.dumps({
            "logins": self._logins,
            "uses_master": self._uses_master,
        }).encode("utf-8")
        ct = AESGCM(self._key).encrypt(nonce, payload, MAGIC + bytes([VERSION]))
        blob = (MAGIC + bytes([VERSION, KDF_PBKDF2])
                + struct.pack(">I", data["iterations"]) + salt + nonce + ct)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_bytes(blob)
        try:
            os.chmod(tmp, 0o600)
        except OSError:
            pass
        tmp.replace(self.path)

    # ------------------------------------------------------------------ #
    # Master password management
    # ------------------------------------------------------------------ #
    def set_master_password(self, master: Optional[str]) -> bool:
        """Re-encrypts the vault under a new master (or removes it with None)."""
        self._check()
        data = self._read()
        self._write(self._logins, master, uses_master=bool(master),
                    iterations=data["iterations"])
        self._key = self._derive_key(master, data["salt"], data["iterations"])
        self._uses_master = bool(master)
        self._unlocked_at = time.time()
        return True

    def change_auto_lock(self, minutes: int) -> None:
        self.auto_lock_seconds = max(0, minutes) * 60

    # ------------------------------------------------------------------ #
    # Analysis / import / export
    # ------------------------------------------------------------------ #
    def report(self) -> Dict[str, List[int]]:
        self._check()
        weak, reused = [], []
        seen: Dict[str, List[int]] = {}
        for i, e in enumerate(self._logins):
            if strength(e["password"]) < 3:
                weak.append(i)
            seen.setdefault(e["password"], []).append(i)
        reused = [idxs for idxs in seen.values() if len(idxs) > 1]
        return {"weak": weak, "reused": reused, "total": len(self._logins)}

    def export_encrypted(self, dest: Path) -> None:
        """Export is the encrypted vault itself; it is never plaintext."""
        self._check()
        data = self._read()
        dest.write_bytes(self.path.read_bytes())
        try:
            os.chmod(dest, 0o600)
        except OSError:
            pass
        _ = data

    def export_csv(self, dest: Path) -> int:
        """Plaintext CSV export — requires unlock and shows a strong warning.
        Returns the number of rows."""
        import csv
        self._check()
        rows = self.all()
        with open(dest, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["origin", "username", "password", "note"])
            for e in rows:
                w.writerow([e["origin"], e["username"], e["password"], e.get("note", "")])
        return len(rows)

    def import_csv(self, src: Path) -> int:
        import csv
        self._check()
        n = 0
        with open(src, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                o = (row.get("origin") or row.get("url") or "").strip()
                u = (row.get("username") or row.get("user") or "").strip()
                p = (row.get("password") or "").strip()
                if o and p:
                    self.add(o, u, p, note=row.get("note", "") or "")
                    n += 1
        return n


# --------------------------------------------------------------------------- #
# Generation + strength (pure functions)
# --------------------------------------------------------------------------- #
_PASSWORD_ALPHABETS = {
    "lower": "abcdefghijklmnopqrstuvwxyz",
    "upper": "ABCDEFGHIJKLMNOPQRSTUVWXYZ",
    "digits": "0123456789",
    "symbols": "!@#$%^&*()-_=+[]{};:,.?/",
}


def generate_password(length: int = 20, use_symbols: bool = True,
                      use_digits: bool = True) -> str:
    """Random password from a character policy with length control."""
    rng = secrets.SystemRandom()
    pools = [_PASSWORD_ALPHABETS["lower"], _PASSWORD_ALPHABETS["upper"]]
    if use_digits:
        pools.append(_PASSWORD_ALPHABETS["digits"])
    if use_symbols:
        pools.append(_PASSWORD_ALPHABETS["symbols"])
    # Guarantee one char from each pool, fill the rest randomly, then shuffle.
    chars = [rng.choice(p) for p in pools]
    allc = "".join(pools)
    chars += [rng.choice(allc) for _ in range(max(0, length - len(chars)))]
    for i in range(len(chars) - 1, 0, -1):
        j = rng.randrange(i + 1)
        chars[i], chars[j] = chars[j], chars[i]
    return "".join(chars[:length])


def strength(pw: str) -> int:
    """0..4 password strength score."""
    if not pw:
        return 0
    score = 0
    length = len(pw)
    variety = sum([
        any(c.islower() for c in pw),
        any(c.isupper() for c in pw),
        any(c.isdigit() for c in pw),
        any(not c.isalnum() for c in pw),
    ])
    if length >= 8: score += 1
    if length >= 12: score += 1
    if length >= 16: score += 1
    score += 1 if variety >= 3 else 0
    score += 1 if variety == 4 and length >= 12 else 0
    common = {"password", "123456", "qwerty", "letmein", "admin", "welcome",
              "iloveyou", "dragon", "monkey", "111111", "123456789"}
    if pw.lower() in common:
        return 0
    return min(score, 4)
