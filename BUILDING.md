# Building and packaging — browser

## Run from source (all platforms)

```bash
# 1. Python 3.10+ (3.14 tested)
# 2. Dependencies
pip install PyQt6 PyQt6-WebEngine cryptography

# 3. Start
python main.py
```

Data is created on first run in the platform data directory. Set
`BROWSER_DATA_DIR` to relocate it (also used by the test suite).

## Tests

```bash
python -m unittest discover -s browser/tests -v
```

## Building a distributable

### Windows (single-folder or installer)

```bash
pip install pyinstaller
pyinstaller main.py --name browser --windowed --noconfirm ^
  --collect-all PyQt6 --collect-all PyQt6.QtWebEngineCore ^
  --collect-all PyQt6.QtWebEngineWidgets --collect-submodules browser
```

Output in `dist/browser/browser.exe`. Wrap with Inno Setup / NSIS for an
installer and code-sign the binary with your certificate (`signtool`).
Code-signing is required for SmartScreen trust; without it Windows shows the
standard unsigned-binary warning.

### macOS

```bash
pyinstaller main.py --name browser --windowed --collect-all PyQt6 \
  --collect-submodules browser
codesign --deep --force --sign "Developer ID Application: YOUR NAME" dist/browser.app
```

For distribution outside the App Store, notarize with `xcrun notarytool`.
PyQt6's WebEngine framework must be inside the bundle (PyInstaller
`--collect-all PyQt6` handles this).

### Linux

```bash
pyinstaller main.py --name browser --windowed --collect-all PyQt6 \
  --collect-submodules browser
```

Or package as Flatpak/AppImage. AppImage tooling can wrap the PyInstaller
output. QtWebEngine needs system GPU libraries at runtime
(libEGL, libGL, fontconfig).

## Update channel (optional)

browser never phones home. To operate your own update channel:

1. Host a manifest JSON:
   ```json
   {
     "version": "1.1.0",
     "url": "https://example.com/downloads/browser-1.1.0.exe",
     "sha256": "<hex of package>",
     "channel": "stable",
     "notes": "…",
     "pubkey": "<ed25519 public key hex>"
   }
   ```
2. Sign it: the signature field must be an Ed25519 signature (hex) over the
   canonical JSON of all fields except `signature`, sorted keys, compact
   separators (see `browser/core/updates.py`).
3. Users paste the feed URL in Settings → Advanced → Updates. The first
   check pins your key; later key changes are rejected.

`browser/tools/make_update_manifest.py` shows the exact signing procedure.

## Environment variables

| Variable | Purpose |
|---|---|
| `BROWSER_DATA_DIR` | Override data directory (tests, portable use) |
| `BROWSER_DOWNLOADS_DIR` | Override default download directory |
| `BROWSER_PROXY` | Proxy for the engine, e.g. `socks5://127.0.0.1:9050` |
| `QTWEBENGINE_CHROMIUM_FLAGS` | Advanced: extra Chromium flags |
