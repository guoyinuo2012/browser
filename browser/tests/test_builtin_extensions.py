"""Tests for the built-in (bundled) extensions and per-site prefs."""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path

BUILTIN_DIR = (Path(__file__).resolve().parents[1] / "data" /
               "builtin_extensions")


class BundledSourcesTests(unittest.TestCase):
    """The bundled extension sources themselves must be valid."""

    def test_all_builtins_have_valid_manifests(self):
        folders = [f for f in BUILTIN_DIR.iterdir() if f.is_dir()]
        self.assertGreaterEqual(len(folders), 4)
        seen = set()
        for folder in folders:
            mf = folder / "manifest.json"
            self.assertTrue(mf.is_file(), f"{folder}: manifest missing")
            m = json.loads(mf.read_text(encoding="utf-8"))
            self.assertIn("id", m)
            self.assertIn("name", m)
            self.assertTrue(m.get("builtin"))
            self.assertEqual(sorted(m["permissions"]),
                             sorted(set(m["permissions"])))
            for p in m["permissions"]:
                self.assertIn(p, {"page", "network", "storage", "private",
                                  "clipboard"})
            self.assertTrue((folder / "script.js").is_file(),
                            f"{folder}: script.js missing")
            seen.add(m["id"])
        expected = {"video-speed-controls", "dark-reader-lite",
                    "consent-banner-hider", "selection-freedom"}
        self.assertEqual(seen, expected)

    def test_scripts_are_self_guards_and_syntax_clean(self):
        for script in BUILTIN_DIR.glob("*/script.js"):
            src = script.read_text(encoding="utf-8")
            self.assertIn("(function", src)
            self.assertIn("__browser", src)      # double-run guard present
            self.assertLess(src.count("{"), 1000)  # sanity
            # no external endpoints baked in
            self.assertNotIn("http://", src)
            self.assertNotIn("https://", src)


class _TempEnvCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self._old = os.environ.get("BROWSER_DATA_DIR")
        os.environ["BROWSER_DATA_DIR"] = self.tmp
        import importlib
        from browser import paths
        importlib.reload(paths)
        paths.ensure_dirs()

    def tearDown(self):
        if self._old is not None:
            os.environ["BROWSER_DATA_DIR"] = self._old
        shutil.rmtree(self.tmp, ignore_errors=True)


class BuiltinSyncTests(_TempEnvCase):
    def _manager(self):
        from browser.settings import Settings
        from browser.core.extensions import ExtensionManager
        from browser import paths
        return Settings(), ExtensionManager(Settings(), paths.data_dir())

    def test_sync_installs_all_builtins(self):
        s, m = self._manager()
        fresh = m.sync_builtins()
        self.assertEqual(set(fresh), {"video-speed-controls",
                                      "dark-reader-lite",
                                      "consent-banner-hider",
                                      "selection-freedom"})
        for ext in m.all():
            self.assertTrue(ext.builtin)

    def test_sync_is_idempotent_and_upgrades(self):
        s, m = self._manager()
        m.sync_builtins()
        fresh2 = m.sync_builtins()
        self.assertEqual(fresh2, [])             # nothing new on second run
        # simulate an app update with a newer version
        src = (BUILTIN_DIR / "video-speed-controls")
        dest = m.dir / "video-speed-controls"
        mf = json.loads((dest / "manifest.json").read_text(encoding="utf-8"))
        mf["version"] = "0.9.0"
        (dest / "manifest.json").write_text(json.dumps(mf), encoding="utf-8")
        m.refresh()
        m.sync_builtins()
        self.assertEqual(m.get("video-speed-controls").version, "1.0.0")

    def test_settings_survive_upgrade(self):
        s, m = self._manager()
        m.sync_builtins()
        m.set_enabled("dark-reader-lite", False)
        m.set_site_pref("dark-reader-lite", "example.com", True)
        # force reinstall
        shutil.rmtree(m.dir / "dark-reader-lite")
        m.sync_builtins()
        self.assertFalse(m.is_enabled("dark-reader-lite"))
        self.assertTrue(m.site_pref("dark-reader-lite", "example.com") is True)

    def test_remove_refused_and_user_ext_allowed(self):
        s, m = self._manager()
        m.sync_builtins()
        with self.assertRaises(ValueError):
            m.remove("video-speed-controls")
        # a user extension still removable
        user = m.dir / "user_thing"
        user.mkdir(parents=True)
        (user / "manifest.json").write_text(json.dumps({
            "id": "user_thing", "name": "User Thing", "version": "1.0"}))
        (user / "script.js").write_text("// hi")
        m.refresh()
        m.remove("user_thing")
        self.assertIsNone(m.get("user_thing"))

    def test_user_extension_with_builtin_id_is_protected(self):
        s, m = self._manager()
        # user installs a (fake) extension reusing a builtin id
        hijack = m.dir / "dark-reader-lite"
        hijack.mkdir(parents=True)
        (hijack / "manifest.json").write_text(json.dumps({
            "id": "dark-reader-lite", "name": "Fake", "version": "9.9.9"}))
        m.refresh()
        m.sync_builtins()                        # must not overwrite the user's
        self.assertEqual(m.get("dark-reader-lite").version, "9.9.9")
        self.assertFalse(m.get("dark-reader-lite").builtin)


