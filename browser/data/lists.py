"""Bundled, locally-maintained lists for privacy and security filtering.

These lists are curated by hand from well-known, public tracker/ad/threat
catalogs. They are shipped inside the application and checked **locally**:
no request is ever sent to any list provider. Users can extend them via
Settings → Privacy (custom block list).

Lists:
    TRACKER_DOMAINS      — analytics / ad / session-replay / pixel trackers
    TRACKER_PATHS        — well-known tracker URL paths on first-party hosts
    MALWARE_DOMAINS      — locally known malware/phishing distribution hosts
    DANGEROUS_EXTENSIONS — download file types treated as high risk
    SUSPICIOUS_EXTENSIONS— file types that merit a warning
"""

from __future__ import annotations

# --------------------------------------------------------------------------
# Tracker / ad / fingerprinting / session-replay hosts.
# Requests to these are dropped before any network connection is made.
# --------------------------------------------------------------------------
TRACKER_DOMAINS = frozenset({
    # --- Google/DoubleClick ads & analytics ---
    "doubleclick.net", "googlesyndication.com", "googleadservices.com",
    "googletagmanager.com", "google-analytics.com", "analytics.google.com",
    "googletagservices.com", "adservice.google.com", "pagead2.googlesyndication.com",
    "app-measurement.com", "firebaseinstallations.googleapis.com",
    # --- Meta / Facebook / Instagram ---
    "facebook.net", "connect.facebook.net", "graph.facebook.com",
    "an.facebook.com", "ads.twitter.com", "ads-twitter.com",
    "analytics.twitter.com", "static.ads-twitter.com",
    # --- Amazon ads ---
    "amazon-adsystem.com", "amzn.to.ads", "aax.amazon-adsystem.com",
    # --- Microsoft / Bing ---
    "clarity.ms", "bat.bing.com", "bing.com/partner", "ads.microsoft.com",
    "browser.events.data.msn.com", "hubble.extras.adx.microsoft.com",
    # --- Large ad exchanges / SSPs ---
    "adnxs.com", "adsafeprotected.com", "adsrvr.org", "adsystem.com",
    "adzerk.com", "adform.net", "adroll.com", "criteo.com", "criteo.net",
    "casalemedia.com", "openx.net", "pubmatic.com", "rubiconproject.com",
    "smartadserver.com", "sharethrough.com", "taboola.com", "outbrain.com",
    "zedo.com", "spotxchange.com", "teads.tv", "yieldmo.com",
    "indexexchange.com", "bidswitch.net", "districtm.io", "improvedigital.com",
    # --- Analytics ---
    "hotjar.com", "hotjar.io", "mouseflow.com", "fullstory.com",
    "inspectlet.com", "crazyegg.com", "luckyorange.com", "smartlook.com",
    "quantserve.com", "scorecardresearch.com", "chartbeat.com", "parsely.com",
    "matomo.cloud", "segment.io", "segment.com", "amplitude.com",
    "mixpanel.com", "heap.io", "heapanalytics.com", "kissmetrics.com",
    "newrelic.com", "nr-data.net", "branch.io", "appsflyer.com",
    "atdmt.com", "adjust.com", "kochava.com", "singular.net",
    # --- Tag managers & consent-walls that double as trackers ---
    "tealium.com", "tiqcdn.com", "ensighten.com", "optimizely.com",
    "crazyegg.com", "onesignal.com", "pushcrew.com", "webpushs.com",
    # --- Data brokers / identity graphs ---
    "bluekai.com", "demdex.net", "everesttech.net", "krxd.net", "liadm.com",
    "id5-sync.com", "adsco.re", "liveramp.com", "rlcdn.com", "acxiom.com",
    "merkle.com", "liveintent.com", "quantum.com",
    # --- Fingerprinting ---
    "fingerprintjs.com", "fpjs.io", "fptower.com", "iovation.com",
    "threatmetrix.com", "deviceatlas.com", "wurfl.io", "51degrees.com",
    # --- Session replay ---
    "logrocket.com", "logrocket.io", "fullstory.com", "sessioncam.com",
    "clicktale.net", "ghostinspector.com",
    # --- Pixels ---
    "pixel.facebook.com", "ct.pinterest.com", "ads.pinterest.com",
    "ads.linkedin.com", "px.ads.linkedin.com", "snap.licdn.com",
    "analytics.tiktok.com", "ads.tiktok.com", "adsnap.tv",
    "sc-static.net", "tr.snapchat.com",
    # --- Reddit/X trackers ---
    "reddit.com/static/pixel", "alb.reddit.com", "events.redditmedia.com",
    "ads.reddit.com",
    # --- Misc ad networks ---
    "ad.gt", "adgang.com", "adsco.ch", "adspirit.de", "adtechus.com",
    "advertising.com", "advelocity.com", "adversal.com", "adexcite.com",
    "burstly.com", "buzzfeedads.com", "contextweb.com", "cpmstar.com",
    "gumgum.com", "infolinks.com", "media.net", "mgid.com", "popads.net",
    "popcash.net", "propellerads.com", "revcontent.com", "sonobi.com",
    "sulvo.com", "undertone.com", "verigy.com", "wavewerx.com",
    "yieldlab.net", "yldbt.com", "adition.com", "adsnative.com",
    # --- Email tracking ---
    "mailstat.us", "mailtrack.io", "getpic.tv", "streak.com",
    # --- Push notification spam ---
    "onesignal.com", "sendpulse.com", "pushwoosh.com", "notix.co",
})

