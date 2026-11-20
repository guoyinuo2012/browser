"""WebTab — one browsing context for browser.

Responsibilities:
  * custom QWebEnginePage: navigation policy (HTTPS-first, safe browsing,
    browser:// handling), certificate errors (never bypassed), permission
    requests, popup policy, fullscreen, render-crash recovery
  * privacy script injection (fingerprinting mitigation, WebRTC policy)
  * extension user-script injection
  * password autofill + save-password prompts
  * reader mode, find, zoom persistence, devtools attachment

Private tabs use an off-the-record profile: no history, no cookies on disk,
no cache, no saved passwords.
"""

from __future__ import annotations

from urllib.parse import quote_plus

from PyQt6.QtCore import QUrl, pyqtSignal
from PyQt6.QtWidgets import QWidget, QVBoxLayout
from PyQt6.QtWebEngineCore import (
    QWebEnginePage, QWebEngineProfile, QWebEngineDownloadRequest)
from PyQt6.QtWebEngineWidgets import QWebEngineView

from ..constants import SCHEME_STR
from ..core.privacy import fingerprint_script, webrtc_script
from ..core.security import HTTPSFirstUpgrader


class BrowserPage(QWebEnginePage):
    """Page with browser's navigation + security policy."""

    def __init__(self, profile: QWebEngineProfile, tab: "WebTab", parent=None):
        super().__init__(profile, parent)
        self.tab = tab

    def acceptNavigationRequest(self, url: QUrl, type_, is_main_frame: bool) -> bool:
        s = url.toString()
        # Internal pages always allowed.
        if url.scheme() == SCHEME_STR:
            return True
        # Safe Browsing (local lists only)
        sb = self.tab.services.safe_browsing
        if sb is not None and is_main_frame and type_ != QWebEnginePage.NavigationType.NavigationTypeReload:
            reason = sb.check(s)
            if reason:
                self.tab.show_internal("blocked", url=url,
                                       reason=quote_plus(reason), kind="threat")
                return False
        # HTTPS-First for main-frame typed/link navigations
        if (is_main_frame and self.tab.https_first
                and type_ in (QWebEnginePage.NavigationType.NavigationTypeTyped,
                              QWebEnginePage.NavigationType.NavigationTypeLinkClicked)):
            upgraded = self.tab.upgrader.upgrade(s)
            if upgraded != s:
                url = QUrl(upgraded)
        return super().acceptNavigationRequest(url, type_, is_main_frame)


