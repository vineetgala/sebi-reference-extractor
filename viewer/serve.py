#!/usr/bin/env python3
"""Dev server for the SEBI Reference Viewer.

Serves the project root so the viewer can reach:
  /manifest.json               — golden dataset manifest
  /reference-output/*.json     — pre-computed reference extractions

Usage:
    python3 viewer/serve.py

Then open:
    http://localhost:7890/viewer/

For the "Extract New" tab the FastAPI server must also be running:
    uvicorn api.server:app --reload --port 8000
"""

import http.server
import socketserver
from pathlib import Path

PORT = 7890
ROOT = Path(__file__).resolve().parent.parent   # project root, not viewer/


class _Handler(http.server.SimpleHTTPRequestHandler):
    """Serve files from the project root so /manifest.json and
    /reference-output/ resolve correctly relative to /viewer/index.html."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def log_message(self, fmt, *args):
        # Only surface non-200 responses to avoid cluttering the terminal
        if args[1] != "200":
            super().log_message(fmt, *args)


if __name__ == "__main__":
    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.TCPServer(("", PORT), _Handler) as httpd:
        url = f"http://localhost:{PORT}/viewer/"
        print(f"\n  SEBI Reference Viewer  →  {url}\n")
        print("  For the 'Extract New' tab, also run:")
        print("    uvicorn api.server:app --reload --port 8000\n")
        print("  Press Ctrl-C to stop.\n")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\n  Server stopped.")