# Well-known tracking endpoints hosted on first-party/CDN hosts.
TRACKER_PATHS = tuple(p.lower() for p in (
    "/gtm.js", "/gtag/js", "/analytics.js", "/analytics.min.js",
    "/matomo.js", "/piwik.js", "/fb pixel", "/fbevents.js",
    "/collect?v=", "/collect?v=1", "/pagead/", "/ads.js",
    "/fingerprint", "/fp.min.js", "/insights.js",
    "/hotjar-", "/clarity.js", "/segment.js", "/amplitude.js",
    "/mixpanel-", "/telemetry", "/beacon.gif", "/pixel.gif",
    "/pixel.png", "/track.gif", "/event/collect", "/telemetry/collect",
    "/1x1.gif", "/blank.gif", "/o.gif", "/px.gif", "/sp.gif",
))

# Locally-maintained malware/phishing host list. Deliberately small; this is a
# backstop against *known* threats, not a complete web filter. Safe Browsing
# provider checks require separate, explicit user consent.
MALWARE_DOMAINS = frozenset({
    "securelogin-auth.com", "appleid-verify.com", "paypal-secure-login.net",
    "amazon-security-alert.com", "microsoft-support-assist.com",
    "google-account-recovery.net", "bankofamerica-secure.net",
    "chase-verify.com", "wellsfargo-alerts.com", "netflix-billing.net",
    "coinbase-support.net", "metamask-wallet.io", "wallet-connect-app.net",
    "ledger-live-update.com", "trezor-suite.io",
    "drive-download.link", "docs-share.online", "invoice-attachment.net",
    "docusign-sign.online", "adobe-pdf-view.net",
    "delivery-notify.com", "fedex-redelivery.net", "ups-parcel-missed.com",
    "usps-track-package.net", "dhl-delivery-notice.com",
})

# Web/CDN surfaces commonly used to serve malicious payloads.
SUSPICIOUS_PATH_HOSTS = frozenset({
    "cdn.discordapp.com", "objects.githubusercontent.com",
    "anonfiles.com", "gofile.io", "filebin.net", "uguu.se", "litterbox.catbox.moe",
})

