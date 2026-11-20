"""Tests for the built-in ad blocker: filter engine, lists, integration."""

from __future__ import annotations

import os
import shutil
import tempfile
import time
import unittest
from pathlib import Path


class FilterEngineTests(unittest.TestCase):
    """ABP/uBO-syntax filter engine: network + cosmetic matching."""

    def _eng(self, text):
        from browser.core.filterengine import FilterEngine
        eng = FilterEngine()
        eng.load_text(text)
        return eng

    def test_anchored_host_rule(self):
        e = self._eng("||ads.example.com^\n")
        self.assertTrue(e.match("https://ads.example.com/x.js",
                                "ads.example.com", "site.com", "script"))
        self.assertTrue(e.match("https://sub.ads.example.com/x.js",
                                "sub.ads.example.com", "site.com", "script"))
        # prefix-lookalike hosts must NOT match
        self.assertFalse(e.match("https://notads.example.com/",
                                 "notads.example.com", "site.com", "script"))
        self.assertFalse(e.match("https://example.com/",
                                 "example.com", "site.com", "script"))

    def test_separator_and_wildcards(self):
        e = self._eng("||cdn.com/ads/*\n/banner/ad-$image\n")
        self.assertTrue(e.match("https://cdn.com/ads/x.js", "cdn.com",
                                "site.com", "image"))
        self.assertFalse(e.match("https://cdn.com/adsx.js", "cdn.com",
                                 "site.com", "image"))
        self.assertTrue(e.match("https://site.com/banner/ad-x.png", "site.com",
                                "site.com", "image"))

    def test_exceptions_and_types(self):
        e = self._eng("||doubleclick.net^\n@@||doubleclick.net^$script\n")
        self.assertFalse(e.match("https://doubleclick.net/inx.js",
                                 "doubleclick.net", "news.com", "script"))
        self.assertTrue(e.match("https://doubleclick.net/inx.png",
                                "doubleclick.net", "news.com", "image"))

    def test_third_party_and_domain_options(self):
        e = self._eng(
            "||tracking.net^$script,third-party,domain=news.com|~sub.news.com\n")
        self.assertTrue(e.match("https://tracking.net/t.js", "tracking.net",
                                "news.com", "script"))
        self.assertFalse(e.match("https://tracking.net/t.js", "tracking.net",
                                 "sub.news.com", "script"))
        self.assertFalse(e.match("https://tracking.net/t.js", "tracking.net",
                                 "news.com", "image"))
        self.assertFalse(e.match("https://tracking.net/t.js", "tracking.net",
                                 "other.com", "script"))

    def test_important_beats_exception(self):
        e = self._eng("||example.com^$important\n@@||example.com^\n")
        self.assertTrue(e.match("https://example.com/a.js", "example.com",
                                "site.com", "script"))

    def test_regex_filters(self):
        e = self._eng("/tracking[0-9]+/\n")
        self.assertTrue(e.match("https://cdn.com/tracking9/x", "cdn.com",
                                "site.com", "other"))
        self.assertFalse(e.match("https://cdn.com/trackingX/x", "cdn.com",
                                 "site.com", "other"))

    def test_cosmetics(self):
        e = self._eng("##.ad-banner\nexample.com##.site-ad\n"
                      "example.com,other.org###topad\n#@#.keep-me\n")
        css = e.css_for("www.example.com")
        self.assertIn(".site-ad", css)
        self.assertIn("#topad", css)
        self.assertIn(".ad-banner", css)
        self.assertNotIn("keep-me", css)
        self.assertNotIn("site-ad", e.css_for("other-site.net"))

    def test_unsupported_options_are_skipped_not_matched(self):
        e = self._eng("||x.com^$badfilter\n||y.com^$csp=script-src\n"
                      "||z.com^$unknownopt\n")
        self.assertEqual(e.rule_count, 1)
        self.assertFalse(e.match("https://x.com/", "x.com", "a.com", "other"))
        self.assertTrue(e.match("https://y.com/", "y.com", "a.com", "other"))
        self.assertFalse(e.match("https://z.com/", "z.com", "a.com", "other"))

    def test_qt_type_mapping(self):
        from browser.core.filterengine import type_for_qt
        self.assertEqual(type_for_qt(-1), "other")

    def test_easylist_scale(self):
        """40k synthetic rules: load fast, clean requests stay fast."""
        lines = []
        for i in range(20000):
            lines.append(f"||adserver{i//10}.example{i%7}^")
            lines.append(f"/ads/banners{i%100}/*$image")
        from browser.core.filterengine import FilterEngine
        e = FilterEngine()
        t0 = time.perf_counter()
        e.load_text("\n".join(lines))
        self.assertLess(time.perf_counter() - t0, 6.0)
        self.assertEqual(e.rule_count, 40000)
        t0 = time.perf_counter()
        for i in range(100):
            self.assertFalse(e.match(
                f"https://sub.site{i%10}.com/page?q=x", f"sub.site{i%10}.com",
                f"site{i%10}.com", "script"))
        self.assertLess((time.perf_counter() - t0) / 100, 0.005)


