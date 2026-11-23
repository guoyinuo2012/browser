"""Share helpers: Google Lens search, email share, QR plumbing.

Pure URL builders — no network calls. Used by the main menu ("Search this
tab with Google Lens", "Save, share and cast") and the page context menu
("Search image with Google Lens").
"""

from __future__ import annotations

from urllib.parse import quote


def lens_image_url(image_url: str) -> str:
    """Google Lens lookup for an image that is already on the web."""
    if not image_url:
        return "https://lens.google.com/"
    return "https://lens.google.com/uploadbyurl?url=" + quote(image_url,
                                                            safe="")


def lens_page_url() -> str:
    """The Lens upload page (for tabs with no usable image)."""
    return "https://lens.google.com/"


def email_share_url(url: str, title: str = "") -> str:
    """mailto: link that shares a page."""
    body = url
    subject = title or url
    return (f"mailto:?subject={quote(subject, safe='')}"
            f"&body={quote(body, safe='')}")


def copyable_link(url: str, title: str = "") -> str:
    """Title + URL text suitable for 'Copy page link'."""
    return f"{title}\n{url}" if title else url


LENS_IMAGE_JS = (
    "(function(){var m=document.querySelector('meta[property=\"og:image\"]');"
    "if(m&&m.content&&/^https?:/i.test(m.content))return m.content;"
    "var imgs=document.querySelectorAll('img[src]');"
    "for(var i=0;i<imgs.length;i++){var s=imgs[i].src;"
    "if(/^https?:\\/\\//i.test(s)&&s.indexOf('data:')!==0)return s;}"
    "return '';})()"
)
