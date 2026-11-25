"""Tests for the optional Tor integration (browser.core.tor)."""

from __future__ import annotations

import socket
import threading
import time
import unittest
from pathlib import Path

from browser.core.tor import (TorManager, engine_flags_for, exit_test,
                              json_loads_safe, proxy_alive)


class FakeSocksServer:
    """Minimal SOCKS5 server for unit tests: greeting + CONNECT + HTTP body."""

    def __init__(self, http_body: bytes = b"", refuse: bool = False,
                 no_socks: bool = False):
        self.http_body = http_body
        self.refuse = refuse
        self.no_socks = no_socks
        self._srv = socket.socket()
        self._srv.bind(("127.0.0.1", 0))
        self._srv.listen(4)
        self.port = self._srv.getsockname()[1]
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    def _serve(self):
        try:
            while True:
                conn, _ = self._srv.accept()
                threading.Thread(target=self._handle,
                                 args=(conn,), daemon=True).start()
        except OSError:
            pass

    def _handle(self, conn):
        try:
            conn.settimeout(5)
            greeting = conn.recv(3)
            if self.no_socks:
                conn.close()
                return
            conn.sendall(b"\x05\x00")
            if len(greeting) >= 5 or True:
                req = conn.recv(64)
                if self.refuse:
                    conn.sendall(b"\x05\x01\x00\x01" + b"\x00" * 6)
                else:
                    conn.sendall(b"\x05\x00\x00\x01" + b"\x00" * 6)
                    while True:
                        data = conn.recv(4096)
                        if not data or b"\r\n\r\n" in data:
                            break
                    conn.sendall(self.http_body)
        except OSError:
            pass
        finally:
            try:
                conn.close()
            except OSError:
                pass

    def close(self):
        try:
            self._srv.close()
        except OSError:
            pass


class ProxyAliveTests(unittest.TestCase):
    def test_dead_port(self):
        # a port almost certainly without a listener
        self.assertFalse(proxy_alive(59989, timeout=1.0))

    def test_socks5_answers(self):
        srv = FakeSocksServer()
        try:
            self.assertTrue(proxy_alive(srv.port, timeout=2.0))
        finally:
            srv.close()

    def test_non_socks_port_rejected(self):
        # a plain TCP echo that never answers the greeting correctly
        srv = FakeSocksServer(no_socks=True)
        try:
            self.assertFalse(proxy_alive(srv.port, timeout=2.0))
        finally:
            srv.close()


class ExitTestTests(unittest.TestCase):
    def test_exit_confirmed(self):
        body = (b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n"
                b"Connection: close\r\n\r\n"
                b'{"IP":"185.220.101.5","IsTor":true,"ExitNode":true}')
        srv = FakeSocksServer(http_body=body)
        try:
            confirmed, msg = exit_test(srv.port, timeout=5.0)
            self.assertTrue(confirmed)
            self.assertIn("confirmed", msg)
        finally:
            srv.close()

    def test_exit_not_tor(self):
        body = (b"HTTP/1.1 200 OK\r\nConnection: close\r\n\r\n"
                b'{"IP":"1.2.3.4","IsTor":false}')
        srv = FakeSocksServer(http_body=body)
        try:
            confirmed, msg = exit_test(srv.port, timeout=5.0)
            self.assertFalse(confirmed)
            self.assertIn("NOT Tor", msg)
        finally:
            srv.close()

    def test_proxy_refused_connect(self):
        srv = FakeSocksServer(refuse=True)
        try:
            confirmed, msg = exit_test(srv.port, timeout=5.0)
            self.assertFalse(confirmed)
            self.assertIn("refused", msg)
        finally:
            srv.close()

    def test_inconclusive_site(self):
        srv = FakeSocksServer(http_body=b"HTTP/1.1 200 OK\r\n\r\nnot json")
        try:
            confirmed, msg = exit_test(srv.port, timeout=5.0)
            self.assertFalse(confirmed)
            self.assertIn("inconclusive", msg)
        finally:
            srv.close()


class EngineFlagTests(unittest.TestCase):
    class S:
        def __init__(self, vals):
            self._v = vals
        def get(self, k, d=None):
            return self._v.get(k, d)

    def test_off_gives_no_flags(self):
        self.assertEqual(engine_flags_for(self.S({"tor.enabled": False})), [])
        self.assertEqual(engine_flags_for(self.S({})), [])

    def test_on_pins_socks_and_dns(self):
        flags = engine_flags_for(self.S({"tor.enabled": True,
                                         "tor.socks_port": 9150}))
        joined = " ".join(flags)
        self.assertIn("socks5://127.0.0.1:9150", joined)
        self.assertIn("MAP * ~NOTFOUND", joined)      # no local DNS leak
        self.assertIn("EXCLUDE 127.0.0.1", joined)


class TorManagerTests(unittest.TestCase):
    def _mgr(self):
        return TorManager(None, Path(__file__).parent)

    def test_disabled_status(self):
        class S:
            def get(self, k, d=None):
                return d
        m = TorManager(S(), Path(__file__).parent)
        self.assertEqual(m.status_line(), "off")
        self.assertFalse(m.enabled)

    def test_launch_with_bad_path_is_graceful(self):
        class S:
            def get(self, k, d=None):
                return {"tor.enabled": True, "tor.socks_port": 59997}.get(k, d)
        m = TorManager(S(), Path(__file__).parent)
        self.assertFalse(m.launch_tor("", timeout=1))
        self.assertFalse(m.launch_tor("Z:/no/such/tor.exe", timeout=1))
        self.assertEqual(m.status_line(), "enabled, but no proxy is answering")

    def test_stop_without_process_is_noop(self):
        m = self._mgr()
        m.stop()   # must not raise

    def test_exit_test_async_caches(self):
        class S:
            def get(self, k, d=None):
                return {"tor.enabled": True, "tor.socks_port": 59996}.get(k, d)
        m = TorManager(S(), Path(__file__).parent)
        m.test_exit_async()
        deadline = time.time() + 8
        while time.time() < deadline and m.cached_exit_result() is None:
            time.sleep(0.1)
        self.assertIsNotNone(m.cached_exit_result())

    def test_json_safe(self):
        self.assertEqual(json_loads_safe('{"IsTor": true}'), {"IsTor": True})
        self.assertEqual(json_loads_safe("nope"), {})


if __name__ == "__main__":
    unittest.main()
