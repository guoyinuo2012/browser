"""Entry point shim — the real bootstrap lives in browser/main.py.

    python main.py [urls...]
    python -m browser [urls...]
"""

import sys

from browser.main import main

if __name__ == "__main__":
    sys.exit(main())
