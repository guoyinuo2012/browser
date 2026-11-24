"""Internal browser:// page renderers.

All pages are rendered server-side (in the UI process) by these pure
functions and served through the browser:// scheme handler. Actions are
performed via navigation (browser://<page>?action=...), which keeps the
whole flow synchronous, safe, and testable without a running engine.

Security rules:
  * every dynamic string is HTML-escaped before embedding
  * actions validate parameters and ignore unknown ones
  * password material is never embedded in any page
"""

from __future__ import annotations

import html
import time
import datetime as _dt
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote

APP = "browser"


def e(s: Any) -> str:
    """HTML-escape text for safe interpolation into page templates."""
    return html.escape(str(s), quote=True)


BASE_CSS = """
:root {
  --bg:#121417; --bg2:#191c21; --bg3:#21252c; --fg:#e8eaf0; --fg-dim:#9aa2b1;
  --line:#2a2f38; --accent:#4f8cff; --danger:#ff5d5d; --ok:#3ecf8e; --warn:#ffb84f;
  --card:#1a1e24; --shadow:0 8px 30px rgba(0,0,0,.35);
}
[data-theme="light"] {
  --bg:#f5f6f8; --bg2:#ffffff; --bg3:#eef0f4; --fg:#1a1d23; --fg-dim:#5b6270;
  --line:#dfe3ea; --card:#ffffff; --shadow:0 8px 30px rgba(20,30,60,.12);
}
* { box-sizing:border-box; margin:0; }
body {
  font-family:'Segoe UI',system-ui,-apple-system,sans-serif;
  background:var(--bg); color:var(--fg); font-size:15px; line-height:1.55;
  padding:0; min-height:100vh;
}
header.top {
  display:flex; align-items:center; gap:14px; padding:18px 28px;
  border-bottom:1px solid var(--line); position:sticky; top:0;
  background:var(--bg2); z-index:5;
}
header.top h1 { font-size:19px; font-weight:600; letter-spacing:.2px; }
header.top .brand { color:var(--accent); font-weight:700; }
nav.crumbs { color:var(--fg-dim); font-size:13px; }
main { max-width:960px; margin:0 auto; padding:28px 28px 80px; }
h2 { font-size:17px; margin:26px 0 10px; }
h2:first-of-type { margin-top:6px; }
p.dim { color:var(--fg-dim); }
a { color:var(--accent); text-decoration:none; }
a:hover { text-decoration:underline; }
a.btn, button.btn {
  display:inline-block; background:var(--bg3); color:var(--fg); border:1px solid var(--line);
  border-radius:8px; padding:7px 14px; font-size:13.5px; cursor:pointer; text-decoration:none;
  transition:background .15s, border-color .15s;
}
a.btn:hover, button.btn:hover { background:var(--line); text-decoration:none; }
a.btn.primary, button.btn.primary { background:var(--accent); border-color:var(--accent); color:#fff; }
a.btn.danger, button.btn.danger { color:var(--danger); border-color:var(--danger); }
a.btn.small, button.btn.small { padding:4px 10px; font-size:12.5px; }
.card { background:var(--card); border:1px solid var(--line); border-radius:12px; padding:16px 18px; margin:10px 0; }
.grid { display:grid; gap:12px; }
.grid.cols3 { grid-template-columns:repeat(3, 1fr); }
.grid.cols2 { grid-template-columns:repeat(2, 1fr); }
.stat { background:var(--card); border:1px solid var(--line); border-radius:12px; padding:16px; text-align:center; }
.stat .num { font-size:30px; font-weight:700; color:var(--accent); }
.stat .lbl { color:var(--fg-dim); font-size:12.5px; margin-top:4px; }
table { width:100%; border-collapse:collapse; font-size:13.5px; }
th { text-align:left; color:var(--fg-dim); font-weight:600; font-size:12px;
     text-transform:uppercase; letter-spacing:.5px; padding:8px 10px; border-bottom:1px solid var(--line); }
td { padding:9px 10px; border-bottom:1px solid var(--line); vertical-align:middle; }
tr:last-child td { border-bottom:none; }
input[type=text], input[type=search], input[type=password], select {
  background:var(--bg3); color:var(--fg); border:1px solid var(--line); border-radius:8px;
  padding:8px 10px; font-size:14px; outline:none;
}
input:focus, select:focus { border-color:var(--accent); }
.row { display:flex; align-items:center; gap:10px; flex-wrap:wrap; }
.spread { justify-content:space-between; }
.badge { display:inline-block; padding:2px 9px; border-radius:20px; font-size:11.5px;
         border:1px solid var(--line); color:var(--fg-dim); }
.badge.ok { color:var(--ok); border-color:var(--ok); }
.badge.warn { color:var(--warn); border-color:var(--warn); }
.badge.bad { color:var(--danger); border-color:var(--danger); }
.notice { border-left:3px solid var(--accent); background:var(--card); padding:12px 16px;
          border-radius:0 10px 10px 0; margin:12px 0; font-size:13.5px; }
.notice.warn { border-color:var(--warn); }
.notice.bad { border-color:var(--danger); }
.notice.ok { border-color:var(--ok); }
.muted { color:var(--fg-dim); }
.small { font-size:12.5px; }
.center { text-align:center; }
.mono { font-family:'Cascadia Code','Consolas',monospace; font-size:13px; }
.home-hero { text-align:center; margin:60px 0 30px; }
.home-hero .logo { font-size:56px; font-weight:800; letter-spacing:6px; }
.home-hero .logo span { color:var(--accent); }
.home-search { max-width:560px; margin:0 auto; }
.home-search input { width:100%; padding:14px 18px; font-size:16px; border-radius:12px; }
.tiles { display:grid; grid-template-columns:repeat(4,1fr); gap:12px; max-width:760px; margin:26px auto 0; }
.tiles a.tile { background:var(--card); border:1px solid var(--line); border-radius:12px;
  padding:18px 10px; text-align:center; color:var(--fg); transition:transform .12s, border-color .12s; }
.tiles a.tile:hover { transform:translateY(-2px); border-color:var(--accent); text-decoration:none; }
.tiles .t-ico { font-size:22px; }
.tiles .t-lbl { font-size:12.5px; color:var(--fg-dim); margin-top:6px; }
details.folder summary { cursor:pointer; padding:6px 4px; color:var(--fg); font-weight:600; }
details.folder summary:hover { color:var(--accent); }
ul.bm { list-style:none; padding-left:18px; }
ul.bm li { padding:3px 0; }
.collapse-head { cursor:pointer; }
"""

