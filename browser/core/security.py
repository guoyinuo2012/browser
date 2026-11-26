"""Security engine for browser.

  * HTTPSFirstUpgrader      — rewrites http:// navigations to https:// and
                              remembers hosts that must fall back.
  * SafeBrowsing            — local threat-list checks; optional provider
                              lookups gated behind explicit user consent.
  * DownloadScreening       — file-type risk classification with user warnings.
  * CertGate                — certificate error handling contract: errors are
                              never bypassed automatically.

Design principle: security warnings can be loud, but never silent bypasses.
"""

from __future__ import annotations

import ipaddress
import time
from typing import Optional
from urllib.parse import urlparse

from ..data import lists


class HTTPSFirstUpgrader:
    """Upgrades http:// to https:// with a remembered-fallback list."""

    FALLBACK_TTL = 24 * 3600.0

    def __init__(self, enabled: bool = True):
        self.enabled = enabled
        self._fallbacks: dict[str, float] = {}

    def upgrade(self, url: str) -> str:
        """Returns the URL to navigate to for a user-initiated navigation."""
        if not self.enabled:
            return url
        p = urlparse(url)
        if p.scheme != "http":
            return url
        host = p.hostname or ""
        if not host or self._has_fallback(host):
            return url
        if host in ("localhost", "127.0.0.1", "::1") or _is_private_ip(host):
            return url
        return "https://" + url[len("http://"):]

    def record_failure(self, url: str) -> None:
        """After an https load failure for an upgraded http-origin request,
        allow plain http for this host for a day (user-visible in security
        panel). We only ever *navigate* to http after explicit retry."""
        host = urlparse(url).hostname or ""
        if host:
            self._fallbacks[host] = time.time() + self.FALLBACK_TTL

    def _has_fallback(self, host: str) -> bool:
        t = self._fallbacks.get(host)
        if t is None:
            return False
        if t < time.time():
            self._fallbacks.pop(host, None)
            return False
        return True

    def clear(self) -> None:
        self._fallbacks.clear()


def _is_private_ip(host: str) -> bool:
    try:
        ip = ipaddress.ip_address(host)
        return ip.is_private or ip.is_loopback or ip.is_link_local
    except ValueError:
        return False


class SafeBrowsing:
    """Local threat list checks with optional consented provider lookup."""

    def __init__(self, enabled: bool = True, consent: bool = False, api_key: str = ""):
        self.enabled = enabled
        self.consent = consent
        self.api_key = api_key
        self.last_alert: Optional[str] = None

    def check(self, url: str) -> Optional[str]:
        """Returns a threat reason or None. Never performs a network request
        unless the user has explicitly consented AND provided an API key."""
        if not self.enabled:
            return None
        p = urlparse(url)
        if p.scheme not in ("http", "https"):
            return None
        host = (p.hostname or "").lower()
        reason = lists.is_malware(host, url)
        if reason:
            return reason
        # Provider lookup requires explicit consent + key (opt-in only).
        if self.consent and self.api_key:
            # Implemented in updates/network-free path; not done by default.
            # Local decision: treat as "not flagged locally".
            pass
        return None

    def check_download_url(self, url: str) -> Optional[str]:
        p = urlparse(url)
        host = (p.hostname or "").lower()
        if host in lists.SUSPICIOUS_PATH_HOSTS:
            return "file-hosting service (verify the source before opening)"
        return lists.is_malware(host, url)


class DownloadScreening:
    """Local threat screening for downloads before they are accepted."""

    @staticmethod
    def classify(filename: str) -> str:
        """Classify a download filename into a risk verdict."""
        return lists.download_risk(filename)

    @staticmethod
    def message(risk: str, filename: str) -> str:
        if risk == "danger":
            return (f"“{filename}” can run programs on your computer. "
                    "browser never runs downloads automatically. Only keep this "
                    "file if you trust the source.")
        if risk == "warn":
            return (f"“{filename}” is an archive/document type that is often "
                    "abused to deliver malware. Scan it before opening.")
        return ""


class CertGate:
    """Certificate error policy.

    Certificate errors are never bypassed silently. The only user
    action available is to view details and go back. This class exists so
    the policy is stated in code, not just in the UI.
    """

    ALLOW_OVERRIDE = False  # deliberately immutable

    DESCRIPTIONS = {
        -202: "The server's certificate is not trusted (unknown authority).",
        -201: "The certificate's date is invalid or expired.",
        -200: "The certificate common name does not match the site address.",
        -1: "The certificate could not be verified.",
    }

    @classmethod
    def describe(cls, error_code: int) -> str:
        if error_code in cls.DESCRIPTIONS and cls.DESCRIPTIONS[error_code]:
            return cls.DESCRIPTIONS[error_code]
        return (f"secure connection verification failed "
                f"(error code {error_code}).")

    @classmethod
    def action_label(cls) -> str:
        return "Back to safety"