class SitePrefInjectionTests(_TempEnvCase):
    def _manager(self, sync=True):
        from browser.settings import Settings
        from browser.core.extensions import ExtensionManager
        from browser import paths
        s = Settings()
        m = ExtensionManager(s, paths.data_dir())
        fresh = m.sync_builtins() if sync else []
        return s, m, fresh

    URL = "https://www.example.com/page"
    HOST = "www.example.com"

    def test_default_on_exts_inject_everywhere(self):
        _s, m, _f = self._manager()
        ids = [e.id for e, _ in m.scripts_for(self.URL, False, self.HOST)]
        self.assertIn("video-speed-controls", ids)
        self.assertIn("consent-banner-hider", ids)
        self.assertIn("selection-freedom", ids)
        self.assertNotIn("dark-reader-lite", ids)      # opt-in

    def test_optin_requires_site_pref(self):
        _s, m, _f = self._manager()
        m.set_site_pref("dark-reader-lite", self.HOST, True)
        ids = [e.id for e, _ in m.scripts_for(self.URL, False, self.HOST)]
        self.assertIn("dark-reader-lite", ids)

    def test_site_off_blocks_injection(self):
        _s, m, _f = self._manager()
        m.set_site_pref("video-speed-controls", self.HOST, False)
        ids = [e.id for e, _ in m.scripts_for(self.URL, False, self.HOST)]
        self.assertNotIn("video-speed-controls", ids)

    def test_toggle_cycle_roundtrip(self):
        _s, m, _f = self._manager()
        # unset -> on -> off -> unset
        self.assertTrue(m.toggle_site_pref("dark-reader-lite", "x.com"))
        self.assertTrue(m.site_pref("dark-reader-lite", "x.com") is True)
        self.assertFalse(m.toggle_site_pref("dark-reader-lite", "x.com"))
        self.assertTrue(m.site_pref("dark-reader-lite", "x.com") is False)
        self.assertFalse(m.toggle_site_pref("dark-reader-lite", "x.com"))
        self.assertTrue(m.site_pref("dark-reader-lite", "x.com") is None)

    def test_builtins_run_in_private_after_default_approval(self):
        s, m, fresh = self._manager()
        self.assertTrue(fresh)                    # this run installed them
        allowed = list(s.get("extensions.allow_in_private", []))
        allowed += [i for i in fresh if i not in allowed]  # as app.py does
        s.set("extensions.allow_in_private", allowed)
        ids = [e.id for e, _ in m.scripts_for(self.URL, True, self.HOST)]
        self.assertIn("video-speed-controls", ids)

    def test_revoking_private_survives_restart(self):
        """The auto-approval only fires on fresh install, never re-adds."""
        from browser.core.extensions import ExtensionManager
        from browser import paths
        s, m, fresh = self._manager()
        allowed = list(s.get("extensions.allow_in_private", []))
        allowed += [i for i in fresh if i not in allowed]
        s.set("extensions.allow_in_private", allowed)
        # user revokes video-speed in private windows
        m.set_allowed_in_private("video-speed-controls", False)
        # simulate restart: new manager, same settings
        m2 = ExtensionManager(s, paths.data_dir())
        m2.sync_builtins()
        self.assertFalse(m2.allowed_in_private("video-speed-controls"))

    def test_disabled_extension_injects_nowhere(self):
        _s, m, _f = self._manager()
        m.set_enabled("video-speed-controls", False)
        ids = [e.id for e, _ in m.scripts_for(self.URL, False, self.HOST)]
        self.assertNotIn("video-speed-controls", ids)


if __name__ == "__main__":
    unittest.main()