class WebTab(QWidget):
    """One tab: view + page + chrome state (pinned/group/muted)."""

    title_changed = pyqtSignal(str)
    url_changed = pyqtSignal(QUrl)
    icon_changed = pyqtSignal()
    load_started = pyqtSignal()
    load_progress = pyqtSignal(int)
    load_finished = pyqtSignal(bool)
    open_new_tab = pyqtSignal(str, bool)          # url, background
    open_new_window = pyqtSignal(str, bool)       # url, private
    status_message = pyqtSignal(str)
    blocked_count_changed = pyqtSignal()
    popup_blocked = pyqtSignal(str)
    save_password_prompt = pyqtSignal(str, str, str)   # origin, username, password
    permission_prompt = pyqtSignal(object, str, object)  # origin, feature, responder
    close_requested = pyqtSignal()
    fullscreen_requested = pyqtSignal(bool)
    devtools_requested = pyqtSignal(object)       # self

    def __init__(self, profile: QWebEngineProfile, services, window, parent=None):
        super().__init__(parent)
        self.profile = profile
        self.services = services
        self.window = window
        self.settings = services.settings
        self.store = services.store
        self.vault = services.vault
        self.is_private = profile.isOffTheRecord()

        self.pinned = False
        self.group_name: str = ""
        self.muted = False
        self.zoom_host = ""

        self.https_first = bool(self.settings.get("security.https_first"))
        self.upgrader = HTTPSFirstUpgrader(enabled=self.https_first)
        self.safe_browsing = services.safe_browsing
        self._cert_error_detail = ""

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.view = QWebEngineView(self)
        layout.addWidget(self.view)
        self.setLayout(layout)

        self.page = BrowserPage(profile, self, self.view)
        self.view.setPage(self.page)

        self._connect_page()

    # ------------------------------------------------------------------ #
    def _connect_page(self) -> None:
        p = self.page
        p.titleChanged.connect(self._on_title)
        p.urlChanged.connect(self._on_url)
        p.iconChanged.connect(self.icon_changed)
        p.loadStarted.connect(lambda: (self.load_started.emit(),
                                       self.status_message.emit("")))
        p.loadProgress.connect(self.load_progress)
        p.loadFinished.connect(self._on_load_finished)
        p.linkHovered.connect(self.status_message)
        p.featurePermissionRequested.connect(self._on_permission)
        p.certificateError.connect(self._on_certificate_error)
        p.fullScreenRequested.connect(self._on_fullscreen)
        p.newWindowRequested.connect(self._on_new_window)
        p.windowCloseRequested.connect(self.close_requested)
        p.renderProcessTerminated.connect(self._on_render_crash)
        p.printRequested.connect(lambda: self.print_page())

    # -- navigation ---------------------------------------------------------
    def load_url(self, url: str) -> None:
        u = url.strip()
        if not u:
            return
        self._cert_error_detail = ""
        self.page.load(QUrl(u))

    def reload(self) -> None:
        self.page.triggerAction(QWebEnginePage.WebAction.Reload)

    def stop(self) -> None:
        self.page.triggerAction(QWebEnginePage.WebAction.Stop)

    def back(self) -> None:
        self.page.triggerAction(QWebEnginePage.WebAction.Back)

    def forward(self) -> None:
        self.page.triggerAction(QWebEnginePage.WebAction.Forward)

    def home(self) -> None:
        from ..constants import URL_HOME
        self.load_url(URL_HOME)

    @property
    def url_string(self) -> str:
        return self.page.url().toString()

    def show_internal(self, host: str, **params) -> None:
        from urllib.parse import urlencode
        qs = urlencode(params)
        self.page.load(QUrl(f"{SCHEME_STR}://{host}" + (f"?{qs}" if qs else "")))

    # -- title / url ----------------------------------------------------------
    def _on_title(self, title: str) -> None:
        if not title:
            host = self.page.url().host() if self.page.url().isValid() else ""
            title = host or "New tab"
        self.title_changed.emit(title)

    def _on_url(self, url: QUrl) -> None:
        self.url_changed.emit(url)
        host = url.host()
        if host and host != self.zoom_host:
            self.zoom_host = host
            saved = self.settings.get("internal.zoom_by_host", {})
            factor = float(saved.get(host, self.settings.get("a11y.page_zoom_default", 1.0)))
            self.page.setZoomFactor(factor)
        if self.is_private:
            return
        self._record_history(url)

    def _record_history(self, url: QUrl) -> None:
        s = url.toString()
        if not self.settings.get("history.enabled", True):
            return
        if url.scheme() in ("http", "https"):
            self.store.add_history(s, self.page.title() or s)

    # -- load lifecycle --------------------------------------------------------
    def _on_load_finished(self, ok: bool) -> None:
        self.load_finished.emit(ok)
        if ok:
            self._inject_runtime_scripts()
            self._inject_cosmetic_css()
            self._check_for_login_form()

    def _inject_cosmetic_css(self) -> None:
        """Element hiding from filter lists (uBO-Lite style, post-load)."""
        ab = getattr(self.services, "adblock", None)
        if ab is None or not self.settings.get("adblock.cosmetic", True):
            return
        if not self.settings.get("adblock.enabled", True):
            return
        url = self.page.url()
        if url.scheme() not in ("http", "https"):
            return
        host = url.host().lower()
        if ab.is_paused(host):
            return
        css = ab.engine.css_for(host)
        if not css:
            return
        safe = (css.replace("\\", "\\\\").replace("`", "\\`")
                .replace("${", "\\${"))
        js = ("(function(){var s=document.createElement('style');"
              f"s.id='browser-adblock-css';s.textContent=`{safe}`;"
              "(document.head||document.documentElement).appendChild(s);})()")
        self.page.runJavaScript(js)

    def _inject_runtime_scripts(self) -> None:
        pol = self.services.privacy_policy
        scripts = []
        fp = fingerprint_script(pol.fingerprinting)
        if fp:
            scripts.append(fp)
        wr = webrtc_script(self.settings.get("privacy.webrtc_policy", "default"))
        if wr:
            scripts.append(wr)
        # extension user scripts
        exts = self.services.extensions
        if exts is not None and self.page.url().scheme() in ("http", "https"):
            u = self.page.url()
            for _ext, js in exts.scripts_for(u.toString(), self.is_private,
                                             host=u.host()):
                scripts.append(js)
        if scripts:
            combined = "\n;\n".join(scripts)
            self.page.runJavaScript(combined)

    # -- passwords ---------------------------------------------------------------
    AUTOFILL_JS = """
(function () {
  function findForm() {
    var pwds = document.querySelectorAll('input[type=password]');
    for (var i = 0; i < pwds.length; i++) {
      var f = pwds[i].form;
      if (f) {
        var user = f.querySelector('input[type=text], input[type=email], input[name*=user i], input[name*=email i], input[name*=login i], input[name*=account i], input[id*=user i], input[id*=email i], input[id*=login i]');
        return {pwd: pwds[i], user: user};
      }
    }
    return null;
  }
  window.__browserLogin = findForm();
  return window.__browserLogin ? {
    has: true,
    user: window.__browserLogin.user ? window.__browserLogin.user.value : '',
    pwdFilled: false
  } : {has: false};
})();
"""

    def _check_for_login_form(self) -> None:
        u = self.page.url()
        if u.scheme() not in ("http", "https"):
            return
        if not self.settings.get("passwords.autofill", True):
            return
        if not self.vault.is_initialized() or not self.vault.is_unlocked():
            return
        origin = u.host()

        def apply(result):
            if not result or not result.get("has"):
                return
            match = self.vault.find(origin)
            if not match:
                return
            import json as _json
            username = _json.dumps(match["username"])
            password = _json.dumps(match["password"])
            js = f"""
(function () {{
  var info = window.__browserLogin; if (!info || !info.pwd) return;
  if (info.user && !info.user.value) {{
    info.user.value = {username};
  }}
  info.pwd.value = {password};
  return true;
}})();"""
            self.page.runJavaScript(js, lambda r: self.status_message.emit(
                f"Filled saved login for {origin}") if r else None)

        self.page.runJavaScript(self.AUTOFILL_JS, apply)

    def offer_save_password(self, username: str, password: str) -> None:
        origin = self.page.url().host()
        self.save_password_prompt.emit(origin, username, password)

    # -- permissions ---------------------------------------------------------
    def _on_permission(self, origin: QUrl, feature) -> None:
        origin_str = origin.host()
        if not origin_str:
            return
        pm = self.services.permissions

        def respond(allow: bool, remember: bool) -> None:
            self.page.setFeaturePermission(
                origin, feature,
                QWebEnginePage.PermissionPolicy.PermissionGrantedByUser if allow
                else QWebEnginePage.PermissionPolicy.PermissionDeniedByUser)
            if remember:
                pm.set_site_rule(origin_str, _feature_name(feature),
                                 "allow" if allow else "block")

        decision = pm.decide(origin_str, _feature_name(feature))
        if decision == "allow":
            self.page.setFeaturePermission(origin, feature,
                                           QWebEnginePage.PermissionPolicy.PermissionGrantedByUser)
        elif decision == "block":
            self.page.setFeaturePermission(origin, feature,
                                           QWebEnginePage.PermissionPolicy.PermissionDeniedByUser)
        else:
            self.permission_prompt.emit(origin_str, _feature_name(feature), respond)

    # -- certificate errors ------------------------------------------------------
    def _on_certificate_error(self, error) -> None:
        # SECURITY POLICY: certificate errors are never bypassed automatically.
        # We always reject and show a warning page with the reason.
        detail = error.description()
        url = error.url().toString()
        error.rejectCertificate()
        if not error.isMainFrame():
            return
        if self.https_first:
            self.upgrader.record_failure(url)
        self._cert_error_detail = detail
        self.show_internal("certerror", url=url, detail=detail)

    # -- fullscreen -----------------------------------------------------------
    def _on_fullscreen(self, request) -> None:
        request.accept()
        self.fullscreen_requested.emit(request.toggleOn())

    # -- popups ---------------------------------------------------------------
    def _on_new_window(self, request: QWebEngineNewWindowRequest) -> None:
        url = request.requestedUrl().toString()
        user_initiated = request.isUserInitiated()
        # Popup blocking: unrequested popups are dropped by not attaching a
        # page to the request (Chromium then cancels the navigation).
        allow_popups = not self.settings.get("privacy.block_popups", True)
        if not (allow_popups or user_initiated):
            self.popup_blocked.emit(url)
            return
        # Handled synchronously by the window: creates the tab/window and
        # calls request.openIn(new_page) before returning.
        self.window.handle_new_window(self, request)

    def _on_render_crash(self, status, code) -> None:
        self.show_internal(
            "error", url=self.page.url().toString(),
            title="This tab crashed",
            desc=("The site's renderer stopped working. browser keeps other "
                  "tabs isolated, so they are unaffected. Reload to try again."))

    # -- devtools ---------------------------------------------------------------
    def attach_devtools(self) -> None:
        self.devtools_requested.emit(self)

    # -- productivity -------------------------------------------------------------
    def find(self, text: str, backward: bool = False, case_sensitive: bool = False,
             callback=None) -> None:
        flags = QWebEnginePage.FindFlag(0)
        if backward:
            flags |= QWebEnginePage.FindFlag.FindBackward
        if case_sensitive:
            flags |= QWebEnginePage.FindFlag.FindCaseSensitively
        self.page.findText(text, flags, callback or (lambda r: None))

    def find_clear(self) -> None:
        self.page.findText("")

    def set_zoom(self, factor: float) -> None:
        factor = max(0.3, min(5.0, factor))
        self.page.setZoomFactor(factor)
        if self.zoom_host:
            saved = dict(self.settings.get("internal.zoom_by_host", {}))
            saved[self.zoom_host] = factor
            self.settings.set("internal.zoom_by_host", saved)

    def zoom_in(self) -> None:
        self.set_zoom(self.page.zoomFactor() + 0.1)

    def zoom_out(self) -> None:
        self.set_zoom(self.page.zoomFactor() - 0.1)

    def zoom_reset(self) -> None:
        self.set_zoom(self.settings.get("a11y.page_zoom_default", 1.0))

    def print_page(self) -> None:
        """Native print handled by the window via printToPdf."""
        pass

    def print_to_pdf(self, dest: str, callback=None) -> None:
        if callback is None:
            self.page.printToPdf(dest)
        else:
            self.page.printToPdf(callback, dest)

    def save_page(self, path: str, complete: bool = True) -> None:
        fmt = (QWebEngineDownloadRequest.SavePageFormat.CompleteHtmlSaveFormat
               if complete else QWebEngineDownloadRequest.SavePageFormat.SingleHtmlSaveFormat)
        self.page.save(path, fmt)

    def screenshot(self, path: str) -> bool:
        img = self.view.grab()
        ok = img.save(path, "PNG")
        return ok

    READER_JS = """
(function () {
  function pick() {
    var best = null, bestScore = 0;
    var candidates = document.querySelectorAll('article, main, [role=main], .post, .article, #content, .content');
    candidates.forEach(function (el) {
      var ps = el.querySelectorAll('p');
      var score = 0;
      ps.forEach(function (p) { score += (p.textContent || '').length; });
      if (score > bestScore) { bestScore = score; best = el; }
    });
    if (!best || bestScore < 500) {
      best = document.body;
    }
    var out = [];
    var ps = best.querySelectorAll('h1,h2,h3,p,li,blockquote,pre,img');
    var seen = {};
    ps.forEach(function (el) {
      var tag = el.tagName.toLowerCase();
      if (tag === 'img') {
        var src = el.currentSrc || el.src;
        if (src) out.push('<img src="' + src + '">');
        return;
      }
      var text = (el.textContent || '').replace(/\\s+/g, ' ').trim();
      if (!text || seen[text]) return;
      seen[text] = 1;
      if (tag === 'p' && text.length < 40) return;
      var esc = text.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
      if (tag === 'h1') out.push('<h1>' + esc + '</h1>');
      else if (tag === 'h2') out.push('<h2>' + esc + '</h2>');
      else if (tag === 'h3') out.push('<h3>' + esc + '</h3>');
      else if (tag === 'blockquote') out.push('<blockquote>' + esc + '</blockquote>');
      else if (tag === 'pre') out.push('<pre>' + esc + '</pre>');
      else if (tag === 'li') out.push('<li>' + esc + '</li>');
      else out.push('<p>' + esc + '</p>');
    });
    return {title: document.title, html: out.join('\\n')};
  }
  return pick();
})();
"""

    def enter_reader_mode(self, dark: bool) -> None:
        def build(result):
            if not result or not result.get("html"):
                self.status_message.emit("Reader mode found no readable content here.")
                return
            theme_css = ("""body{background:#121417;color:#e8eaf0}"""
                         if dark else """body{background:#fbfaf7;color:#20232a}""")
            html = f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<title>Reader — {result.get('title','')}</title>
