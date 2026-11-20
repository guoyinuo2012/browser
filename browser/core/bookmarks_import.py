"""Netscape-format bookmark HTML import/export (compatible with all
major browsers) using only the standard library."""

from __future__ import annotations

import time
from html.parser import HTMLParser
from typing import List, Tuple


class _BookmarkParser(HTMLParser):
    """Extracts folders + links from Netscape bookmark HTML."""

    def __init__(self):
        super().__init__()
        self.stack: List[str] = []       # folder path names
        self.items: List[Tuple[List[str], str, str]] = []  # (folders, title, url)
        self._in_a = False
        self._a_href = ""
        self._a_text: List[str] = []
        self._folder_stack: List[str] = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "h3":
            pass
        if tag == "a" and a.get("href"):
            self._in_a = True
            self._a_href = a["href"]
            self._a_text = []
        elif tag == "dl":
            # entering a folder's content list — folder titles come from h3
            pass
        elif tag == "h3":
            self._in_h3 = True
            self._h3_text: List[str] = []

    def handle_endtag(self, tag):
        if tag == "a" and self._in_a:
            title = "".join(self._a_text).strip() or self._a_href
            self.items.append((list(self._folder_stack), title, self._a_href))
            self._in_a = False
        elif tag == "h3" and getattr(self, "_in_h3", False):
            self._folder_stack.append("".join(self._h3_text).strip())
            self._in_h3 = False

    def handle_data(self, data):
        if self._in_a:
            self._a_text.append(data)
        if getattr(self, "_in_h3", False):
            self._h3_text.append(data)


def export_bookmarks_html(store, path: str) -> int:
    """Serialize the bookmark tree to Netscape HTML; returns items written."""
    count = 0
    lines = [
        "<!DOCTYPE NETSCAPE-Bookmark-file-1>",
        '<META HTTP-EQUIV="Content-Type" CONTENT="text/html; charset=UTF-8">',
        f"<TITLE>Bookmarks</TITLE>",
        "<H1>Bookmarks</H1>",
        "<DL><p>",
    ]
    folders: dict[str, list] = {}
    order: list = []

    def walk(parent_id, path_names):
        nonlocal count
        for row in store.children(parent_id):
            if row["is_folder"]:
                walk(row["id"], path_names + [row["title"]])
            else:
                folders.setdefault(" / ".join(path_names), []).append(row)
                if path_names not in order:
                    order.append(" / ".join(path_names))
                count += 1

    walk(None, [])
    for key in order:
        depth = key.count(" / ") + 1 if key else 0
        if key:
            name = key.split(" / ")[-1]
            lines.append("    " * depth + f"<DT><H3>{_esc(name)}</H3>")
            lines.append("    " * depth + "<DL><p>")
        for row in folders.get(key, []):
            add = time.strftime("%Y%m%d", time.gmtime(row["added_time"]))
            lines.append("    " * (depth + 1) +
                         f'<DT><A HREF="{_esc(row["url"])}" ADD_DATE="{add}">'
                         f'{_esc(row["title"])}</A>')
        if key:
            lines.append("    " * depth + "</DL><p>")
    lines.append("</DL><p>")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    return count


def _esc(s: str) -> str:
    return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace('"', "&quot;")


def import_bookmarks_html(store, path: str) -> int:
    """Merge a Netscape bookmarks file into the store; returns items added."""
    with open(path, encoding="utf-8", errors="replace") as f:
        text = f.read()
    parser = _BookmarkParser()
    parser.feed(text)
    parser.close()

    folder_ids: dict[str, str] = {}

    def ensure_folder(path_names) -> str | None:
        if not path_names:
            return None
        key = " / ".join(path_names)
        if key in folder_ids:
            return folder_ids[key]
        parent = ensure_folder(path_names[:-1])
        fid = store.add_folder(path_names[-1], parent)
        folder_ids[key] = fid
        return fid

    n = 0
    seen = set()
    for path_names, title, url in parser.items:
        if not url or url in seen:
            continue
        seen.add(url)
        if store.duplicate_url_exists(url):
            continue
        store.add_bookmark(title, url, ensure_folder(path_names))
        n += 1
    return n
