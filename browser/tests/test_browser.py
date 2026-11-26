"""Test suite for browser (standard library unittest).

Run:  python -m unittest discover -s browser/tests -v
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

_TMP = tempfile.mkdtemp(prefix="browser-tests-")
os.environ["BROWSER_DATA_DIR"] = _TMP

from browser.settings import Settings
from browser.storage import Store
from browser.data import lists
from browser.core.privacy import Counters, PrivacyPolicy, PrivacyInterceptor, fingerprint_script, webrtc_script
from browser.core.security import HTTPSFirstUpgrader, SafeBrowsing, DownloadScreening, CertGate
from browser.core.vault import Vault, generate_password, strength, VaultLocked
from browser.core.search import normalize_input, looks_like_url, parse_suggestions_osjson, BUILTIN_ENGINES
from browser.core.qr import encode, to_svg, format_bits, version_bits, rs_encode, rs_syndromes
from browser.core.session import snapshot, save, load, crashed_last_run, mark_clean_exit
from browser.core.bookmarks_import import export_bookmarks_html, import_bookmarks_html
from browser.pages import pages
from browser.ui.tab import WebTab
from browser.core.extensions import ExtensionManager
from browser.core.permissions import PermissionManager
from browser.core import updates
from browser import pages


def fresh_settings(tmp: Path) -> Settings:
    return Settings(tmp / "settings.json")


class PrivacyEngineTests(unittest.TestCase):
    def setUp(self):
        self.c = Counters()
        self.p = PrivacyPolicy()
        self.i = PrivacyInterceptor(self.c, self.p)

    def test_internal_scheme_never_blocked(self):
        self.assertFalse(self.i.decide("browser", "/", "browser", ""))

    def test_tracker_domains_blocked(self):
        for host in ("www.google-analytics.com", "connect.facebook.net",
                     "doubleclick.net", "hotjar.com", "clarity.ms"):
            self.assertTrue(self.i.decide(host, "/x.js", "https", "site.com"),
                            f"{host} should be blocked")

    def test_tracker_paths_blocked_on_first_party(self):
        self.assertTrue(self.i.decide("example.com", "/gtag/js?id=G-X", "https", "example.com"))

    def test_normal_traffic_allowed(self):
        self.assertFalse(self.i.decide("example.com", "/", "https", "example.com"))
        self.assertFalse(self.i.decide("cdn.example.com", "/app.js", "https", "example.com"))

    def test_custom_block_and_allow(self):
        self.p.custom_block = frozenset({"evil.example"})
        self.assertTrue(self.i.decide("evil.example", "/", "https", "site.com"))
        self.p.custom_allow = frozenset({"trusted-tracker.example"})
        self.p.block_trackers = True
        # domain is in list but allowed
        self.p.custom_allow = frozenset({"doubleclick.net"})
        self.assertFalse(self.i.decide("doubleclick.net", "/", "https", "site.com"))

    def test_third_party_cookie_blocking(self):
        self.assertFalse(self.i.cookie_allowed("tracker.com", "site.com", True))
        self.assertTrue(self.i.cookie_allowed("site.com", "site.com", False))

    def test_per_site_cookie_override(self):
        self.p.custom_allow = frozenset({"site.com"})
        self.assertTrue(self.i.cookie_allowed("third.com", "site.com", True))

    def test_block_all_cookies(self):
        self.p.block_all_cookies = True
        self.assertFalse(self.i.cookie_allowed("site.com", "site.com", False))

    def test_counters(self):
        self.i.decide("doubleclick.net", "/", "https", "site.com")
        self.i.cookie_allowed("t.com", "site.com", True)
        t, c, ads, r, sites = self.c.snapshot()
        self.assertEqual(t, 1)
        self.assertEqual(c, 1)
        self.assertEqual(sites.get("site.com"), 2)

    def test_fingerprint_scripts(self):
        self.assertTrue("hardwareConcurrency" in fingerprint_script("light"))
        self.assertTrue("getImageData" in fingerprint_script("strict"))
        self.assertEqual(fingerprint_script("off"), "")
        self.assertIn("RTCPeerConnection", webrtc_script("disable"))
        self.assertEqual(webrtc_script("default"), "")

    def test_protection_levels(self):
        s = fresh_settings(Path(_TMP) / f"s{time.time()}.json")
        changed = lists.apply_protection_level("standard", s)
        self.assertIn("privacy.block_third_party_cookies", changed)
        self.assertIn("security.https_first", changed)
        self.assertEqual(s.get("privacy.anti_fingerprinting"), "off")
        self.assertFalse(s.get("security.https_first"))
        lists.apply_protection_level("strict", s)
        self.assertEqual(s.get("privacy.anti_fingerprinting"), "strict")
        self.assertTrue(s.get("security.https_first"))
        self.assertTrue(s.get("privacy.block_third_party_cookies"))


class SecurityEngineTests(unittest.TestCase):
    def test_https_first_upgrade(self):
        u = HTTPSFirstUpgrader(True)
        self.assertEqual(u.upgrade("http://example.com/page"), "https://example.com/page")
        self.assertEqual(u.upgrade("https://example.com"), "https://example.com")

    def test_localhost_not_upgraded(self):
        u = HTTPSFirstUpgrader(True)
        self.assertEqual(u.upgrade("http://localhost:8080/x"), "http://localhost:8080/x")
        self.assertEqual(u.upgrade("http://127.0.0.1/x"), "http://127.0.0.1/x")
        self.assertEqual(u.upgrade("http://192.168.1.10/x"), "http://192.168.1.10/x")

    def test_fallback_after_failure(self):
        u = HTTPSFirstUpgrader(True)
        u.record_failure("https://broken.example")
        self.assertEqual(u.upgrade("http://broken.example"), "http://broken.example")
        self.assertNotEqual(u.upgrade("http://other.example"), "http://other.example")

    def test_safe_browsing_local(self):
        sb = SafeBrowsing(True)
        self.assertIsNotNone(sb.check("https://fake.paypal-secure-login.net/x"))
        self.assertIsNone(sb.check("https://example.com"))
        self.assertIsNotNone(sb.check_download_url("https://cdn.discordapp.com/x.zip"))

    def test_safe_browsing_no_consent_no_lookup(self):
        sb = SafeBrowsing(True, consent=False, api_key="")
        # must never make network calls; just verify it returns local decisions
        self.assertIsNone(sb.check("https://unknown.example"))

    def test_download_classification(self):
        self.assertEqual(DownloadScreening.classify("setup.exe"), "danger")
        self.assertEqual(DownloadScreening.classify("installer.msi"), "danger")
        self.assertEqual(DownloadScreening.classify("archive.zip"), "warn")
        self.assertEqual(DownloadScreening.classify("photo.png"), "")
        self.assertIn("never", DownloadScreening.message("danger", "x.exe").lower())

    def test_cert_gate_never_bypasses(self):
        self.assertFalse(CertGate.ALLOW_OVERRIDE)
        self.assertIn("certificate", CertGate.describe(-202).lower())


class VaultTests(unittest.TestCase):
    def setUp(self):
        self.dir = Path(_TMP) / "vault-tests"
        self.dir.mkdir(exist_ok=True)

    def _vault(self, name="v"):
        return Vault(self.dir / f"{name}.bin", self.dir / f"{name}.key")

    def test_encrypted_at_rest(self):
        v = self._vault("a")
        v.initialize()
        v.add("example.com", "alice", "super-secret-password-123")
        raw = (self.dir / "a.bin").read_bytes()
        self.assertNotIn(b"super-secret", raw)
        self.assertNotIn(b"alice", raw)
        self.assertEqual(raw[:8], b"BROWSER1")

    def test_roundtrip_and_find(self):
        v = self._vault("b")
        v.initialize()
        v.add("example.com", "alice", "pw1")
        v2 = Vault(self.dir / "b.bin", self.dir / "b.key")
        self.assertTrue(v2.unlock(None))
        self.assertEqual(v2.find("www.example.com")["username"], "alice")
        self.assertEqual(len(v2.get("example.com")), 1)

    def test_master_password_flow(self):
        v = self._vault("c")
        v.initialize()
        v.add("example.com", "u", "pw")
        v.set_master_password("master!")
        v.lock()
        self.assertFalse(v.is_unlocked())
        self.assertFalse(v.unlock("wrong"))
        self.assertTrue(v.unlock("master!"))
        self.assertEqual(v.all()[0]["password"], "pw")

    def test_auto_lock(self):
        v = self._vault("d")
        v.initialize()
        v.set_master_password("m")
        v.change_auto_lock(0)
        self.assertFalse(v.is_unlocked())
        with self.assertRaises(VaultLocked):
            v.all()

    def test_locked_vault_rejects_ops(self):
        v = Vault(self.dir / "e.bin", self.dir / "e.key")
        v.initialize()
        v.set_master_password("m")
        v.change_auto_lock(0)
        with self.assertRaises(VaultLocked):
            v.add("x.com", "u", "p")

    def test_weak_reused_report(self):
        v = self._vault("f")
        v.initialize()
        v.add("a.com", "u", "123456")
        v.add("b.com", "u", "123456")
        v.add("c.com", "u", generate_password(20))
        rep = v.report()
        self.assertIn(0, rep["weak"])
        self.assertIn(1, rep["weak"])
        self.assertTrue(any(len(x) == 2 for x in rep["reused"]))

    def test_csv_roundtrip(self):
        v = self._vault("g")
        v.initialize()
        v.add("a.com", "u1", "p1")
        v.add("b.com", "u2", "p2")
        csv_path = self.dir / "exp.csv"
        self.assertEqual(v.export_csv(csv_path), 2)
        v2 = self._vault("h")
        v2.initialize()
        self.assertEqual(v2.import_csv(csv_path), 2)
        self.assertEqual(len(v2.all()), 2)

    def test_generator_strength(self):
        pw = generate_password(24)
        self.assertEqual(len(pw), 24)
        self.assertGreaterEqual(strength(pw), 3)
        self.assertEqual(strength("password"), 0)
        self.assertEqual(strength(""), 0)
        self.assertGreaterEqual(strength("Tr0ub4dor&3"), 2)


class StorageTests(unittest.TestCase):
    def setUp(self):
        self.store = Store(Path(_TMP) / f"store-{time.time()}.db")

    def test_history_roundtrip(self):
        self.store.add_history("https://example.com/a", "A")
        self.store.add_history("https://example.com/b", "B")
        self.assertEqual(self.store.history_count(), 2)
        rows = self.store.search_history("example")
        self.assertEqual(len(rows), 2)
        self.store.delete_history([rows[0]["id"]])
        self.assertEqual(self.store.history_count(), 1)

    def test_history_range_delete(self):
        self.store.add_history("https://old.com/", "old", visit_time=time.time() - 90000)
        self.store.add_history("https://new.com/", "new")
        n = self.store.delete_history_range(0, time.time() - 86400)
        self.assertEqual(n, 1)
        self.assertEqual(self.store.history_count(), 1)

    def test_retention_prune(self):
        self.store.add_history("https://x.com/", "x", visit_time=time.time() - 400 * 86400)
        self.assertEqual(self.store.prune_history(365), 1)
        self.assertEqual(self.store.history_count(), 0)

    def test_bookmarks_tree(self):
        f = self.store.add_folder("Tech")
        b1 = self.store.add_bookmark("Qt", "https://qt.io", f)
        b2 = self.store.add_bookmark("Python", "https://python.org", f)
        sub = self.store.add_folder("News", f)
        b3 = self.store.add_bookmark("HN", "https://news.ycombinator.com", sub)
        walk = [r["title"] for r in self.store.walk()]
        self.assertEqual(walk, ["Tech", "Qt", "Python", "News", "HN"])
        deleted = self.store.delete_bookmark(f)
        self.assertEqual(deleted, 5)
        self.assertEqual(len(self.store.walk()), 0)

    def test_duplicate_detection(self):
        self.store.add_bookmark("x", "https://dup.example")
        self.assertTrue(self.store.duplicate_url_exists("https://dup.example"))
        self.assertFalse(self.store.duplicate_url_exists("https://other.example"))

    def test_move_bookmark(self):
        b = self.store.add_bookmark("m", "https://move.example")
        f = self.store.add_folder("Target")
        self.store.move_bookmark(b, f)
        titles = [r["title"] for r in self.store.children(f)]
        self.assertIn("m", titles)

    def test_downloads(self):
        self.store.add_download("d1", "https://x/f.zip", "/tmp/f.zip")
        self.store.update_download("d1", received=50, total=100)
        self.store.update_download("d1", state="completed", finished=True, danger="warn")
        r = self.store.get_download("d1")
        self.assertEqual(r["state"], "completed")
        self.assertEqual(r["received_bytes"], 50)
        self.store.clear_downloads()
        self.assertIsNone(self.store.get_download("d1"))


class ListTests(unittest.TestCase):
    def test_is_tracker(self):
        self.assertTrue(lists.is_tracker("ads.example.doubleclick.net"))
        self.assertTrue(lists.is_tracker("site.com", "/gtm.js"))
        self.assertFalse(lists.is_tracker("example.org", "/about"))

    def test_domain_of(self):
        self.assertEqual(lists.domain_of("a.b.example.com"), "example.com")
        self.assertEqual(lists.domain_of("www.bbc.co.uk"), "bbc.co.uk")
        self.assertEqual(lists.domain_of("localhost"), "localhost")

    def test_malware(self):
        self.assertEqual(lists.is_malware("sub.appleid-verify.com"), "known phishing/malware host")
        self.assertEqual(lists.is_malware("example.com"), "")

    def test_lists_are_sane(self):
        self.assertGreater(len(lists.TRACKER_DOMAINS), 80)
        self.assertGreater(len(lists.MALWARE_DOMAINS), 5)
        for d in lists.TRACKER_DOMAINS:
            self.assertNotIn(" ", d)


class SearchTests(unittest.TestCase):
    def setUp(self):
        self.eng = BUILTIN_ENGINES["DuckDuckGo"]

    def test_url_detection(self):
        for t in ("example.com", "https://x.co/a?b=1", "192.168.1.1", "localhost:3000",
                  "[::1]:9000", "sub.domain.co.uk/x"):
            self.assertTrue(looks_like_url(t), t)
        for t in ("how do browsers work", "search this", "123", "a"):
            self.assertFalse(looks_like_url(t), t)

    def test_normalize(self):
        url, kind = normalize_input("example.com", self.eng)
        self.assertEqual((url, kind), ("https://example.com", "url"))
        url, kind = normalize_input("cats", self.eng)
        self.assertEqual(kind, "search")
        self.assertIn("q=cats", url)
        url, kind = normalize_input("browser://settings", self.eng)
        self.assertEqual(kind, "internal")

    def test_engines_configurable(self):
        for name, eng in BUILTIN_ENGINES.items():
            self.assertIn("{query}", eng.search_url)
        g = BUILTIN_ENGINES["Google"]
        self.assertEqual(g.search("a b"), "https://www.google.com/search?q=a+b")

    def test_suggestions_parsing(self):
        self.assertEqual(parse_suggestions_osjson(b'["q",["a","b"]]'), ["a", "b"])
        self.assertEqual(parse_suggestions_osjson(b"not json"), [])


class QRTests(unittest.TestCase):
    def test_format_bits_match_spec(self):
        self.assertEqual(format_bits("L", 0), 0b111011111000100)
        self.assertEqual(format_bits("M", 0), 0b101010000010010)

    def test_version_bits_match_spec(self):
        self.assertEqual(version_bits(7), 0x07C94)

    def test_rs_syndromes_zero(self):
        data = list(b"test data for rs")
        ecc = rs_encode(data, 10)
        self.assertEqual(rs_syndromes(data + ecc, 10), [0] * 10)

    def test_capacity_table_consistency(self):
        from browser.core.qr import _ECC_TABLE, _TOTAL_CW
        for v in range(1, 11):
            for lv in ("L", "M", "Q", "H"):
                ec, sb, lb, scw, lcw = _ECC_TABLE[v][lv]
                data_cw = sb * scw + lb * lcw
                self.assertEqual(data_cw + (sb + lb) * ec, _TOTAL_CW[v], (v, lv))

    def test_alignment_tables(self):
        from browser.core.qr import _ALIGNMENT
        self.assertEqual(_ALIGNMENT[2], [6, 18])
        self.assertEqual(_ALIGNMENT[7], [6, 22, 38])
        self.assertEqual(_ALIGNMENT[10], [6, 28, 50])

    def test_encode_all_levels(self):
        for lv in ("L", "M", "Q", "H"):
            m = encode("Hello browser!", lv)
            self.assertGreaterEqual(len(m), 21)
            # dark module must be dark
            self.assertEqual(m[len(m) - 8][8], 1)
            # finder patterns present
            self.assertEqual(m[0][0], 1)

    def test_multi_block_versions(self):
        m = encode("x" * 150, "L")  # needs v5+ with split blocks
        self.assertGreaterEqual(len(m), 37)

    def test_unicode(self):
        m = encode("приватность 🛡", "M")
        self.assertTrue(m)

    def test_svg(self):
        svg = to_svg(encode("https://example.com"))
        self.assertTrue(svg.startswith("<svg"))
        self.assertIn("rect", svg)


class SettingsTests(unittest.TestCase):
    def test_persistence(self):
        p = Path(_TMP) / f"set-{time.time()}.json"
        s = Settings(p)
        s.set("appearance.theme", "light")
        s2 = Settings(p)
        self.assertEqual(s2.get("appearance.theme"), "light")

    def test_corrupt_settings_recover(self):
        p = Path(_TMP) / f"corrupt-{time.time()}.json"
        p.write_text("{not json", encoding="utf-8")
        s = Settings(p)   # must not raise
        self.assertEqual(s.get("appearance.theme"), "system")

    def test_export_import(self):
        s = Settings(Path(_TMP) / f"ei-{time.time()}.json")
        s.set("search.default_engine", "Google")
        text = s.export_json()
        s2 = Settings(Path(_TMP) / f"ei2-{time.time()}.json")
        n = s2.import_json(text)
        self.assertEqual(s2.get("search.default_engine"), "Google")
        self.assertGreater(n, 10)

    def test_reset(self):
        s = Settings(Path(_TMP) / f"rs-{time.time()}.json")
        s.set("privacy.block_trackers", False)
        s.reset()
        self.assertTrue(s.get("privacy.block_trackers"))


class SessionTests(unittest.TestCase):
    def test_roundtrip(self):
        s = Settings(Path(_TMP) / f"ses-{time.time()}.json")
        save(s, [[{"url": "https://example.com", "pinned": True}]])
        data = load(s)
        self.assertEqual(data[0][0]["url"], "https://example.com")
        self.assertTrue(data[0][0]["pinned"])

    def test_crash_flag(self):
        s = Settings(Path(_TMP) / f"ses2-{time.time()}.json")
        save(s, [[{"url": "https://example.com"}]])
        self.assertTrue(crashed_last_run(s))
        mark_clean_exit(s)
        self.assertFalse(crashed_last_run(s))

    def test_sanitization(self):
        s = Settings(Path(_TMP) / f"ses3-{time.time()}.json")
        save(s, [[{"url": ""}, {"url": "https://ok.example", "zoom": "x"}]])
        data = load(s)
        self.assertEqual(len(data[0]), 1)
        self.assertEqual(data[0][0]["zoom"], 1.0)


class BookmarkImportExportTests(unittest.TestCase):
    def test_roundtrip(self):
        store = Store(Path(_TMP) / f"bm-{time.time()}.db")
        f = store.add_folder("News")
        store.add_bookmark("HN", "https://news.ycombinator.com", f)
        store.add_bookmark("Example", "https://example.com")
        out = Path(_TMP) / "bm.html"
        n = export_bookmarks_html(store, out)
        self.assertEqual(n, 2)
        store2 = Store(Path(_TMP) / f"bm2-{time.time()}.db")
        m = import_bookmarks_html(store2, out)
        self.assertEqual(m, 2)
        urls = [r["url"] for r in store2.walk()]
        self.assertIn("https://news.ycombinator.com", urls)
        self.assertIn("https://example.com", urls)


class FakeSettings:
    def __init__(self, values=None):
        self.values = dict(values or {})
        self.saved = []

    def get(self, k, d=None):
        return self.values.get(k, d)

    def set(self, k, v):
        self.values[k] = v


class ExtensionTests(unittest.TestCase):
    def setUp(self):
        import shutil
        self.root = Path(_TMP) / "ext-tests"
        self.dir = self.root / "extensions"
        shutil.rmtree(self.root, ignore_errors=True)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.settings = FakeSettings({"extensions.enabled": {}, "extensions.allow_in_private": []})

    def _write_ext(self, ext_id: str, perms=("page",), private=False):
        folder = self.dir / ext_id
        folder.mkdir(exist_ok=True)
        manifest = {"id": ext_id, "name": ext_id.title(), "version": "1.0",
                    "description": "test", "permissions": list(perms),
                    "matches": ["*://example.com/*"]}
        if private:
            manifest["permissions"].append("private")
        (folder / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        (folder / "script.js").write_text("// hello", encoding="utf-8")
        return folder

    def test_install_and_remove(self):
        import json
        mgr = ExtensionManager(self.settings, self.dir)
        folder = self._write_ext("test-ext")
        ext = mgr.install(folder)
        self.assertEqual(ext.name, "Test-Ext")
        self.assertIsNotNone(mgr.get("test-ext"))
        mgr.remove("test-ext")
        self.assertIsNone(mgr.get("test-ext"))

    def test_invalid_manifest_rejected(self):
        import json
        mgr = ExtensionManager(self.settings, self.dir)
        folder = self._write_ext("bad-ext")
        (folder / "manifest.json").write_text('{"name": "no id"}', encoding="utf-8")
        with self.assertRaises(ValueError):
            mgr.install(folder)

    def test_unknown_permission_rejected(self):
        import json
        mgr = ExtensionManager(self.settings, self.dir)
        folder = self._write_ext("perm-ext", perms=("root",))
        with self.assertRaises(ValueError):
            mgr.install(folder)

    def test_matching_and_private(self):
        import json
        mgr = ExtensionManager(self.settings, self.root)  # data_dir → uses root/extensions
        self._write_ext("pub-ext")
        self._write_ext("priv-ext", perms=("page", "private"))
        mgr.refresh()
        mgr.set_enabled("pub-ext", True)
        scripts = mgr.scripts_for("https://example.com/page", private=False)
        self.assertEqual(len(scripts), 2)
        priv_scripts = mgr.scripts_for("https://example.com/page", private=True)
        self.assertEqual(len(priv_scripts), 0)  # not approved yet
        mgr.set_allowed_in_private("priv-ext", True)
        priv_scripts = mgr.scripts_for("https://example.com/page", private=True)
        self.assertEqual(len(priv_scripts), 1)
        other = mgr.scripts_for("https://other.com/", private=False)
        self.assertEqual(len(other), 0)  # match pattern restricts


class PermissionTests(unittest.TestCase):
    def test_decide(self):
        s = FakeSettings({"permissions.global": {}, "permissions.sites": {}})
        pm = PermissionManager(s)
        self.assertEqual(pm.decide("x.com", "camera"), "ask")
        pm.set_global_default("notifications", "allow")
        self.assertEqual(pm.decide("x.com", "notifications"), "allow")
        # sensitive can never be globally allowed
        pm.set_global_default("camera", "allow")
        self.assertEqual(pm.decide("x.com", "camera"), "ask")
        pm.set_site_rule("x.com", "camera", "block")
        self.assertEqual(pm.decide("x.com", "camera"), "block")
        self.assertEqual(pm.site_rule("x.com", "camera"), "block")
        pm.reset_site("x.com")
        self.assertIsNone(pm.site_rule("x.com", "camera"))


class UpdateTests(unittest.TestCase):
    def _make_manifest(self, version="1.0.1", pubkey=None, secret=None):
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        import json as _json
        sk = secret or Ed25519PrivateKey.generate()
        pub = pubkey or sk.public_key()
        manifest = {"version": version, "url": "https://example.com/browser-setup.exe",
                    "sha256": "ab" * 32, "channel": "stable", "notes": "x",
                    "pubkey": pub.public_bytes_raw().hex()}
        signed = _json.dumps({k: manifest[k] for k in sorted(manifest)},
                             sort_keys=True, separators=(",", ":")).encode()
        manifest["signature"] = sk.sign(signed).hex()
        return manifest, sk

    def test_valid_signature_accepted(self):
        import json as _json
        m, _ = self._make_manifest()
        ok, msg = updates.verify_manifest(m, {})
        self.assertTrue(ok, msg)

    def test_tampered_manifest_rejected(self):
        m, _ = self._make_manifest()
        m["sha256"] = "ff" * 32
        ok, msg = updates.verify_manifest(m, {})
        self.assertFalse(ok)

    def test_downgrade_rejected(self):
        m, _ = self._make_manifest(version="0.9.9")
        ok, _msg = updates.verify_manifest(m, {})
        self.assertFalse(ok)

    def test_key_pinning(self):
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        m1, sk1 = self._make_manifest()
        trust = {"pubkey": m1["pubkey"]}
        ok, msg = updates.verify_manifest(m1, trust)
        self.assertTrue(ok)
        # attacker swaps in their own key:
        m2, _ = self._make_manifest(secret=Ed25519PrivateKey.generate())
        ok, msg = updates.verify_manifest(m2, trust)
        self.assertFalse(ok)
        self.assertIn("changed", msg)

    def test_package_hash(self):
        import hashlib
        p = Path(_TMP) / "pkg.bin"
        data = b"package-bytes"
        p.write_bytes(data)
        ok, _ = updates.verify_package_hash(p, hashlib.sha256(data).hexdigest())
        self.assertTrue(ok)
        ok, msg = updates.verify_package_hash(p, "ff" * 32)
        self.assertFalse(ok)


class PagesTests(unittest.TestCase):
    def setUp(self):
        self.settings = Settings(Path(_TMP) / f"pages-{time.time()}.json")

    def test_home_renders(self):
        html = pages.home(self.settings, "DuckDuckGo", "https://duckduckgo.com/?q={query}")
        self.assertIn("browser", html)
        self.assertIn("Private by default", html)

    def test_all_pages_render(self):
        self.assertTrue(pages.history_page([], "", 0))
        self.assertTrue(pages.bookmarks_page([]))
        self.assertTrue(pages.downloads_page([]))
        self.assertTrue(pages.passwords_page([], {"weak": [], "reused": []}, True, False))
        self.assertTrue(pages.privacy_page({"trackers": 1, "cookies": 0, "requests": 0},
                                           [("x", "on")], [], "balanced"))
        self.assertTrue(pages.security_page("https://a.com", True, "ok", [], [("x", "on")], "n"))
        self.assertTrue(pages.extensions_page([], {}, []))
        self.assertTrue(pages.permissions_page({}, {}, {"camera": "Camera"}))
        self.assertTrue(pages.about_page("1.0", "6.11", "/data"))
        self.assertTrue(pages.blocked("https://x", "reason"))
        self.assertTrue(pages.cert_error("https://x", "detail"))
        self.assertTrue(pages.error_page("https://x", "T", "D"))

    def test_no_script_injection(self):
        html = pages.home(self.settings, "x", "y")
        self.assertNotIn("<script", html)

    def test_xss_escaping(self):
        evil = '<script>alert(1)</script>'
        html = pages.bookmark_edit_page("id", evil, "u", False)
        self.assertNotIn("<script>alert", html)
        self.assertIn("&lt;script&gt;", html)
        html = pages.blocked(evil, evil)
        self.assertNotIn("<script>alert", html)

    def test_password_never_in_page(self):
        html = pages.passwords_page(
            [{"origin": "x.com", "username": "u", "password": "S3cret!", "_strength": 3}],
            {"weak": [], "reused": []}, False, False)
        self.assertNotIn("S3cret!", html)

    def test_search_redirect(self):
        self.assertEqual(
            pages.search_redirect("a b", "https://e.com/?q={query}"),
            "https://e.com/?q=a+b")


class EngineProbeTests(unittest.TestCase):
    def test_should_probe_by_default_and_can_be_disabled(self):
        from browser.engine_probe import should_probe
        old = os.environ.get("BROWSER_PROBE")
        try:
            os.environ.pop("BROWSER_PROBE", None)
            self.assertTrue(should_probe())            # default: always probe
            os.environ["BROWSER_PROBE"] = "0"
            self.assertFalse(should_probe())           # explicit opt-out
            os.environ["BROWSER_PROBE"] = "1"
            self.assertTrue(should_probe())            # explicit override
        finally:
            if old is not None: os.environ["BROWSER_PROBE"] = old
            else: os.environ.pop("BROWSER_PROBE", None)

    def test_probe_flag_sets_ordered_by_liberality(self):
        from browser.engine_probe import PROBE_FLAG_SETS, FAILFAST_EXIT
        self.assertEqual(PROBE_FLAG_SETS[0], [])       # default first
        self.assertTrue(all(isinstance(f, list) for f in PROBE_FLAG_SETS))
        self.assertEqual(FAILFAST_EXIT, 3221226505)

    def test_restriction_message_is_actionable(self):
        from browser.engine_probe import restriction_message
        msg = restriction_message(3221226505)
        self.assertIn("3221226505", msg)
        self.assertIn("crash.log", msg)   # tells the user where the reason lives


class RegressionTests(unittest.TestCase):
    """Bugs found in the full-code review: lock these behaviors in."""

    def test_vault_master_rotation_preserves_data(self):
        v = Vault(Path(_TMP) / "rot.bin", Path(_TMP) / "rot.key")
        v.initialize(master="old-master")
        v.add("example.com", "u", "CorrectHorse1!")
        v.set_master_password("new-master")
        v.add("example2.com", "u2", "Hunter2Hunter22")
        v2 = Vault(Path(_TMP) / "rot.bin", Path(_TMP) / "rot.key")
        self.assertTrue(v2.unlock("new-master"))
        self.assertEqual(v2.find("example.com")["password"], "CorrectHorse1!")
        self.assertEqual(v2.find("example2.com")["password"], "Hunter2Hunter22")

    def test_vault_clear_all(self):
        v = Vault(Path(_TMP) / "clr.bin", Path(_TMP) / "clr.key")
        v.initialize()
        v.add("a.com", "u", "CorrectHorse1!")
        v.clear_all()
        self.assertEqual(v.all(), [])

    def test_scheme_handler_routes_are_well_formed(self):
        """Every _route result must be (html, mime, redirect) — a bare page
        return used to crash the browser://adblock service."""
        from browser.pages.handler import SchemeHandler, Services
        from browser.settings import Settings as S
        from browser.core.privacy import Counters
        from browser.core.adblock import ListManager
        s = Services()
        s.settings = S(Path(_TMP) / f"sh-{time.time()}.json")
        s.counters = Counters()
        s.adblock = ListManager(s.settings, Path(_TMP) / "ab",
                                lambda u: u.rsplit(".", 2)[-2] if "." in u else u)
        h = SchemeHandler(s)
        out = h._route("adblock", "/", _FakeUrl("adblock", "/"))
        self.assertEqual(len(out), 3)
        self.assertTrue(out[0].startswith("<!DOCTYPE html>"))

    def test_scheme_handler_unknown_host(self):
        from browser.pages.handler import SchemeHandler, Services
        from browser.settings import Settings as S
        s = Services()
        s.settings = S(Path(_TMP) / f"sh2-{time.time()}.json")
        h = SchemeHandler(s)
        out = h._route("nosuchpage", "/", _FakeUrl("nosuchpage", "/"))
        self.assertEqual(len(out), 3)
        self.assertIn("Not found", out[0])

    def test_engine_error_reply_renders(self):
        from browser.pages.handler import SchemeHandler, Services
        h = SchemeHandler(Services())
        html = h._error_reply("boom <script>")
        self.assertIn("Internal page error", html)
        self.assertNotIn("<script>", html)   # escaped

    def test_tor_page_renders(self):
        """browser://tor renders with the Tor dashboard (integration off)."""
        from browser.pages.handler import SchemeHandler, Services
        from browser.settings import Settings as S
        from browser.core.tor import TorManager
        s = Services()
        s.settings = S(Path(_TMP) / f"tor-{time.time()}.json")
        s.tor = TorManager(s.settings, Path(_TMP) / "tordata")
        h = SchemeHandler(s)
        out = h._route("tor", "/", _FakeUrl("tor", "/"))
        self.assertEqual(len(out), 3)
        self.assertIn("Tor", out[0])
        self.assertIn("OFF", out[0])   # off by default

    def test_tor_page_enable_flow(self):
        from browser.pages.handler import SchemeHandler, Services
        from browser.settings import Settings as S
        from browser.core.tor import TorManager
        s = Services()
        s.settings = S(Path(_TMP) / f"tor2-{time.time()}.json")
        s.tor = TorManager(s.settings, Path(_TMP) / "tordata2")
        h = SchemeHandler(s)
        out = h._route("tor", "/", _FakeUrl("tor", "/", "action=enable"))
        self.assertTrue(s.settings.get("tor.enabled"))
        # safety default applied: WebRTC off in Tor mode
        self.assertEqual(s.settings.get("privacy.webrtc_policy"), "disable")
        self.assertIn("restart", out[0])

    def test_qr_host_with_no_url_degrades(self):
        from browser.pages.handler import SchemeHandler, Services
        from browser.settings import Settings as S
        s = Services()
        s.settings = S(Path(_TMP) / f"sh3-{time.time()}.json")
        h = SchemeHandler(s)
        out = h._route("qr", "/", _FakeUrl("qr", "/"))
        self.assertEqual(len(out), 3)
        self.assertIn("No URL", out[0])

    def test_store_update_history_title(self):
        st = Store(Path(_TMP) / "title.db")
        st.add_history("https://a.com/x", "")
        st.update_history_title("https://a.com/x", "A page")
        row = st.search_history("a.com")[0]
        self.assertEqual(row["title"], "A page")
        st.close()

    def test_reader_mode_escapes_img_src(self):
        js = WebTab.READER_JS
        self.assertIn('replace(/"/g', js)  # attribute-breakout guard present


class _FakeUrl:
    """Minimal QUrl stand-in for SchemeHandler._route smoke tests."""
    def __init__(self, host, path, query=b""):
        self._h, self._p, self._q = host, path, query
    def query(self):
        return self._q
    def host(self):
        return self._h
    def path(self):
        return self._p


if __name__ == "__main__":
    unittest.main()