LOGO = f'<span style="font-weight:800">{APP[:4]}<span style="color:var(--accent)">ser</span></span>'


def page(title: str, body: str, theme: str = "dark", accent: str = "#4f8cff",
         extra_css: str = "", active: str = "") -> str:
    """Wrap a body fragment in the shared internal-page layout."""
    nav = ""
    items = [("home", "Home", "browser://home"), ("history", "History", "browser://history"),
             ("bookmarks", "Bookmarks", "browser://bookmarks"),
             ("downloads", "Downloads", "browser://downloads"),
             ("passwords", "Passwords", "browser://passwords"),
             ("privacy", "Privacy", "browser://privacy"),
             ("adblock", "Ad block", "browser://adblock"),
             ("security", "Security", "browser://security"),
             ("extensions", "Extensions", "browser://extensions"),
             ("settings", "Settings", "browser://settings")]
    for key, label, href in items:
        if key == active:
            nav += f'<a class="btn primary" href="{href}">{label}</a>'
        else:
            nav += f'<a class="btn" href="{href}">{label}</a>'
    return f"""<!DOCTYPE html>
<html data-theme="{e(theme)}">
<head><meta charset="utf-8"><title>{e(title)} — {APP}</title>
<style>{BASE_CSS}{extra_css}
header.top nav {{ display:flex; gap:6px; flex-wrap:wrap; margin-left:auto; }}
header.top nav a.btn {{ font-size:12.5px; padding:5px 11px; }}
</style></head>
<body>
<header class="top">
  <a href="browser://home" style="color:var(--fg); text-decoration:none">{LOGO}</a>
  <nav>{nav}</nav>
</header>
<main>{body}</main>
</body></html>"""


# --------------------------------------------------------------------------- #
# Home / new tab
# --------------------------------------------------------------------------- #
def home(settings, engine_name: str, search_url: str) -> str:
    """The home/new-tab page with search box and quick links."""
    theme = settings.get("appearance.theme")
    if theme == "system":
        theme = "dark"
    accent = settings.get("appearance.accent")
    engine = e(engine_name)
    tiles = [
        ("🛡", "Privacy dashboard", "browser://privacy"),
        ("🔐", "Security", "browser://security"),
        ("⭐", "Bookmarks", "browser://bookmarks"),
        ("🕘", "History", "browser://history"),
        ("⬇", "Downloads", "browser://downloads"),
        ("🔑", "Passwords", "browser://passwords"),
        ("🧩", "Extensions", "browser://extensions"),
        ("⚙", "Settings", "browser://settings"),
    ]
    tiles_html = "".join(
        f'<a class="tile" href="{href}"><div class="t-ico">{ico}</div>'
        f'<div class="t-lbl">{lbl}</div></a>' for ico, lbl, href in tiles)
    body = f"""
<div class="home-hero"><div class="logo">browser<span>.</span></div>
<p class="dim">Private by default. Secure by design.</p></div>
<div class="home-search">
  <form action="browser://search" method="get">
    <input type="search" name="q" placeholder="Search with {engine} or enter address"
           autofocus autocomplete="off">
  </form>
</div>
<div class="tiles">{tiles_html}</div>
<p class="small center muted" style="margin-top:34px">
  Suggestions are sent only to {engine} and only when enabled.
  browser sends nothing anywhere else.</p>"""
    return page("New tab", body, theme, accent)


# --------------------------------------------------------------------------- #
# Search redirect (home search box)
# --------------------------------------------------------------------------- #
def search_redirect(q: str, engine_search_url: str) -> str:
    """Redirect instruction to the chosen search engine."""
    from urllib.parse import quote_plus
    return engine_search_url.replace("{query}", quote_plus(q))