DANGEROUS_EXTENSIONS = frozenset({
    ".exe", ".msi", ".msp", ".mst", ".bat", ".cmd", ".com", ".scr", ".pif",
    ".js", ".jse", ".vbs", ".vbe", ".wsf", ".wsh", ".ps1", ".psm1",
    ".hta", ".cpl", ".jar", ".apk", ".app", ".deb", ".rpm", ".dmg",
    ".reg", ".lnk", ".iso", ".img", ".vhd", ".vhdx", ".gadget",
})

SUSPICIOUS_EXTENSIONS = frozenset({
    ".zip", ".rar", ".7z", ".gz", ".tgz", ".cab", ".ace", ".uue",
    ".pdf", ".doc", ".docm", ".docx", ".xls", ".xlsm", ".xlsx", ".ppt",
    ".pptm", ".pptx", ".rtf", ".dll", ".sys", ".so", ".dylib",
})

OPEN_REDIRECT_MARKERS = ("http://", "https://", "//")


def domain_of(host: str) -> str:
    """Effective registrable-ish domain (suffix + one label)."""
    h = host.lower().strip(".")
    parts = h.split(".")
    if h.count(".") <= 1:
        return h
    slds = {"co.uk", "org.uk", "gov.uk", "ac.uk", "com.au", "net.au", "org.au",
            "co.jp", "or.jp", "ne.jp", "com.br", "com.mx", "co.nz", "co.za",
            "com.cn", "com.tw", "com.hk", "com.sg", "com.tr", "com.ar",
            "co.in", "com.ru", "org.cn", "gov.cn"}
    if len(parts) >= 3 and ".".join(parts[-2:]) in slds:
        return ".".join(parts[-3:])
    return ".".join(parts[-2:])


def is_tracker(host: str, path: str = "", first_party: str | None = None) -> bool:
    """True when the request is to a known tracker.

    `first_party` is the host of the page that initiated the request, when
    known; third-party-ness alone is not sufficient to call something a
    tracker, so matching is domain-based.
    """
    d = domain_of(host)
    if d and d in TRACKER_DOMAINS:
        return True
    p = path.lower()
    return any(marker in p for marker in TRACKER_PATHS)


def is_malware(host: str, url: str = "") -> str:
    """Returns a threat reason string, or '' if clean."""
    d = domain_of(host)
    if d in MALWARE_DOMAINS:
        return "known phishing/malware host"
    return ""


def download_risk(filename: str) -> str:
    """Risk assessment for a downloaded file name.

    Returns '' (allowed), 'warn' or 'danger'.
    """
    name = (filename or "").lower()
    dot = name.rfind(".")
    ext = name[dot:] if dot >= 0 else ""
    if ext in DANGEROUS_EXTENSIONS:
        return "danger"
    if ext in SUSPICIOUS_EXTENSIONS:
        return "warn"
    if ext == "" and name:
        return "warn"          # extensionless executables are rare and risky
    return ""


# Privacy protection levels map to behavior knobs.
PROTECTION_LEVELS = {
    "standard":  {"trackers": True,  "third_party_cookies": False, "fingerprinting": "off",
                  "https_first": False, "block_mixed_content": True},
    "balanced":  {"trackers": True,  "third_party_cookies": True,  "fingerprinting": "light",
                  "https_first": True,  "block_mixed_content": True},
    "strict":    {"trackers": True,  "third_party_cookies": True,  "fingerprinting": "strict",
                  "https_first": True,  "block_mixed_content": True},
}


def apply_protection_level(level: str, settings) -> list[str]:
    """Push a named protection level into individual settings. Returns changed keys."""
    preset = PROTECTION_LEVELS.get(level)
    if not preset:
        return []
    changed = []
    mapping = {
        "privacy.block_trackers": "trackers",
        "privacy.block_third_party_cookies": "third_party_cookies",
        "privacy.anti_fingerprinting": "fingerprinting",
        "security.https_first": "https_first",
        "security.block_mixed_content": "block_mixed_content",
    }
    for key, pname in mapping.items():
        old = settings.get(key)
        new = preset[pname]
        if old != new:
            settings.set(key, new, save=False)
            changed.append(key)
    settings.save()
    return changed
