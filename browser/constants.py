"""Application constants for browser."""

APP_NAME = "browser"
APP_VERSION = "1.0.0"
APP_USER_AGENT_COMMENT = "browser"

SCHEME = b"browser"
SCHEME_STR = "browser"

# Internal URLs
URL_HOME = "browser://home"
URL_SETTINGS = "browser://settings"
URL_HISTORY = "browser://history"
URL_BOOKMARKS = "browser://bookmarks"
URL_DOWNLOADS = "browser://downloads"
URL_PASSWORDS = "browser://passwords"
URL_PRIVACY = "browser://privacy"
URL_SECURITY = "browser://security"
URL_EXTENSIONS = "browser://extensions"
URL_PERMISSIONS = "browser://permissions"
URL_ABOUT = "browser://about"
URL_BLOCKED = "browser://blocked"
URL_ERROR = "browser://error"

# QtWebEngine local storage will not persist these; kept for reference.
MAX_TAB_PREVIEW = 160  # px width of hover previews

DEFAULT_DOWNLOADS_DIR_NAME = "browser downloads"