# --------------------------------------------------------------------------- #
# Blocked / error pages
# --------------------------------------------------------------------------- #
def blocked(url: str, reason: str, kind: str = "threat") -> str:
    """Safe-browsing block page for a dangerous URL."""
    if kind == "threat":
        icon, title = "⛔", "This site is dangerous"
        text = (f"browser blocked this page: <b>{e(reason)}</b>. "
                "It may try to steal your information or install malware.")
    else:
        icon, title = "🔒", "Connection is not secure"
        text = e(reason)
    body = f"""
<div class="center" style="margin-top:60px">
  <div style="font-size:64px">{icon}</div>
  <h2 style="font-size:24px; margin:14px 0">{title}</h2>
  <p class="dim" style="max-width:520px; margin:0 auto">{text}</p>
  <p class="mono small muted" style="margin-top:10px">{e(url)}</p>
  <div class="row" style="justify-content:center; margin-top:24px">
    <a class="btn primary" href="browser://home">Go home</a>
    <a class="btn" href="browser://security">Security details</a>
  </div>
</div>"""
    return page("Blocked", body)


def error_page(url: str, title: str, description: str, actions: str = "") -> str:
    """Generic load-error page with a retry affordance."""
    body = f"""
<div class="center" style="margin-top:60px">
  <div style="font-size:60px">🔌</div>
  <h2 style="font-size:23px; margin:14px 0">{e(title)}</h2>
  <p class="dim" style="max-width:540px; margin:0 auto">{e(description)}</p>
  <p class="mono small muted" style="margin-top:10px">{e(url)}</p>
  <div class="row" style="justify-content:center; margin-top:24px">
    <a class="btn primary" href="javascript:void(0)" onclick="location.reload()">Try again</a>
    <a class="btn" href="browser://home">Go home</a>
    {actions}
  </div>
</div>"""
    return page("Error", body)


def cert_error(url: str, detail: str) -> str:
    """Certificate-failure page; there is no bypass control at all."""
    body = f"""
<div class="center" style="margin-top:60px">
  <div style="font-size:60px">🔒</div>
  <h2 style="font-size:23px; margin:14px 0">Your connection is not private</h2>
  <p class="dim" style="max-width:560px; margin:0 auto">
    browser could not verify this website's security certificate. Attackers
    might be trying to steal your information. browser <b>never</b> bypasses
    this warning automatically.</p>
  <div class="notice bad" style="max-width:560px; margin:18px auto; text-align:left">
    <b>Technical details:</b> {e(detail)}</div>
  <p class="mono small muted">{e(url)}</p>
  <div class="row" style="justify-content:center; margin-top:24px">
    <a class="btn primary" href="browser://home">Back to safety</a>
    <a class="btn" href="javascript:void(0)" onclick="location.reload()">Retry</a>
  </div>
</div>"""
    return page("Certificate error", body)


# --------------------------------------------------------------------------- #
# History
# --------------------------------------------------------------------------- #
def history_page(groups, q: str, total: int) -> str:
    """Browsing history grouped by day with delete controls."""
    search_box = f"""
<form method="get" action="browser://history" class="row" style="margin-bottom:14px">
  <input type="search" name="q" value="{e(q)}" placeholder="Search history…" style="flex:1">
  <button class="btn" type="submit">Search</button>
</form>"""
    groups_html = []
    for day, rows in groups:
        items = []
        for r in rows:
            t = _dt.datetime.fromtimestamp(r["visit_time"]).strftime("%H:%M")
            items.append(
                f"<li><span class='muted small'>{t}</span> "
                f"<a href='{e(r['url'])}'>{e(r['title'] or r['url'])}</a> "
                f"<span class='muted small'>{e(r['host'])}</span></li>")
        groups_html.append(
            f"<h2 class='collapse-head'>{e(day)} "
            f"<span class='badge'>{len(rows)}</span></h2><ul class='bm'>{''.join(items)}</ul>")
    if not groups:
        groups_html.append("<p class='dim'>No history entries. Private browsing "
                           "is never recorded.</p>")
    body = f"""
<div class="row spread"><h2 style="margin:0">History <span class="badge">{total} entries</span></h2>
  <div class="row">
    <a class="btn small" href="browser://history?action=clear_last_hour">Clear last hour</a>
    <a class="btn small" href="browser://history?action=clear_last_day">Clear last day</a>
    <a class="btn small danger" href="browser://history?action=clear&confirm=1">Clear all…</a>
  </div>
</div>
{search_box}
{''.join(groups_html)}"""
    return page("History", body, active="history")


def history_confirm_clear() -> str:
    """Confirmation screen for destructive history clears."""
    body = """
<div class="notice warn">Delete <b>all</b> browsing history? This cannot be undone.</div>
<a class="btn danger" href="browser://history?action=clear_confirmed">Yes, delete all history</a>
<a class="btn" href="browser://history" style="margin-left:8px">Cancel</a>"""
    return page("Confirm", body, active="history")


