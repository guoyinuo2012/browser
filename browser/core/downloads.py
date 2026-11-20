"""Download manager for browser.

Handles QWebEngineDownloadRequest lifecycle: security screening before
accepting, progress tracking, pause/resume/cancel, persistence, and
open/reveal actions. Downloaded files are never executed automatically.
"""

from __future__ import annotations

import os
import uuid
from pathlib import Path
from typing import Dict, List, Optional

from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtWebEngineCore import QWebEngineDownloadRequest

from .. import paths
from .security import DownloadScreening, SafeBrowsing


class DownloadItem(QObject):
    """One tracked download: state, progress, screening result and paths."""
    updated = pyqtSignal()
    finished_ok = pyqtSignal()
    failed = pyqtSignal(str)

    def __init__(self, did: str, request, store, screen_note: str = ""):
        super().__init__()
        self.id = did
        self.request = request
        self.store = store
        self.screen_note = screen_note

    # -- info ----------------------------------------------------------------
    @property
    def path(self) -> str:
        d = self.request.downloadDirectory()
        f = self.request.downloadFileName()
        return str(Path(d) / f) if d and f else ""

    @property
    def received(self) -> int:
        return self.request.receivedBytes()

    @property
    def total(self) -> int:
        return self.request.totalBytes()

    @property
    def state(self) -> str:
        s = self.request.state()
        return {
            QWebEngineDownloadRequest.DownloadState.DownloadRequested: "in_progress",
            QWebEngineDownloadRequest.DownloadState.DownloadInProgress: "in_progress",
            QWebEngineDownloadRequest.DownloadState.DownloadCompleted: "completed",
            QWebEngineDownloadRequest.DownloadState.DownloadCancelled: "cancelled",
            QWebEngineDownloadRequest.DownloadState.DownloadInterrupted: "failed",
        }.get(s, "in_progress")

    # -- actions ----------------------------------------------------------------
    def pause(self) -> None:
        self.request.pause()

    def resume(self) -> None:
        self.request.resume()

    def cancel(self) -> None:
        self.request.cancel()


class DownloadManager(QObject):
    """Connected to every profile's downloadRequested signal."""

    download_started = pyqtSignal(object)      # DownloadItem
    download_updated = pyqtSignal(str)
    download_finished = pyqtSignal(str, bool)  # id, success
    warn_requested = pyqtSignal(object, object)  # (item-factory info, callback)

    def __init__(self, settings, store):
        super().__init__()
        self.settings = settings
        self.store = store
        self.active: Dict[str, DownloadItem] = {}

    # ------------------------------------------------------------------ #
    def handle_request(self, request: QWebEngineDownloadRequest) -> None:
        url = request.url().toString()
        suggested = request.suggestedFileName() or "download"
        mime = request.mimeType() if hasattr(request, "mimeType") else ""

        # "Save page as..." downloads carry the page content; always allow.
        if request.isSavePageDownload():
            self._accept(request, url, suggested, mime, danger="", note="")
            return

        risk = DownloadScreening.classify(suggested)
        sb_note = SafeBrowsing(True).check_download_url(url)
        danger = ""
        note = ""
        if self.settings.get("security.download_warnings", True):
            if risk == "danger":
                danger = DownloadScreening.message("danger", suggested)
            elif risk == "warn":
                note = DownloadScreening.message("warn", suggested)
            if sb_note:
                note = f"Source flagged locally: {sb_note}"

        if danger:
            # Ask the user before saving executables. Never auto-accept.
            self.warn_requested.emit(
                {"url": url, "filename": suggested, "danger": danger, "note": note},
                lambda allowed: self._user_decided(request, url, suggested, mime,
                                                   danger, note, allowed))
            return
        self._accept(request, url, suggested, mime, danger="", note=note)

    def _user_decided(self, request, url, suggested, mime, danger, note, allowed) -> None:
        if allowed:
            self._accept(request, url, suggested, mime, danger=danger, note=note)
        else:
            request.cancel()

    # ------------------------------------------------------------------ #
    def _accept(self, request, url, suggested, mime, danger, note) -> None:
        did = uuid.uuid4().hex[:12]
        target_dir = self.settings.get("downloads.dir") or str(paths.downloads_dir())
        try:
            Path(target_dir).mkdir(parents=True, exist_ok=True)
        except OSError:
            target_dir = str(Path.home() / "Downloads")
        if not self.settings.get("downloads.ask_where_to_save"):
            request.setDownloadDirectory(target_dir)
            request.setDownloadFileName(self._unique_name(target_dir, suggested))
        # accept AFTER directory is configured
        request.accept()

        item = DownloadItem(did, request, self.store)
        self.active[did] = item
        self.store.add_download(did, url, request.downloadDirectory() + "/" +
                                request.downloadFileName(),
                                state="in_progress", total=request.totalBytes(),
                                mime=mime)
        if danger:
            self.store.update_download(did, danger=danger or note)
        elif note:
            self.store.update_download(did, danger=note)

        request.receivedBytesChanged.connect(lambda: self._on_progress(did))
        request.stateChanged.connect(lambda: self._on_state(did))
        self.download_started.emit(item)
        self.download_updated.emit(did)

    def _unique_name(self, directory: str, filename: str) -> str:
        base, ext = os.path.splitext(filename or "download")
        candidate = base + ext
        i = 1
        while os.path.exists(os.path.join(directory, candidate)) and i < 999:
            candidate = f"{base} ({i}){ext}"
            i += 1
        return candidate

    # ------------------------------------------------------------------ #
    def _on_progress(self, did: str) -> None:
        item = self.active.get(did)
        if not item:
            return
        self.store.update_download(did, received=item.received,
                                   total=item.total if item.total >= 0 else None)
        self.download_updated.emit(did)

    def _on_state(self, did: str) -> None:
        item = self.active.get(did)
        if not item:
            return
        state = item.state
        self.store.update_download(did, state=state,
                                   finished=state in ("completed", "failed", "cancelled"))
        if state == "completed":
            self._post_download_check(item)
            self.download_finished.emit(did, True)
            self.active.pop(did, None)
        elif state in ("failed", "cancelled"):
            reason = item.request.interruptReasonString() if state == "failed" else ""
            if reason:
                self.store.update_download(did, danger=f"failed: {reason}")
            self.download_finished.emit(did, False)
            if state != "failed" or not item.request.interruptReasonString():
                self.active.pop(did, None)
            else:
                self.download_updated.emit(did)
        else:
            self.download_updated.emit(did)

    def _post_download_check(self, item: DownloadItem) -> None:
        """Optional user-configured antivirus scan hook (runs locally)."""
        cmd = (self.settings.get("advanced.scan_command") or "").strip()
        if not cmd or "%p" not in cmd:
            return
        path = item.path
        if not path or not os.path.exists(path):
            return
        try:
            import subprocess
            subprocess.Popen(cmd.replace("%p", path).split(),
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            self.store.update_download(item.id, danger="scanned with local tool (async)")
        except OSError:
            pass

    # ------------------------------------------------------------------ #
    def item(self, did: str) -> Optional[DownloadItem]:
        return self.active.get(did)

    def recent_warnings(self, limit: int = 8) -> List[str]:
        out = []
        for r in self.store.downloads(40):
            if r["danger"]:
                out.append(f"{os.path.basename(r['path'])}: {r['danger']}")
        return out[:limit]
