"""Engine pre-flight probe for browser.

Chromium fails fast (0xC0000409) in environments whose process/job
restrictions block its GPU or IPC needs — e.g. CI sandboxes. That failure is
uncatchable in-process, so when a restricted environment is suspected,
browser runs a tiny probe subprocess with a few flag presets and:

  * uses the first preset that works (applied via QTWEBENGINE_CHROMIUM_FLAGS),
  * otherwise reports a clear, actionable error instead of dying silently.

On a normal desktop the first preset succeeds in ~1s, so the probe is only
enabled when it can matter (see should_probe()).
"""

from __future__ import annotations

import os
import subprocess
import sys
from typing import Optional

PROBE_SCRIPT = """
import sys
from PyQt6.QtWebEngineQuick import QtWebEngineQuick
QtWebEngineQuick.initialize()
import PyQt6.QtWebEngineWidgets  # noqa: F401
from PyQt6.QtWidgets import QApplication
app = QApplication([])
from PyQt6.QtWebEngineCore import QWebEngineProfile
p = QWebEngineProfile("browser-probe", None)
print("PROBE_OK")
"""

PROBE_FLAG_SETS = [
    [],                                      # default — normal desktops
    ["--disable-gpu", "--no-sandbox"],       # VMs / RDP without GPU
    ["--single-process", "--no-sandbox", "--disable-gpu"],
    ["--in-process-gpu", "--no-sandbox", "--disable-gpu"],
]

FAILFAST_EXIT = 3221226505  # 0xC0000409


def should_probe() -> bool:
    """Probe only in environments where Chromium is likely constrained."""
    if os.environ.get("BROWSER_PROBE") == "1":
        return True
    platform = os.environ.get("QT_QPA_PLATFORM", "")
    return platform in ("offscreen", "minimal")


def probe(flag_set: list[str], timeout: float = 30.0) -> Optional[int]:
    """Run one probe. Returns exit code (0 = OK) or -1 on timeout."""
    env = dict(os.environ)
    env["QTWEBENGINE_CHROMIUM_FLAGS"] = " ".join(flag_set)
    try:
        r = subprocess.run([sys.executable, "-u", "-c", PROBE_SCRIPT],
                           env=env, capture_output=True, text=True,
                           timeout=timeout)
        return r.returncode if "PROBE_OK" in r.stdout else (r.returncode or -2)
    except subprocess.TimeoutExpired:
        return -1
    except OSError:
        return -2


def find_working_configuration() -> tuple[bool, list[str], Optional[int]]:
    """Returns (ok, working_flags, last_exit_code)."""
    last = None
    for flags in PROBE_FLAG_SETS:
        code = probe(flags)
        last = code
        if code == 0:
            return True, flags, 0
    return False, [], last


def restriction_message(exit_code: Optional[int]) -> str:
    """Human-facing explanation for a failed engine probe."""
    return (
        "browser could not start its rendering engine.\n\n"
        f"Chromium exited with code {exit_code} (fail-fast). This happens when "
        "the surrounding environment restricts the process — for example "
        "automated test sandboxes with Windows job-object limits.\n\n"
        "browser itself is fine: launch it normally (outside the sandbox) and "
        "it will run. Tried GPU/no-sandbox/single-process fallbacks "
        "automatically; none were permitted here."
    )