# --------------------------------------------------------------------------- #
# Bookmarks
# --------------------------------------------------------------------------- #
def bookmarks_page(nodes: List[Any], q: str = "", parent_path: str = "") -> str:
    """Bookmark list with nested folders and management links."""
    rows = []
    for n in nodes:
        if n["is_folder"]:
            rows.append(
                f"<details class='folder' style='padding:4px 0'>"
                f"<summary>📁 {e(n['title'])} "
                f"<span class='muted small'>(folder)</span></summary>"
                f"<ul class='bm'><li class='muted small'>Open folder view: "
                f"<a href='browser://bookmarks?folder={e(n['id'])}'>{e(n['title'])}</a></li></ul>"
                f"</details>")
        else:
            rows.append(
                f"<li class='row spread' style='padding:5px 0'>"
                f"<span>📄 <a href='{e(n['url'])}'>{e(n['title'])}</a> "
                f"<span class='muted small'>{e(n['url'])[:60]}</span></span>"
                f"<span class='row'>"
                f"<a class='btn small' href='browser://bookmarks?action=edit&id={n['id']}'>Edit</a>"
                f"<a class='btn small danger' href='browser://bookmarks?action=delete&id={n['id']}'>Delete</a>"
                f"</span></li>")
    listing = "".join(f"<ul class='bm'>{''.join(rows)}</ul>") if rows else \
        "<p class='dim'>No bookmarks yet — click the ⭐ in the address bar.</p>"
    body = f"""
<div class="row spread"><h2 style="margin:0">Bookmarks</h2>
  <div class="row">
    <a class="btn small" href="browser://bookmarks?action=add_folder">New folder</a>
    <a class="btn small" href="browser://bookmarks?action=export_html">Export HTML</a>
    <a class="btn small" href="browser://bookmarks?action=import_html">Import HTML</a>
  </div>
</div>
<p class="muted small">Path: {e(parent_path or 'Bookmarks')} · drag in the sidebar to reorganize</p>
{listing}"""
    return page("Bookmarks", body, active="bookmarks")


def bookmark_edit_page(bid: str, title: str, url: str, duplicate: bool) -> str:
    """Edit form for one bookmark's title, URL and folder."""
    dup_note = ("<div class='notice warn'>Another bookmark already points to "
                "this address.</div>") if duplicate else ""
    body = f"""
<h2>Edit bookmark</h2>
{dup_note}
<form method="get" action="browser://bookmarks" class="card">
  <input type="hidden" name="action" value="save_edit">
  <input type="hidden" name="id" value="{e(bid)}">
  <p><input type="text" name="title" value="{e(title)}" style="width:100%" placeholder="Title"></p>
  <p><input type="text" name="url" value="{e(url)}" style="width:100%" placeholder="URL"></p>
  <button class="btn primary" type="submit">Save</button>
  <a class="btn" href="browser://bookmarks">Cancel</a>
</form>"""
    return page("Edit bookmark", body, active="bookmarks")


# --------------------------------------------------------------------------- #
# Downloads
# --------------------------------------------------------------------------- #
def _fmt_size(n: int) -> str:
    """Human-readable byte size."""
    if n < 0:
        return "—"
    size = float(n)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024.0
    return f"{size:.1f} GB"


