#!/usr/bin/env python3
"""Start the web server and Cloudflare tunnel for internet sharing."""
from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def main() -> None:
    from share_public import detect_tunnel_mode, mode_label, resolve_config_path, resolve_public_url

    port = int(os.environ.get("SIM_PORT") or os.environ.get("PORT") or "8080")
    if not os.environ.get("SIM_ADMIN_TOKEN"):
        os.environ["SIM_ADMIN_TOKEN"] = "changeme"
        print("Warning: using default admin token 'changeme'. Set SIM_ADMIN_TOKEN first.\n")

    mode, _ = detect_tunnel_mode()
    config_path = resolve_config_path()
    public_url = resolve_public_url(mode, config_path)

    print(f"Tunnel mode: {mode_label(mode)}")
    if mode == "quick":
        print("  -> Random trycloudflare.com URL each restart.")
        print("  -> For a fixed URL: see setup_named_tunnel.md or run start_local.bat\n")
    else:
        if public_url:
            print(f"  -> Stable URL: {public_url}\n")
        else:
            print("  -> Named tunnel active. Set CLOUDFLARE_PUBLIC_URL to show the link here.\n")

    web = subprocess.Popen(
        [sys.executable, str(ROOT / "run_web.py")],
        cwd=str(ROOT),
        env=os.environ.copy(),
    )
    print(f"Web server starting on port {port}…")
    time.sleep(2)

    try:
        share = subprocess.Popen(
            [sys.executable, str(ROOT / "share_public.py")],
            cwd=str(ROOT),
            env=os.environ.copy(),
        )
        share.wait()
    finally:
        web.terminate()
        try:
            web.wait(timeout=5)
        except subprocess.TimeoutExpired:
            web.kill()


if __name__ == "__main__":
    main()
