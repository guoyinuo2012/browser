"""Search engines and omnibox URL logic for browser.

Engines are configurable; the default is DuckDuckGo but nothing forces the
user to keep it. Suggestions come from the selected engine only when
`privacy.suggestions_in_omnibox` is enabled.
"""

from __future__ import annotations

import re
from urllib.parse import quote_plus, urlparse

from ..constants import SCHEME_STR


class SearchEngine:
    """One search engine definition: search and suggestion endpoints."""
    def __init__(self, name: str, search_url: str, suggest_url: str = "",
                 homepage: str = ""):
        self.name = name
        self.search_url = search_url          # contains {query}
        self.suggest_url = suggest_url        # contains {query}; optional
        self.homepage = homepage

    def search(self, query: str) -> str:
        return self.search_url.replace("{query}", quote_plus(query))

    def suggestions(self, query: str) -> str:
        return self.suggest_url.replace("{query}", quote_plus(query)) if self.suggest_url else ""


BUILTIN_ENGINES = {
    "Google":      SearchEngine("Google", "https://www.google.com/search?q={query}",
                                "https://suggestqueries.google.com/complete/search?client=firefox&q={query}",
                                "https://www.google.com"),
    "Bing":        SearchEngine("Bing", "https://www.bing.com/search?q={query}",
                                "https://api.bing.com/osjson.aspx?query={query}",
                                "https://www.bing.com"),
    "DuckDuckGo":  SearchEngine("DuckDuckGo", "https://duckduckgo.com/?q={query}",
                                "https://duckduckgo.com/ac/?q={query}&type=list",
                                "https://duckduckgo.com"),
    "Brave Search": SearchEngine("Brave Search", "https://search.brave.com/search?q={query}",
                                 "", "https://search.brave.com"),
    "Startpage":   SearchEngine("Startpage", "https://www.startpage.com/sp/search?query={query}",
                                "", "https://www.startpage.com"),
    "Ecosia":      SearchEngine("Ecosia", "https://www.ecosia.org/search?q={query}",
                                "https://ac.ecosia.org/?q={query}&type=list",
                                "https://www.ecosia.org"),
    "Mojeek":      SearchEngine("Mojeek", "https://www.mojeek.com/search?q={query}",
                                "", "https://www.mojeek.com"),
}

_KEYWORDS: dict[str, str] = {
    "@g": "Google", "@bing": "Bing", "@d": "DuckDuckGo", "@ddg": "DuckDuckGo",
    "@b": "Brave Search", "@s": "Startpage", "@e": "Ecosia", "@m": "Mojeek",
}

_URL_RE = re.compile(
    r"^(?:[a-z][a-z0-9+.-]*:/{1,3})?"          # optional scheme
    r"(?:localhost|(\d{1,3}\.){3}\d{1,3}|"     # localhost / IPv4
    r"(\[[0-9a-fA-F:.]+\])|"                   # IPv6 literal
    r"[a-z0-9](?:[a-z0-9\-]*[a-z0-9])?"        # domain label
    r"(?:\.[a-z0-9](?:[a-z0-9\-]*[a-z0-9])?)+)"# more labels + TLD
    r"(?::\d{1,5})?"                           # optional port
    r"(?:[/?#].*)?$",                          # optional path/query
    re.IGNORECASE)


def looks_like_url(text: str) -> bool:
    """Heuristic: should this omnibox input be treated as an address?"""
    t = text.strip()
    if not t or " " in t and not t.startswith(("http://", "https://")):
        return False
    p = urlparse(t if "://" in t else "https://" + t)
    host = (p.hostname or "").lower()
    if not host:
        return False
    if host == "localhost":
        return True
    try:
        import ipaddress
        ipaddress.ip_address(host)
        return True
    except ValueError:
        pass
    labels = host.split(".")
    if len(labels) < 2:
        return False
    tld = labels[-1]
    return bool(tld) and tld.isalpha() and len(tld) >= 2


def normalize_input(text: str, engine: SearchEngine) -> tuple[str, str]:
    """Classify omnibox input. Returns (url, kind) with kind in
    'search' | 'url' | 'keyword_search' | 'internal'."""
    t = text.strip()
    if not t:
        return ("", "search")
    low = t.lower()
    if low.startswith(SCHEME_STR + "://"):
        return (t, "internal")
    if low in _KEYWORDS:
        eng = BUILTIN_ENGINES[_KEYWORDS[low]]
        return (eng.homepage, "url")
    if t.startswith(_KEYWORDS.get(low[:2], "@@") and "@") and " " in t:
        kw, _, rest = t.partition(" ")
        eng_name = _KEYWORDS.get(kw.lower())
        if eng_name:
            eng = BUILTIN_ENGINES.get(eng_name) or _custom_engine_by_name(eng_name)
            if eng:
                return (eng.search(rest), "keyword_search")
    if looks_like_url(t):
        if "://" not in t:
            # HTTPS-first for public hosts; localhost and IPs usually speak
            # plain http (development servers, routers).
            host = (urlparse(t if "://" in t else "https://" + t).hostname or "")
            insecure_host = (host == "localhost"
                             or host.startswith("127.")
                             or host in ("::1", "[::1]")
                             or _is_ip(host))
            t = ("http://" if insecure_host else "https://") + t
        return (t, "url")
    return (engine.search(t), "search")


def _custom_engine_by_name(name: str) -> SearchEngine | None:
    return None  # custom engines are resolved by the caller, not here


def _is_ip(host: str) -> bool:
    try:
        import ipaddress
        ipaddress.ip_address(host.strip("[]"))
        return True
    except ValueError:
        return False


def parse_suggestions_osjson(data: bytes) -> list[str]:
    """Parse OpenSearch suggestions (used by Google/Bing/Ecosia/DDG list type)."""
    import json
    try:
        obj = json.loads(data.decode("utf-8", "replace"))
        if isinstance(obj, list) and len(obj) >= 2 and isinstance(obj[1], list):
            return [str(x) for x in obj[1]][:8]
        # DDG list type: ["query", ["s1", ...]]
        if isinstance(obj, list) and obj and isinstance(obj[0], list):
            return [str(x) for x in obj[0]][:8]
    except Exception:
        pass        # any malformed engine payload degrades to no suggestions
    return []