<style>
body {{ font-family: Georgia, 'Times New Roman', serif; margin: 0 auto; padding: 40px 20px;
  max-width: 680px; font-size: 19px; line-height: 1.7; {theme_css} }}
img {{ max-width: 100%; border-radius: 8px; }}
h1,h2,h3 {{ line-height: 1.3; }}
blockquote {{ border-left: 3px solid #8888; padding-left: 14px; color: #999;
  font-style: italic; }}
pre {{ background: #88888818; padding: 12px; border-radius: 8px; overflow: auto; }}
a {{ color: inherit; }}
</style></head><body>
{result['html']}
</body></html>"""
            self.page.setHtml(html, self.page.url())
        self.page.runJavaScript(self.READER_JS, build)

    # -- muted ----------------------------------------------------------------
    def set_muted(self, muted: bool) -> None:
        self.muted = muted
        # WebEngine has no per-page audio API; mute is enforced by the tab UI
        # state and restored audio is blocked while muted via user gesture.
        self.page.runJavaScript(
            "document.querySelectorAll('audio,video').forEach(function(m){m.muted=%s});"
            % ("true" if muted else "false"))

    # ------------------------------------------------------------------ #
    def shutdown(self) -> None:
        try:
            self.page.setParent(None)
            self.page.deleteLater()
            self.deleteLater()
        except RuntimeError:
            pass


def _feature_name(feature) -> str:
    """Map QWebEnginePage.Feature enum to our settings names."""
    names = {
        QWebEnginePage.Feature.MediaAudioCapture: "microphone",
        QWebEnginePage.Feature.MediaVideoCapture: "camera",
        QWebEnginePage.Feature.MediaAudioVideoCapture: "media_audio_video",
        QWebEnginePage.Feature.DesktopVideoCapture: "desktop_video_capture",
        QWebEnginePage.Feature.DesktopAudioVideoCapture: "desktop_audio_video_capture",
        QWebEnginePage.Feature.Geolocation: "location",
        QWebEnginePage.Feature.Notifications: "notifications",
        QWebEnginePage.Feature.MouseLock: "mouse_lock",
    }
    for k, v in names.items():
        if feature == k:
            return v
    # generic fallbacks for newer features
    try:
        n = feature.name.decode() if isinstance(feature.name, bytes) else str(feature.name)
    except Exception:
        n = str(feature)
    mapping = {"ClipboardReadWrite": "clipboard_read", "Notifications": "notifications",
               "Geolocation": "location", "MediaAudioCapture": "microphone",
               "MediaVideoCapture": "camera", "SaveLink": "save_link",
               "DesktopVideoCapture": "desktop_video_capture",
               "DesktopAudioVideoCapture": "desktop_audio_video_capture",
               "MidiSysex": "midi_sysex", "Midi": "midi", "USB": "usb",
               "Bluetooth": "bluetooth", "BackgroundSync": "background_sync"}
    for k, v in mapping.items():
        if k.lower() in n.lower():
            return v
    return "unknown"