def downloads_page(rows: List[Any]) -> str:
    """Download list with state, progress and security verdicts."""
    items = []
    for r in rows:
        state = r["state"]
        badge = {"completed": "ok", "in_progress": "warn", "cancelled": "muted",
                 "failed": "bad"}.get(state, "")
        danger = ""
        if r["danger"]:
            danger = f"<div class='notice warn small'>⚠ {e(r['danger'])}</div>"
        progress = ""
        if state == "in_progress" and r["total_bytes"] > 0:
            pct = min(100, r["received_bytes"] * 100 // r["total_bytes"])
            progress = (f"<div class='small muted'>{pct}% of "
                        f"{_fmt_size(r['total_bytes'])}</div>")
        items.append(f"""
<tr>
  <td>
    <b>{e(r['path'].replace(chr(92), '/').split('/')[-1])}</b>{danger}
    <div class='muted small'>{e(r['path'])}</div>{progress}
  </td>
  <td><span class='badge {badge}'>{e(state)}</span></td>
  <td class='row'>
    <a class='btn small' href='browser://downloads?action=open&id={e(r['id'])}'>Open</a>
    <a class='btn small' href='browser://downloads?action=show&id={e(r['id'])}'>Show in folder</a>
    <a class='btn small danger' href='browser://downloads?action=remove&id={e(r['id'])}'>Remove</a>
  </td>
</tr>""")
    table = ("<table><tr><th>File</th><th>Status</th><th>Actions</th></tr>"
             + "".join(items) + "</table>") if items else \
        "<p class='dim'>No downloads yet.</p>"
    body = f"""
<div class="row spread"><h2 style="margin:0">Downloads</h2></div>
{table}"""
    return page("Downloads", body, active="downloads")


# --------------------------------------------------------------------------- #
# Passwords
# --------------------------------------------------------------------------- #
def passwords_page(entries: List[Dict], report: Dict, locked: bool,
                   uses_master: bool, flash: str = "") -> str:
    """Saved passwords (masked) with reveal/copy/delete controls."""
    if locked:
        body = f"""
<div class="center" style="margin-top:70px">
  <div style="font-size:56px">🔐</div>
  <h2 style="margin:12px 0">Password vault is locked</h2>
  <p class="dim">Passwords are encrypted at rest. Unlock to view saved logins.</p>
  <a class="btn primary" href="browser://passwords?action=unlock" style="margin-top:16px">Unlock</a>
</div>"""
        return page("Passwords", body, active="passwords")
    weak_n, reused_n = len(report.get("weak", [])), len(report.get("reused", []))
    alerts = []
    if weak_n:
        alerts.append(f"<div class='notice warn small'>{weak_n} weak password(s) — consider replacing them.</div>")
    if reused_n:
        alerts.append(f"<div class='notice bad small'>Reused passwords detected across {reused_n} group(s) — reuse makes breaches cascade.</div>")
    rows = []
    for i, en in enumerate(entries):
        s = en.get("_strength", 0)
        badge = {0: ("bad", "very weak"), 1: ("bad", "weak"), 2: ("warn", "fair"),
                 3: ("ok", "strong"), 4: ("ok", "very strong")}.get(s, ("muted", "?"))
        rows.append(f"""
<tr>
  <td><b>{e(en['origin'])}</b><div class='muted small'>{e(en['username'])}</div></td>
  <td><span class='badge {badge[0]}'>{badge[1]}</span></td>
  <td class='row'>
    <a class='btn small' href='browser://passwords?action=reveal&id={i}'>Reveal</a>
    <a class='btn small' href='browser://passwords?action=copy&id={i}'>Copy</a>
    <a class='btn small danger' href='browser://passwords?action=delete&id={i}'>Delete</a>
  </td>
</tr>""")
    table = ("<table><tr><th>Login</th><th>Strength</th><th>Actions</th></tr>"
             + "".join(rows) + "</table>") if rows else \
        "<p class='dim'>No saved logins yet. browser offers to save passwords when you sign in.</p>"
    body = f"""
<div class="row spread"><h2 style="margin:0">Passwords <span class="badge">{len(entries)} saved</span></h2>
  <div class="row">
    <a class="btn small" href="browser://passwords?action=generate">Generate password</a>
    <a class="btn small" href="browser://passwords?action=export_csv">Export CSV…</a>
    <a class="btn small" href="browser://passwords?action=import_csv">Import CSV…</a>
  </div>
</div>
{'<div class="notice ok">' + e(flash) + "</div>" if flash else ""}
{"".join(alerts)}
<p class="muted small">Encrypted with PBKDF2 (600k rounds) + AES-256-GCM. {
  'Master password protection is <b>on</b>.' if uses_master else
  'Master password protection is <b>off</b> — enable it in Settings → Passwords.'}</p>
{table}"""
    return page("Passwords", body, active="passwords")


def password_revealed_page(origin: str, username: str, password: str) -> str:
    """Page shown after revealing a password (still gated by unlock)."""
    body = f"""
<h2>Revealed password</h2>
<div class="card">
  <p class="muted small">{e(origin)}</p>
  <p><b>{e(username)}</b></p>
  <p class="mono" style="font-size:16px; user-select:all">{e(password)}</p>
</div>
<div class="row">
  <a class="btn" href="browser://passwords">Back</a>
  <span class="muted small">Passwords are never sent to any server.</span>
</div>"""
    return page("Reveal", body, active="passwords")


def password_copied_page() -> str:
    """Confirmation page after copying a password to the clipboard."""
    body = """
<div class="notice ok">Password copied to the clipboard. The clipboard will be
cleared automatically in 60 seconds.</div>
<a class="btn" href="browser://passwords">Back to passwords</a>"""
    return page("Copied", body, active="passwords")


def password_generator_page(suggestion: str) -> str:
    """Password generator with policy controls and strength meter."""
    body = f"""
<h2>Generate a strong password</h2>
<div class="card">
  <p class="mono" style="font-size:18px; user-select:all">{e(suggestion)}</p>
  <p class="muted small">Generated locally from a secure random source. Nothing is stored unless you save it.</p>
</div>
<div class="row">
  <a class="btn" href="browser://passwords?action=generate">Generate another</a>
  <a class="btn primary" href="browser://passwords">Done</a>
</div>"""
    return page("Generator", body, active="passwords")


def vault_unlock_prompt_page() -> str:
    """Tells the user the vault is locked and how to unlock it."""
    body = """
<div class="notice warn">The unlock dialog has been opened. After unlocking,
return to the passwords page.</div>
<a class="btn" href="browser://passwords">Retry</a>"""
    return page("Vault locked", body, active="passwords")


# --------------------------------------------------------------------------- #
# Privacy dashboard
# --------------------------------------------------------------------------- #
def privacy_page(stats: Dict, policy_lines: List[Tuple[str, str]], sites,
                 level: str) -> str:
    """Privacy dashboard: counters, policy state, honest limitations."""
    trackers = stats.get("trackers", 0)
    cookies = stats.get("cookies", 0)
    ads = stats.get("ads", 0)
    requests = stats.get("requests", 0)
    level_badge = {"standard": "badge", "balanced": "badge ok", "strict": "badge ok"}.get(level, "badge")
    site_rows = "".join(
        f"<tr><td>{e(host)}</td><td><span class='badge'>{n} blocked</span></td>"
        f"<td><a class='btn small' href='browser://permissions?site={quote(host)}'>Permissions</a></td></tr>"
        for host, n in sites[:12])
    body = f"""
<h2>Privacy protection</h2>
<p class="dim">Protection level: <span class="{level_badge}">{e(level)}</span>
 — <a href="browser://settings#privacy">change</a></p>
<div class="grid cols3" style="margin:16px 0">
  <div class="stat"><div class="num">{trackers}</div><div class="lbl">Trackers blocked</div></div>
  <div class="stat"><div class="num">{cookies}</div><div class="lbl">Third-party cookies blocked</div></div>
  <div class="stat"><div class="num">{ads}</div><div class="lbl">Ads blocked <a class="small" href="browser://adblock">manage</a></div></div>
  <div class="stat"><div class="num">{requests}</div><div class="lbl">Suspicious requests blocked</div></div>
</div>
<p class="small muted">Counters reflect what was blocked on this device. Nothing
was uploaded to produce them.</p>
<div class="card">
  <h2 style="margin-top:0">Current protection</h2>
  <table>
    <tr><th>Setting</th><th>Status</th></tr>
    {''.join(f"<tr><td>{e(k)}</td><td><span class='badge {'ok' if v in ('on','enabled','strict','light') else ''}>{e(v)}</span></td></tr>" for k, v in policy_lines)}
  </table>
</div>
<div class="card">
  <h2 style="margin-top:0">Websites using trackers (this session)</h2>
  {('<table><tr><th>Site</th><th>Blocked</th><th></th></tr>' + site_rows + '</table>') if site_rows else '<p class="dim">No tracker activity seen yet.</p>'}
</div>
<div class="notice">
  <b>Honest limitation:</b> blocking lists reduce tracking, but no browser —
  including this one — makes you completely anonymous. Your IP address, ISP,
  and sophisticated fingerprinting can still identify you. Use a VPN/Tor for
  stronger anonymity.</div>"""
    return page("Privacy", body, active="privacy")



# --------------------------------------------------------------------------- #
# Ad-block dashboard (filter lists, uBlock Origin style)
# --------------------------------------------------------------------------- #
def adblock_page(enabled: bool, cosmetic: bool, stats: Dict,
                 list_rows: List[Dict], paused: List[str],
                 current_site: str = "") -> str:
    """Ad-block dashboard: stats, toggles, lists, per-site pauses."""
    ads = stats.get("ads", 0)
    trackers = stats.get("trackers", 0)
    total_rules = sum(int(r.get("rules", 0) or 0) for r in list_rows
                      if r.get("enabled") and not r.get("not_installed"))
    master = ("on" if enabled else "off")
    rows = []
    for r in list_rows:
        rid = e(r["id"])
        name = e(r.get("name", rid))
        status = []
        if r.get("builtin"):
            status.append("bundled offline")
        if r.get("not_installed"):
            status.append("not downloaded yet")
        else:
            if r.get("rules"):
                status.append(f"{r['rules']} rules")
            if r.get("last_updated"):
                status.append("updated " + r["last_updated"])
        status_txt = " · ".join(status) or "empty"
        if r.get("builtin"):
            enable_link = ("<span class='badge ok'>active</span>"
                           if r.get("enabled") else "")
        else:
            enable_link = (f"<a class='btn small' href='browser://adblock?action=toggle_list&amp;id={rid}&amp;value={'off' if r.get('enabled') else 'on'}'>"
                           + ("Disable" if r.get("enabled") else "Enable") + "</a>")
        update_link = (f"<a class='btn small' href='browser://adblock?action=update&amp;id={rid}'>Update</a>"
                       if r.get("url") else "")
        remove_link = (f"<a class='btn small danger' href='browser://adblock?action=remove_list&amp;id={rid}&amp;confirm=1'>Remove</a>"
                       if r.get("custom") else "")
        rows.append(
            f"<tr><td><b>{name}</b><br><span class='small muted'>{e(r.get('url',''))}</span></td>"
            f"<td class='small muted'>{e(status_txt)}</td>"
            f"<td style='white-space:nowrap'>{enable_link} {update_link} {remove_link}</td></tr>")
    paused_rows = "".join(
        f"<tr><td>{e(site)}</td><td><a class='btn small' href='browser://adblock?action=resume_site&amp;site={quote(site)}'>Resume blocking</a></td></tr>"
        for site in paused) or ""
    quick = ""
    if current_site:
        quick = f"""
  <a class="btn" href="browser://adblock?action=pause_site&amp;site={quote(current_site)}">
    Pause ad blocking on <b>{e(current_site)}</b></a>"""
    body = f"""
<h2>Ad blocking</h2>
<p class="dim">Filter-list based ad and tracker blocking, like uBlock Origin —
built in, no extension needed.</p>
<div class="grid cols3" style="margin:16px 0">
  <div class="stat"><div class="num">{ads}</div><div class="lbl">Ads &amp; ad trackers blocked (session)</div></div>
  <div class="stat"><div class="num">{trackers}</div><div class="lbl">Trackers blocked (session)</div></div>
  <div class="stat"><div class="num">{total_rules}</div><div class="lbl">Active filter rules</div></div>
</div>
<div class="card">
  <h2 style="margin-top:0">Status</h2>
  <table>
    <tr><th>Blocking</th><th>State</th><th></th></tr>
    <tr><td>Ad &amp; tracker blocking</td><td><span class="badge {'ok' if enabled else ''}">{master}</span></td>
        <td><a class="btn small" href="browser://adblock?action=master&amp;value={'off' if enabled else 'on'}">Turn {'off' if enabled else 'on'}</a></td></tr>
    <tr><td>Element hiding (cosmetic filters)</td><td><span class="badge {'ok' if cosmetic else ''}">{'on' if cosmetic else 'off'}</span></td>
        <td><a class="btn small" href="browser://adblock?action=cosmetic&amp;value={'off' if cosmetic else 'on'}">Turn {'off' if cosmetic else 'on'}</a></td></tr>
  </table>{quick}
</div>
<div class="card">
  <h2 style="margin-top:0">Filter lists</h2>
  <table>
    <tr><th>List</th><th>Status</th><th></th></tr>
    {''.join(rows)}
  </table>
  <form method="get" action="browser://adblock" class="row" style="margin-top:12px">
    <input type="hidden" name="action" value="add_list">
    <input type="text" name="name" placeholder="List name" style="max-width:220px" required>
    <input type="url" name="url" placeholder="Filter list URL (https://…/list.txt)" required>
    <button class="btn primary" type="submit">Add list</button>
  </form>
  <p class="small muted">Subscriptions are fetched over HTTPS, directly from the
  list publisher, only when you enable or update them. browser never proxies
  list traffic and never sends your browsing history anywhere.</p>
</div>
<div class="card">
  <h2 style="margin-top:0">Sites where blocking is paused</h2>
  {('<table><tr><th>Site</th><th></th></tr>' + paused_rows + '</table>') if paused_rows else '<p class="dim">Blocking is active everywhere.</p>'}
</div>
<div class="notice">
  <b>What this covers:</b> network requests matching filter-list rules and
  hidden ad elements. It does <b>not</b> replace HTTPS, tracker-cookie
  blocking, or fingerprinting protection — those stay active in
  <a href="browser://privacy">Privacy</a>. Procedural cosmetic filters and
  script-injection tricks used by full uBlock Origin are not supported
  (see <a href="browser://about">About</a>).</div>"""
    return page("Ad block", body, active="adblock")

# --------------------------------------------------------------------------- #
# Security dashboard
# --------------------------------------------------------------------------- #
def security_page(current_url: str, https: bool, cert_info: str,
                 downloads_alerts: List[str], settings_lines: List[Tuple[str, str]],
                 threat_note: str) -> str:
    """Security dashboard: connection state, cert, download alerts."""
    conn_badge = "ok" if https else "bad"
    conn_text = "HTTPS (encrypted)" if https else "not encrypted"
    scheme_note = "" if current_url.startswith(("http", "https")) else \
        "<p class='muted small'>The current tab is not a website (internal page or other scheme).</p>"
    dl_rows = "".join(f"<li>{e(x)}</li>" for x in downloads_alerts) or "<li class='muted'>No download warnings.</li>"
    body = f"""
<h2>Security status</h2>
<div class="grid cols2" style="margin:14px 0">
  <div class="stat"><div class="num" style="color:var(--{'ok' if https else 'danger'})">{'✓' if https else '!'}</div>
    <div class="lbl">Connection</div>
    <div class="small muted">{e(current_url[:60])}<br><span class="badge {conn_badge}">{conn_text}</span></div></div>
  <div class="stat"><div class="num" style="font-size:18px; color:var(--fg)">{e(cert_info) if cert_info else '—'}</div>
    <div class="lbl">Certificate</div></div>
</div>
{scheme_note}
<div class="card">
  <h2 style="margin-top:0">Download security</h2>
  <ul class="bm" style="padding-left:16px">{dl_rows}</ul>
  <p class="muted small">browser never executes downloads automatically and warns
  about executable files before saving them.</p>
</div>
<div class="card">
  <h2 style="margin-top:0">Protection settings</h2>
  <table>
    <tr><th>Setting</th><th>Value</th></tr>
    {''.join(f"<tr><td>{e(k)}</td><td><span class='badge {'ok' if v in ('on','enabled') else ''}>{e(v)}</span></td></tr>" for k, v in settings_lines)}
  </table>
</div>
<div class="notice">{e(threat_note)}</div>
<p class="small muted">Certificate validation is performed by the underlying
Chromium TLS stack. browser never bypasses certificate errors.</p>"""
    return page("Security", body, active="security")


# --------------------------------------------------------------------------- #
# Extensions
# --------------------------------------------------------------------------- #
def extensions_page(exts, enabled: dict, private_ok: list,
                    current_site: str = "", site_prefs: dict = None) -> str:
    """User-script extension manager (enable/private/remove/install)."""
    site_prefs = site_prefs or {}
    rows = []
    for ext in exts:
        eid = e(ext.id)
        on = enabled.get(ext.id, True)
        perms = " ".join(f"<span class='badge'>{e(p)}</span>" for p in ext.permissions)
        priv = ("✓ allowed in private windows" if ext.id in private_ok
                else "not allowed in private windows")
        builtin_badge = " <span class='badge ok'>built-in</span>" if ext.builtin else ""
        behavior = "runs everywhere" if ext.default_on else "per-site opt-in"
        site_ui = ""
        if current_site:
            pref = site_prefs.get(ext.id, {}).get(current_site)
            if ext.default_on:
                label = ("off" if pref is False else "on")
            else:
                label = ("on" if pref is True else "off")
            site_ui = (f"<a class='btn small' "
                       f"href='browser://extensions?action=site_toggle&amp;id={eid}'>"
                       f"{label} on {e(current_site)} — switch</a>")
        overrides = site_prefs.get(ext.id, {})
        ov_rows = "".join(
            f"<span class='badge'>{e(host)}: {'on' if v else 'off'} "
            f"<a href='browser://extensions?action=site_reset&amp;id={eid}&amp;host={quote(host)}'>reset</a></span> "
            for host, v in sorted(overrides.items()))
        remove_btn = ("" if ext.builtin else
                      f"<a class='btn small danger' href='browser://extensions?action=remove&id={eid}&confirm=1'>Remove</a>")
        rows.append(f"""
<tr>
  <td><b>{e(ext.name)}</b>{builtin_badge} <span class="badge">v{e(ext.version)}</span>
    <span class="badge">{e(behavior)}</span>
    <div class="muted small">{e(ext.description)}</div>
    <div style="margin-top:4px">{perms}</div>
    <div class="muted small">{e(priv)}</div>
    <div style="margin-top:6px">{ov_rows}</div></td>
  <td><span class="badge {'ok' if on else ''}">{'enabled' if on else 'disabled'}</span></td>
  <td class="row">
    <a class="btn small" href="browser://extensions?action=toggle&id={eid}">{'Disable' if on else 'Enable'}</a>
    <a class="btn small" href="browser://extensions?action=toggle_private&id={eid}">{'Revoke private' if ext.id in private_ok else 'Allow private'}</a>
    {site_ui}<br>{remove_btn}
  </td>
</tr>""")
    table = ("<table><tr><th>Extension</th><th>State</th><th>Actions</th></tr>"
             + "".join(rows) + "</table>") if rows else         "<p class='dim'>No extensions installed. Extensions are folders with a manifest.json — see the docs.</p>"
    body = f"""
<div class="row spread"><h2 style="margin:0">Extensions</h2>
  <a class="btn small" href="browser://extensions?action=install">Install from folder…</a>
</div>
<div class="notice small">browser supports <b>user-script extensions</b> (JavaScript
injected into matching pages). It does <b>not</b> run Chrome or Firefox extensions —
the engine provides no WebExtension APIs. Built-in extensions are bundled with the
app and can be disabled per site or globally, but not removed.</div>
{table}"""
    return page("Extensions", body, active="extensions")


# --------------------------------------------------------------------------- #
# Permissions
# --------------------------------------------------------------------------- #
def permissions_page(global_defaults: Dict[str, str], sites: Dict[str, Dict[str, str]],
                     feature_labels: Dict[str, str], selected_site: str = "") -> str:
    """Site-permission manager: global defaults and per-site overrides."""
    rows = []
    for f, label in feature_labels.items():
        action = global_defaults.get(f, "ask")
        opts = "".join(
            f"<a class='btn small {'primary' if action == a else ''}' "
            f"href='browser://permissions?action=global&feature={e(f)}&value={a}'>{a}</a>"
            for a in ("allow", "ask", "block"))
        rows.append(f"<tr><td>{e(label)}</td><td class='row'>{opts}</td></tr>")
    site_rows = []
    for origin, feats in sorted(sites.items()):
        for f, a in feats.items():
            label = feature_labels.get(f, f)
            site_rows.append(
                f"<tr><td>{e(origin)}</td><td>{e(label)}</td>"
                f"<td><span class='badge {'ok' if a == 'allow' else 'bad' if a == 'block' else ''}'>{e(a)}</span></td>"
                f"<td><a class='btn small danger' href='browser://permissions?action=reset_site&site={quote(origin)}'>Reset</a></td></tr>")
    selected = (f"<p class='muted small'>Showing overrides for <b>{e(selected_site)}</b> — "
                f"<a href='browser://permissions'>show all</a></p>") if selected_site else ""
    body = f"""
<h2>Website permissions</h2>
<p class="muted small">Global defaults. Sensitive permissions (camera, microphone,
location, screen) can never be globally allowed — you decide per site, every time.</p>
<div class="card"><table>
<tr><th>Feature</th><th>Default</th></tr>{''.join(rows)}
</table></div>
<h2>Per-site overrides</h2>
{selected}
{('<table><tr><th>Site</th><th>Feature</th><th>Rule</th><th></th></tr>' + ''.join(site_rows) + '</table>') if site_rows else "<p class='dim'>No per-site rules yet.</p>"}"""
    return page("Permissions", body, active="settings")


# --------------------------------------------------------------------------- #
# About
# --------------------------------------------------------------------------- #
def about_page(version: str, engine_version: str, data_dir: str) -> str:
    """About page: version, engine, data directory, philosophy."""
    body = f"""
<div class="center" style="margin-top:50px">
  <div class="logo" style="font-size:44px; font-weight:800; letter-spacing:5px">
    browser<span style="color:var(--accent)">.</span></div>
  <p class="dim">The privacy-first web browser</p>
  <p><span class="badge">version {e(version)}</span>
     <span class="badge">engine: Chromium via QtWebEngine {e(engine_version)}</span></p>
</div>
<div class="card" style="margin-top:30px">
  <h2 style="margin-top:0">Privacy commitment</h2>
  <ul class="bm" style="padding-left:16px">
    <li>All data stays on this device. No accounts, no sync, no telemetry.</li>
    <li>No trackers, no ads, no data selling — ever.</li>
    <li>Optional update checks happen only against a feed you configure and approve.</li>
    <li>Data folder: <span class="mono small">{e(data_dir)}</span></li>
  </ul>
</div>
<div class="row" style="justify-content:center">
  <a class="btn" href="browser://settings#about">Settings</a>
  <a class="btn" href="browser://privacy">Privacy dashboard</a>
</div>"""
    return page("About", body)


# --------------------------------------------------------------------------- #
# Generic info / message page
# --------------------------------------------------------------------------- #
def message_page(title: str, text: str, back_href: str = "browser://home",
                 back_label: str = "Go home") -> str:
    """Small informational page with a back link."""
    body = f"""<div class="card" style="margin-top:40px">
<h2 style="margin-top:0">{e(title)}</h2><p>{e(text)}</p>
<p style="margin-top:14px"><a class="btn primary" href="{e(back_href)}">{e(back_label)}</a></p>
</div>"""
    return page(title, body)
