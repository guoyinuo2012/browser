"""Engine pre-flight probe for browser.

Chromium can fail fast (0xC0000409) when the surrounding environment
restricts its GPU/IPC needs — antivirus policy, RDP/VM GPU blocks, job
objects. That failure is uncatchable in-process and kills the app silently,
so browser runs a tiny probe subprocess with a few flag presets FIRST:

  * source runs:  python -u -c "<probe script>"
  * frozen exe:   browser.exe --engine-probe   (self-restart, child exits)

The first preset that works is applied via QTWEBENGINE_CHROMIUM_FLAGS.
If none works, browser reports a clear, actionable error (and writes
crash.log) instead of dying silently.

On a normal desktop the first preset succeeds in ~1 s.
"""

from __future__ import annotations

import os
import subprocess
import sys
from typing import Optional

FROZEN = bool(getattr(sys, "frozen", False))

# In-process probe body (used by `python -c` in source runs and by the
# `browser.exe --engine-probe` self-entrypoint in frozen runs).
PROBE_CODE = """
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


def _probe_command() -> list:
    """Command that runs the probe body in a child process."""
    if FROZEN:
        # Our own exe re-invoked with a special flag; the child runs the
        # probe in-process and exits (a fail-fast there only kills the child).
        return [sys.executable, "--engine-probe"]
    return [sys.executable, "-u", "-c", PROBE_CODE]


def should_probe() -> bool:
    """Probe unconditionally unless explicitly disabled — a Chromium fail-fast
    on a desktop would otherwise look like a silent crash."""
    return os.environ.get("BROWSER_PROBE") != "0"


def probe(flag_set: list, timeout: float = 30.0) -> Optional[int]:
    """Run one probe. Returns exit code (0 = OK) or -1 on timeout."""
    env = dict(os.environ)
    env["QTWEBENGINE_CHROMIUM_FLAGS"] = " ".join(flag_set)
    try:
        r = subprocess.run(_probe_command(), env=env, capture_output=True,
                           text=True, timeout=timeout)
        return r.returncode if "PROBE_OK" in r.stdout else (r.returncode or -2)
    except subprocess.TimeoutExpired:
        return -1
    except OSError:
        return -2


def find_working_configuration() -> tuple:
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
        f"Chromium exited with code {exit_code}. This happens when the "
        "surrounding environment blocks its graphics or IPC needs — for "
        "example antivirus policy, a VM/RDP session without GPU, or "
        "restricted-process policies.\n\n"
        "Things to try: update your graphics driver, or try running with "
        "--no-probe to see the raw behaviour. The reason has been written to "
        "the crash.log file in browser's data folder."
    )


def run_probe_entrypoint() -> int:
    """Handler for `browser.exe --engine-probe` (frozen) — runs the probe
    body in-process and exits with 0 on success."""
    env_code = compile(PROBE_CODE, "<engine-probe>", "exec")
    g = {"__name__": "__probe__"}
    try:
        exec(env_code, g)
        return 0
    except SystemExit as e:
        return int(e.code or 0)
    except BaseException:
        import traceback
        traceback.print_exc()
        return 1
