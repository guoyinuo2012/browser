"""Optional Tor integration for browser.

Model (like other Chromium-based launchers): browser routes all traffic
through a local Tor SOCKS5 proxy (default 127.0.0.1:9050). browser can use:

  * a Tor that is already running (Tor Browser's tor, Tor service, daemon),
  * or launch a tor.exe the user points at (Settings / browser://tor).

Tor mode is OFF by default and opt-in. When it is enabled:
  * engine flags pin ALL traffic to the SOCKS5 proxy and block local DNS
    resolution (no DNS leak),
  * WebRTC is disabled in pages by default when Tor is switched on
    (WebRTC bypasses proxies and would leak the real IP),
  * exit connectivity is verified against check.torproject.org through the
    proxy (pure-Python SOCKS5 client; no extra dependencies).

Note: QtWebEngine is not the Tor Browser. Fingerprinting
surface is reduced (anti-fingerprinting scripts) but not eliminated, and
browser recommends strict fingerprinting defenses in Tor mode.
"""

from __future__ import annotations

import os
import socket
import subprocess
import threading
import time
from pathlib import Path
from typing import Optional, Tuple

SOCKS5_GREETING = b"\x05\x01\x00"          # version 5, 1 method, no auth


def _recv_exact(sock: socket.socket, n: int) -> bytes:
    buf = b""
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            break
        buf += chunk
    return buf


def proxy_alive(port: int = 9050, timeout: float = 3.0) -> bool:
    """True when a SOCKS5 proxy answers on 127.0.0.1:<port>."""
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=timeout) as s:
            s.settimeout(timeout)
            s.sendall(SOCKS5_GREETING)
            resp = _recv_exact(s, 2)
            return len(resp) == 2 and resp[0] == 5 and resp[1] == 0
    except (OSError, ValueError):
        return False


def _http_over_socks5(port: int, host: bytes, http_req: bytes,
                      timeout: float) -> Tuple[bool, str]:
    """One HTTP request through the SOCKS5 proxy. Returns (ok, body)."""
    with socket.create_connection(("127.0.0.1", port), timeout=timeout) as s:
        s.settimeout(timeout)
        s.sendall(SOCKS5_GREETING)
        if _recv_exact(s, 2) != b"\x05\x00":
            return False, "not a SOCKS5 proxy"
        req = (b"\x05\x01\x00\x03" + bytes([len(host)]) + host
               + (80).to_bytes(2, "big"))
        s.sendall(req)
        resp = _recv_exact(s, 4)
        if len(resp) < 2 or resp[1] != 0:
            return False, f"proxy refused CONNECT (code {resp[1] if len(resp) > 1 else '?'})"
        s.sendall(http_req)
        data = b""
        while len(data) < 262144:
            try:
                chunk = s.recv(4096)
            except socket.timeout:
                break
            if not chunk:
                break
            data += chunk
        return True, data.decode("utf-8", "replace")


CHECK_HOST = b"check.torproject.org"
CHECK_REQUEST = (b"GET /api/ip HTTP/1.1\r\n"
                 b"Host: check.torproject.org\r\n"
                 b"User-Agent: Mozilla/5.0\r\n"
                 b"Connection: close\r\n\r\n")


def exit_test(port: int = 9050, timeout: float = 15.0) -> Tuple[bool, str]:
    """Full check: is an exit relay reachable and are we seen as Tor?

    Returns (confirmed, message). `confirmed` False with an "inconclusive"
    note is NOT an error — the check site may be unreachable.
    """
    try:
        ok, body = _http_over_socks5(port, CHECK_HOST, CHECK_REQUEST, timeout)
    except (OSError, socket.timeout) as exc:
        return False, f"test inconclusive: {exc}"
    if not ok:
        return False, body
    try:
        start = body.index("{")
        end = body.rindex("}") + 1
        obj = json_loads_safe(body[start:end])
    except (ValueError, IndexError):
        return False, "test inconclusive: unexpected response from check site"
    if obj.get("IsTor") is True:
        ip = obj.get("IP", "")
        return True, f"exit relay confirmed (exit IP {ip})"
    return False, "proxy reachable, but the exit says this is NOT Tor traffic"


def json_loads_safe(text: str) -> dict:
    import json
    try:
        obj = json.loads(text)
        return obj if isinstance(obj, dict) else {}
    except ValueError:
        return {}


