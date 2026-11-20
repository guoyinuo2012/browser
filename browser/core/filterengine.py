"""Adblock filter engine for browser.

Parses Adblock Plus / uBlock-style filter lists and answers two questions
fast, both without a running browser engine so everything is unit-testable:

  * should this network request be blocked?      (``match``)
  * which element-hiding CSS applies to this page? (``css_for``)

Supported syntax (the practical core of EasyList/uAssets lists):

  ||host^ / ||host^path*   anchored network filters (host-indexed)
  generic patterns with * wildcards and | anchors
  /regular-expression/ filters
  @@ whitelist (exception) filters
  $script, image, stylesheet, subdocument, object, media, xmlhttprequest,
    font, websocket, ping, document, popup, other, 3p/third-party,
    1p/~third-party, domain=a|~b, important, match-case, all
  domain##selector, ##selector, #@#selector (element hiding)

Not supported (skipped, counted as skipped): procedural cosmetics (#?#...),
$redirect/$csp/$removeparam modifiers, $badfilter, $sitekey, $cookie.

Performance design (EasyList-scale, tens of thousands of rules):
  * `||host...` rules are indexed by host token; only the remainder after
    the host gets a tiny compiled regex, tested at the offset where the
    host token occurs in the URL.
  * generic rules keep a lowercase literal prefilter substring and compile
    their regex lazily on first candidate hit; they are bucketed by
    requested type so a script request scans only script/any rules.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple

# --------------------------------------------------------------------------
# resource-type vocabulary (ABP names) and Qt mapping
# --------------------------------------------------------------------------

TYPE_NAMES = frozenset({
    "script", "image", "stylesheet", "subdocument", "object", "media",
    "xmlhttprequest", "font", "websocket", "ping", "document", "popup",
    "other",
})

ALIAS_TYPES = {
    "3p": "third-party",
    "1p": "first-party",
    "xhr": "xmlhttprequest",
    "css": "stylesheet",
    "frame": "subdocument",
    "doc": "document",
    "object_subrequest": "object",
    "specifichide": "specifichide",
    "generichide": "generichide",
    "ghide": "generichide",
    "elemhide": "elemhide",
    "ehide": "elemhide",
}

SKIP_OPTIONS = frozenset({
    "badfilter", "sitekey", "cookie", "replace", "urltransform",
    "urllib-block", "inline-font", "inline-script",
})

_QT_TYPE_MAP: Optional[Dict[int, str]] = None


def qt_type_map() -> Dict[int, str]:
    """Qt ResourceType -> ABP type name map (built lazily, needs Qt)."""
    global _QT_TYPE_MAP
    if _QT_TYPE_MAP is None:
        try:
            from PyQt6.QtWebEngineCore import QWebEngineUrlRequestInfo as R
            RT = R.ResourceType
            _QT_TYPE_MAP = {
                int(RT.ResourceTypeScript): "script",
                int(RT.ResourceTypeImage): "image",
                int(RT.ResourceTypeStylesheet): "stylesheet",
                int(RT.ResourceTypeSubFrame): "subdocument",
                int(RT.ResourceTypeObject): "object",
                int(RT.ResourceTypeMedia): "media",
                int(RT.ResourceTypeXhr): "xmlhttprequest",
                int(RT.ResourceTypeFontResource): "font",
                int(RT.ResourceTypeWebSocket): "websocket",
                int(RT.ResourceTypePing): "ping",
                int(RT.ResourceTypeFavicon): "image",
                int(RT.ResourceTypeSubResource): "other",
                int(RT.ResourceTypePrefetch): "other",
                int(RT.ResourceTypeJson): "xmlhttprequest",
                int(RT.ResourceTypeServiceWorker): "other",
                int(RT.ResourceTypeWorker): "other",
                int(RT.ResourceTypeSharedWorker): "other",
                int(RT.ResourceTypeCspReport): "other",
                int(RT.ResourceTypePluginResource): "object",
                int(RT.ResourceTypeUnknown): "other",
            }
        except Exception:                        # pragma: no cover - Qt missing
            _QT_TYPE_MAP = {}
    return _QT_TYPE_MAP


def type_for_qt(qt_type: int) -> str:
    """Translate a Qt ResourceType int into an ABP type name."""
    return qt_type_map().get(int(qt_type), "other")


# --------------------------------------------------------------------------
# rule object
# --------------------------------------------------------------------------

@dataclass
class NetworkRule:
    """One network filter: pattern form, type/party/domain options."""
    raw: str
    # host-indexed form: key = host token from `||key`; rem = regex for the
    # remainder of the pattern after the key, anchored at the key's end.
    key: str = ""
    rem: Optional[re.Pattern] = None
    # generic form: regex matched against the whole URL (compiled lazily)
    pattern: str = ""
    _regex: Optional[re.Pattern] = None
    _regex_failed: bool = False
    lit: str = ""                       # literal prefilter ("" = skip test)
    # shared option fields
    types: Set[str] = field(default_factory=set)        # empty = all types
    bad_types: Set[str] = field(default_factory=set)
    third_party: Optional[bool] = None
    domains: Set[str] = field(default_factory=set)      # $domain= positives
    bad_domains: Set[str] = field(default_factory=set)
    important: bool = False
    case_sensitive: bool = False

    def regex(self) -> Optional[re.Pattern]:
        """Lazily compiled regex for generic patterns (None = invalid)."""
        if self._regex is None and not self._regex_failed:
            try:
                flags = 0 if self.case_sensitive else re.I
                self._regex = re.compile(self.pattern, flags)
            except re.error:
                self._regex_failed = True
        return self._regex

    def applies_to(self, rtype: str, third_party: bool,
                   first_party_host: str) -> bool:
        if self.types and rtype not in self.types:
            return False
        if rtype in self.bad_types:
            return False
        if self.third_party is True and not third_party:
            return False
        if self.third_party is False and third_party:
            return False
        if self.domains or self.bad_domains:
            fp = (first_party_host or "").lower().rstrip(".")
            if self.domains and not any(
                    fp == d or fp.endswith("." + d) for d in self.domains):
                return False
            for d in self.bad_domains:
                if fp == d or fp.endswith("." + d):
                    return False
        return True


@dataclass
class CosmeticRule:
    """One element-hiding rule: CSS selector plus optional domains."""
    selector: str
    domains: Set[str]      # empty = generic (applies everywhere)
    exception: bool = False


# --------------------------------------------------------------------------
# parsing helpers
# --------------------------------------------------------------------------

_SEPARATOR = r"(?:[\/?#:=&@%]|\Z)"        # what the `^` anchor means
_OPTS_RE = re.compile(r"^[a-z0-9~,=|._+-]+$", re.I)


def _convert(pattern: str) -> Tuple[str, str]:
    """Pattern -> (regex_body, literal_prefilter). Lowercased."""
    p = pattern.lower()
    out = []
    lit = []
    lit_done = False
    i = 0
    if p.startswith("||"):
        out.append(r"^[a-z][a-z0-9+.-]*:\/\/(?:[^\/?#@]*\.)?")
        i = 2
    elif p.startswith("|"):
        out.append(r"^")
        i = 1
    while i < len(p):
        c = p[i]
        if c == "^":
            out.append(_SEPARATOR)
        elif c == "*":
            out.append(".*")
        elif c == "|":
            out.append(r"$" if i == len(p) - 1 else "|")
        else:
            out.append(re.escape(c))
            if not lit_done:
                lit.append(c)
        i += 1
        if not lit_done and (c in "*^|" or (c == "/" and len(lit) >= 4)):
            # stop the literal at the first wildcard; a '/' after a decent
            # prefix is a good stopping point too (pattern->path boundary)
            if c in "*^|":
                lit_done = True
    return "".join(out), "".join(lit)


def _split_options(line: str) -> Tuple[str, str]:
    """Split `pattern$opts`; tolerate `$` inside regex patterns."""
    if "$" not in line:
        return line, ""
    pattern, opts = line.rsplit("$", 1)
    if _OPTS_RE.match(opts):
        return pattern, opts
    return line, ""


def _apply_options(opts: str, rule: NetworkRule, extra: dict) -> bool:
    """Fill option fields; returns False if the rule must be skipped."""
    for opt in opts.split(","):
        opt = opt.strip()
        if not opt:
            continue
        neg = opt.startswith("~")
        val = opt[1:] if neg else opt
        if val.startswith(("domain=", "domains=")):
            spec = val.split("=", 1)[1]
            for d in spec.split("|"):
                d = d.strip().lower()
                if not d:
                    continue
                if d.startswith("~"):
                    rule.bad_domains.add(d[1:])
                else:
                    rule.domains.add(d)
        elif val in ("third-party", "3p"):
            rule.third_party = not neg
        elif val in ("first-party", "1p"):
            rule.third_party = neg
        elif val == "important":
            rule.important = True
        elif val == "match-case":
            extra["match_case"] = True
        elif val == "all":
            pass
        elif val in TYPE_NAMES or val in ALIAS_TYPES:
            name = ALIAS_TYPES.get(val, val)
            if name in ("generichide", "elemhide", "specifichide"):
                extra["hide_kind"] = name
            else:
                (rule.bad_types if neg else rule.types).add(name)
        elif val in SKIP_OPTIONS:
            return False
        elif val.startswith(("redirect", "csp=", "removeparam", "cookie=",
                            "replace=", "urllib-block=")):
            pass                              # block, but drop the modifier
        elif val == "badfilter":
            return False
        else:
            return False                     # unknown option: skip rule
    return True


def _pattern_host(pattern: str) -> str:
    """Extract the literal host part of a `||host...` pattern (may hold *)."""
    p = pattern
    for stop in "/", "^", "|":
        idx = p.find(stop)
        if idx != -1:
            p = p[:idx]
    return p.strip(".").lower()


# --------------------------------------------------------------------------
# the engine
# --------------------------------------------------------------------------

class FilterEngine:
    """Compiled filter list set: network rules + element hiding."""

    def __init__(self) -> None:
        self.host_rules: Dict[str, List[NetworkRule]] = {}
        self.host_exceptions: Dict[str, List[NetworkRule]] = {}
        # generic rules bucketed by requested type + type-unspecific bucket
        self.gen_by_type: Dict[str, List[NetworkRule]] = {}
        self.gen_exc_by_type: Dict[str, List[NetworkRule]] = {}
        self.gen_any: List[NetworkRule] = []
        self.gen_exc_any: List[NetworkRule] = []
        self.cosmetic: List[CosmeticRule] = []
        self.cosmetic_exceptions: Set[str] = set()
        self.rule_count = 0
        self.skipped = 0

    # -- loading ------------------------------------------------------------
    def load_text(self, text: str) -> int:
        added = 0
        for raw in text.splitlines():
            line = raw.strip()
            if not line or line[0] in "![" or line.startswith((";", "# ", "#;")):
                continue

            # --- element hiding (may be domain-prefixed: domain##sel) ---
            if "#@#" in line:
                _, _, sel = line.partition("#@#")
                sel = sel.strip()
                if sel:
                    self.cosmetic_exceptions.add(sel)
                    self.rule_count += 1
                    added += 1
            elif "##" in line:
                dom, _, sel = line.partition("##")
                sel = sel.strip()
                if sel:
                    domains = {d.strip().lower() for d in dom.split(",")
                               if d.strip()}
                    self.cosmetic.append(CosmeticRule(sel, domains))
                    self.rule_count += 1
                    added += 1
            elif line.startswith("#"):
                self.skipped += 1       # #?# procedural, #%# snippet, comments
                continue
            else:
                added += self._load_network(line)
        return added

    def _load_network(self, line: str) -> int:
        exception = line.startswith("@@")
        body = line[2:] if exception else line
        pattern, opts = _split_options(body)
        if not pattern:
            self.skipped += 1
            return 0

        rule = NetworkRule(raw=line)
        extra: dict = {}
        if opts and not _apply_options(opts, rule, extra):
            self.skipped += 1
            return 0
        rule.case_sensitive = bool(extra.get("match_case", False))
        flags = 0 if rule.case_sensitive else re.I

        if (pattern.startswith("/") and pattern.endswith("/")
                and len(pattern) > 2):
            rule.pattern = pattern[1:-1]
            try:
                rule._regex = re.compile(rule.pattern, flags)
            except re.error:
                self.skipped += 1
                return 0
        elif pattern.startswith("||"):
            host = _pattern_host(pattern[2:])
            if host and "*" not in host:
                rule.key = host
                remainder = pattern[2 + len(host):]
                body_regex, _lit = _convert(remainder if remainder else "^$")
                try:
                    rule.rem = re.compile(body_regex, flags)
                except re.error:
                    self.skipped += 1
                    return 0
                table = (self.host_exceptions if exception
                         else self.host_rules)
                table.setdefault(host, []).append(rule)
                self.rule_count += 1
                return 1
            # wildcarded host: fall through to generic
            rule.pattern, rule.lit = _convert(pattern)
        else:
            rule.pattern, rule.lit = _convert(pattern)

        # generic bucketing
        buckets = ((self.gen_exc_by_type if exception else self.gen_by_type),
                   self.gen_exc_any if exception else self.gen_any)
        if rule.types and not rule.bad_types:
            by_type, any_bucket = buckets
            for t in rule.types:
                by_type.setdefault(t, []).append(rule)
        else:
            buckets[1].append(rule)
        self.rule_count += 1
        return 1

    # -- network matching -----------------------------------------------------
    def match(self, url_text: str, url_host: str, first_party_host: str,
              rtype: str = "other") -> bool:
        """True = request should be blocked."""
        low_url = url_text.lower()
        host = (url_host or "").lower().rstrip(".")
        fp = (first_party_host or "").lower().rstrip(".")
        third_party = bool(fp) and host != fp and not (
            host.endswith("." + fp) or fp.endswith("." + host))
        if not fp:
            third_party = False                  # navigations are first-party

        # 1. exceptions (whitelist wins, unless a $important rule matches)
        exception_matched = False
        for lst in self._suffix_lists(host, self.host_exceptions):
            for rule in lst:
                if not rule.applies_to(rtype, third_party, fp):
                    continue
                if self._key_hits(rule, url_text, low_url, host):
                    exception_matched = True
        for rule in self._bucket_for(self.gen_exc_by_type,
                                     self.gen_exc_any, rtype):
            text = url_text if rule.case_sensitive else low_url
            if rule.lit and rule.lit not in low_url:
                continue
            if not rule.applies_to(rtype, third_party, fp):
                continue
            rx = rule.regex()
            if rx and rx.search(text):
                exception_matched = True

        # 2. block rules: host-indexed first, then generic
        blocked = False
        for lst in self._suffix_lists(host, self.host_rules):
            for rule in lst:
                if not rule.applies_to(rtype, third_party, fp):
                    continue
                if self._key_hits(rule, url_text, low_url, host):
                    if rule.important:
                        return True
                    blocked = True
        for rule in self._bucket_for(self.gen_by_type, self.gen_any, rtype):
            # cheapest test first: literal prefilter, then options, then regex
            text = url_text if rule.case_sensitive else low_url
            if rule.lit and rule.lit not in low_url:
                continue
            if not rule.applies_to(rtype, third_party, fp):
                continue
            rx = rule.regex()
            if rx and rx.search(text):
                if rule.important:
                    return True
                blocked = True
        return blocked and not exception_matched

    def _key_hits(self, rule: NetworkRule, url_text: str, low_url: str,
                  host: str) -> bool:
        """`||key...` rule: does the host token occur at a boundary and does
        the remainder regex match right after it? The host token is located
        case-insensitively (hosts are case-insensitive); the remainder is
        matched against the original-case URL only for $match-case rules."""
        pos = low_url.find(rule.key)
        if pos == -1:
            return False
        if pos > 0:
            prev = low_url[pos - 1]
            if prev == ".":
                pass                     # subdomain boundary
            elif prev == "/" and pos >= 3 and low_url[pos - 3:pos] == "://":
                pass                     # scheme boundary
            else:
                return False
        if rule.case_sensitive and len(url_text) == len(low_url):
            rem = url_text[pos + len(rule.key):]
        else:
            rem = low_url[pos + len(rule.key):]
        return bool(rule.rem.match(rem))

    @staticmethod
    def _suffix_lists(host: str, table: Dict[str, List[NetworkRule]]):
        parts = host.split(".")
        for i in range(len(parts)):
            lst = table.get(".".join(parts[i:]))
            if lst:
                yield lst

    @staticmethod
    def _bucket_for(by_type: Dict[str, List[NetworkRule]],
                    any_bucket: List[NetworkRule], rtype: str):
        lst = by_type.get(rtype)
        if lst:
            return any_bucket + lst
        return any_bucket

    # -- element hiding -------------------------------------------------------
    def css_for(self, page_host: str) -> str:
        host = (page_host or "").lower().rstrip(".")
        selectors = []
        for r in self.cosmetic:
            if r.selector in self.cosmetic_exceptions:
                continue
            if r.domains:
                ok = any(host == d or host.endswith("." + d)
                         for d in r.domains)
                if not ok:
                    continue
            selectors.append(r.selector)
        if not selectors:
            return ""
        return (",".join(selectors) +
                "{display:none !important;visibility:hidden !important;}")