class BuiltinListTests(unittest.TestCase):
    def test_builtin_list_loads_and_blocks(self):
        from browser.core.filterengine import FilterEngine
        f = (Path(__file__).resolve().parents[1] / "data" / "abp_builtin.txt")
        eng = FilterEngine()
        eng.load_text(f.read_text("utf-8"))
        self.assertGreater(eng.rule_count, 150)
        self.assertTrue(eng.match(
            "https://securepubads.g.doubleclick.net/gpt.js",
            "securepubads.g.doubleclick.net", "news.com", "script"))
        self.assertFalse(eng.match("https://example.com/page", "example.com",
                                   "example.com", "document"))
        self.assertIn("adsbygoogle", eng.css_for("any.site.com"))


class _TempEnvCase(unittest.TestCase):
    """Base: isolated BROWSER_DATA_DIR per test."""

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


class ListManagerTests(_TempEnvCase):
    def _manager(self):
        from browser.settings import Settings
        from browser.data import lists as datalists
        from browser.core.adblock import ListManager
        from browser import paths
        settings = Settings()
        lm = ListManager(settings, paths.data_dir() / "adblock",
                         datalists.domain_of)
        return settings, lm

    def test_defaults_and_rebuild(self):
        _s, lm = self._manager()
        lm.rebuild()
        ids = [r["id"] for r in lm.lists()]
        self.assertIn("builtin", ids)
        self.assertIn("easylist", ids)
        self.assertGreater(lm.engine.rule_count, 150)
        self.assertTrue(lm.engine.match(
            "https://ads.outbrain.com/f", "ads.outbrain.com", "s.com",
            "script"))

    def test_pause_site(self):
        _s, lm = self._manager()
        lm.set_paused("www.news.com", True)
        self.assertTrue(lm.is_paused("sub.news.com"))
        self.assertFalse(lm.is_paused("other.com"))
        lm.set_paused("www.news.com", False)
        self.assertFalse(lm.is_paused("news.com"))

    def test_custom_list_roundtrip(self):
        _s, lm = self._manager()
        lm.rebuild()
        lid = lm.add_custom("mine", "https://example.com/l.txt")
        rows = {r["id"]: r for r in lm.lists()}
        self.assertIn(lid, rows)
        self.assertTrue(rows[lid]["enabled"])
        lm.remove(lid)
        self.assertNotIn(lid, {r["id"] for r in lm.lists()})


class AdblockIntegrationTests(_TempEnvCase):
    """End-to-end: ListManager engine drives PrivacyInterceptor.decide."""

    def setUp(self):
        super().setUp()
        from browser.settings import Settings
        from browser.data import lists as datalists
        from browser.core.adblock import ListManager
        from browser.core.privacy import (Counters, PrivacyInterceptor,
                                          PrivacyPolicy)
        from browser import paths
        self.settings = Settings()
        self.lm = ListManager(self.settings, paths.data_dir() / "adblock",
                              datalists.domain_of)
        self.lm.rebuild()
        self.counters = Counters()
        self.policy = PrivacyPolicy.from_settings(self.settings)
        self.inter = PrivacyInterceptor(self.counters, self.policy)
        self.inter.adblock = self.lm

    def test_ad_request_blocked_and_counted(self):
        blocked = self.inter.decide("securepubads.g.doubleclick.net",
                                    "/gpt.js", "https", "news.com",
                                    resource_type=9)
        self.assertTrue(blocked)
        _t, _c, ads, _r, _s = self.counters.snapshot()
        self.assertGreater(ads, 0)

    def test_paused_site_unblocks(self):
        self.lm.set_paused("news.com", True)
        blocked = self.inter.decide("securepubads.g.doubleclick.net",
                                    "/gpt.js", "https", "news.com",
                                    resource_type=9)
        self.assertFalse(blocked)

    def test_master_switch(self):
        # isolate ad-block from tracker blocking (doubleclick is in both)
        self.settings.set("privacy.block_trackers", False)
        self.policy.sync(self.settings)
        self.assertTrue(self.inter.decide(
            "securepubads.g.doubleclick.net", "/gpt.js", "https",
            "news.com", resource_type=9))          # ad-block alone blocks it
        self.settings.set("adblock.enabled", False)
        self.policy.sync(self.settings)
        self.assertFalse(self.inter.decide(
            "securepubads.g.doubleclick.net", "/gpt.js", "https",
            "news.com", resource_type=9))          # master off: pass

    def test_first_party_never_blocked_by_builtin(self):
        blocked = self.inter.decide("example.com", "/", "https",
                                    "example.com", resource_type=1,
                                    navigation=True)
        self.assertFalse(blocked)


if __name__ == "__main__":
    unittest.main()
