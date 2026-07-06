#!/usr/bin/env python3
"""Start the public web dashboard."""
from __future__ import annotations

import os
import sys
from pathlib import Path

if __name__ == "__main__":
    import uvicorn

    root = os.path.dirname(os.path.abspath(__file__))
    if root not in sys.path:
        sys.path.insert(0, root)

    host = os.environ.get("SIM_HOST", "0.0.0.0")
    # Cloud hosts (Render, Railway, Fly) inject PORT; prefer it over SIM_PORT.
    port = int(os.environ.get("PORT") or os.environ.get("SIM_PORT") or "8080")
    token = os.environ.get("SIM_ADMIN_TOKEN", "changeme")

    if token == "changeme" and os.environ.get("RENDER"):
        print("WARNING: SIM_ADMIN_TOKEN is still 'changeme'. Set a secret in the Render dashboard.\n")

    url_file = Path(root) / "data" / "public_url.txt"
    public = os.environ.get("RENDER_EXTERNAL_URL", "").strip()
    if not public and url_file.exists():
        public = url_file.read_text(encoding="utf-8").strip()

    print(f"Home:       http://localhost:{port}/")
    print(f"Admin:      http://localhost:{port}/admin")
    print(f"Login:      http://localhost:{port}/login")
    print(f"Squad hub:  http://localhost:{port}/squad")
    if public:
        print(f"Public:     {public}/")
        print(f"Admin:      {public}/admin")
        print(f"Team lab:   {public}/lab")
    else:
        print("Internet:   run  python run_public.py  (or deploy via Render — see DEPLOY.md)")

    reload = os.environ.get("SIM_RELOAD", "").lower() in ("1", "true", "yes")
    if not reload:
        print("Tip: restart this process after code changes (or set SIM_RELOAD=1 for auto-reload).")
    uvicorn.run("web.app:app", host=host, port=port, reload=reload)