class TorManager:
    """State + optional tor.exe launcher for browser's Tor mode."""

    def __init__(self, settings, data_dir: Path):
        self.settings = settings
        self.data_dir = Path(data_dir)
        self._process: Optional[subprocess.Popen] = None
        self._tor_output: list[str] = []          # last log lines (debugging)
        self._bootstrapped = threading.Event()
        self._exit_result: Optional[Tuple[bool, str]] = None
        self._exit_lock = threading.Lock()

    # -- settings ------------------------------------------------------------
    @property
    def enabled(self) -> bool:
        return bool(self.settings.get("tor.enabled", False))

    @property
    def socks_port(self) -> int:
        try:
            return int(self.settings.get("tor.socks_port", 9050))
        except (TypeError, ValueError):
            return 9050

    # -- status ---------------------------------------------------------------
    def is_running(self) -> bool:
        if self._process is not None and self._process.poll() is None:
            return True
        return proxy_alive(self.socks_port)

    def status_line(self) -> str:
        if not self.enabled:
            return "off"
        if self.is_running():
            with self._exit_lock:
                if self._exit_result:
                    return self._exit_result[1]
            return "proxy reachable (exit not tested)"
        return "enabled, but no proxy is answering"

    def test_exit_async(self) -> None:
        """Run the exit check in the background (scheme handlers must be fast)."""
        def run():
            result = exit_test(self.socks_port)
            with self._exit_lock:
                self._exit_result = result
        threading.Thread(target=run, daemon=True).start()

    def cached_exit_result(self) -> Optional[Tuple[bool, str]]:
        with self._exit_lock:
            return self._exit_result

    # -- tor.exe launch ---------------------------------------------------------
    def launch_tor(self, tor_path: str, timeout: float = 90.0) -> bool:
        """Spawn the user's tor.exe with an isolated data dir; wait for
        bootstrap. Returns True when a SOCKS5 proxy answers afterwards."""
        if self.is_running():
            return True
        tor_path = (tor_path or "").strip().strip('"')
        if not tor_path or not os.path.isfile(tor_path):
            return False
        datadir = self.data_dir / "tor-data"
        try:
            datadir.mkdir(parents=True, exist_ok=True)
        except OSError:
            return False
        args = [tor_path,
                "--SocksPort", f"127.0.0.1:{self.socks_port}",
                "--DataDirectory", str(datadir)]
        creationflags = 0x08000000 if os.name == "nt" else 0   # CREATE_NO_WINDOW
        try:
            self._process = subprocess.Popen(
                args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, encoding="utf-8", errors="replace",
                creationflags=creationflags)
        except OSError:
            self._process = None
            return False
        self._bootstrapped.clear()
        threading.Thread(target=self._pump_output, daemon=True).start()
        self._bootstrapped.wait(timeout)
        return self.proxy_alive_check()

    def _pump_output(self) -> None:
        proc = self._process
        if proc is None or proc.stdout is None:
            return
        try:
            for line in proc.stdout:
                line = line.strip()
                if not line:
                    continue
                self._tor_output.append(line[:200])
                del self._tor_output[:-200]     # keep last 200 lines
                if "Bootstrapped 100%" in line:
                    self._bootstrapped.set()
        except (OSError, ValueError):
            pass

    def proxy_alive_check(self) -> bool:
        return proxy_alive(self.socks_port)

    def last_tor_output(self) -> list[str]:
        return list(self._tor_output[-40:])

    def stop(self) -> None:
        """Terminate a tor.exe we launched (never a foreign Tor)."""
        proc = self._process
        if proc is None or proc.poll() is not None:
            return
        try:
            proc.terminate()
            try:
                proc.wait(5)
            except subprocess.TimeoutExpired:
                proc.kill()
        except OSError:
            pass
        self._process = None


def engine_flags_for(settings) -> list[str]:
    """Chromium flags that pin traffic to Tor. Empty when Tor is off."""
    if not bool(settings.get("tor.enabled", False)):
        return []
    try:
        port = int(settings.get("tor.socks_port", 9050))
    except (TypeError, ValueError):
        port = 9050
    return [
        f"--proxy-server=socks5://127.0.0.1:{port}",
        # no local DNS: every lookup must go through the proxy
        '--host-resolver-rules="MAP * ~NOTFOUND , EXCLUDE 127.0.0.1, '
        'EXCLUDE localhost"',
    ]
