"""Application entry point for DevMonitor.

Allows running the application directly from the prototype root:
    python app.py
or using the Flask CLI:
    flask run
"""

import os
import sys
from pathlib import Path

# Ensure the package directory is resolvable
_CURRENT_DIR = Path(__file__).resolve().parent
if str(_CURRENT_DIR) not in sys.path:
    sys.path.insert(0, str(_CURRENT_DIR))

from python.app import app, create_app

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    debug = os.environ.get("FLASK_DEBUG", "true").lower() in ("true", "1")
    app.run(host="127.0.0.1", port=port, debug=debug)
