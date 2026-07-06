#!/usr/bin/env python3
"""Expose the local simulator dashboard to the internet via Cloudflare Tunnel."""
from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PORT = int(os.environ.get("SIM_PORT") or os.environ.get("PORT") or "8080")
URL_FILE = ROOT / "data" / "public_url.txt"

QUICK_URL_PATTERN = re.compile(r"https://[a-z0-9-]+\.trycloudflare\.com")
PLACEHOLDER_MARKERS = (
    "YOUR_USER",
    "TUNNEL-UUID",
    "yourdomain.com",
    "your-secret-token",
    "changeme",
)


def find_cloudflared() -> str:
    found = shutil.which("cloudflared")
    if found:
        return found
    candidates = [
        Path(os.environ.get("ProgramFiles", "")) / "cloudflared" / "cloudflared.exe",
        Path(os.environ.get("ProgramFiles(x86)", "")) / "cloudflared" / "cloudflared.exe",
        Path(os.environ.get("LocalAppData", "")) / "Microsoft" / "WinGet" / "Links" / "cloudflared.exe",
    ]
    for p in candidates:
        if p.is_file():
            return str(p)
    raise SystemExit(
        "cloudflared not found. Install: winget install Cloudflare.cloudflared"
    )


def resolve_config_path(*, strict: bool = False) -> Path | None:
    env = os.environ.get("CLOUDFLARE_TUNNEL_CONFIG", "").strip()
    if env:
        p = Path(env).expanduser()
        if p.is_file():
            return p.resolve()
        if strict:
            raise SystemExit(f"CLOUDFLARE_TUNNEL_CONFIG not found: {env}")
        return None

    for candidate in (
        ROOT / "cloudflared-config.yml",
        ROOT / "cloudflared-config.yaml",
        Path.home() / ".cloudflared" / "config.yml",
        Path.home() / ".cloudflared" / "config.yaml",
    ):
        if candidate.is_file():
            return candidate.resolve()
    return None


def public_url_from_config(config_path: Path) -> str | None:
    fields = parse_config_fields(config_path)
    if "error" in fields:
        return None
    host = fields.get("hostname")
    if host and not _looks_like_placeholder(host):
        return f"https://{host}"
    return None


def resolve_public_url(mode: str, config_path: Path | None) -> str | None:
    explicit = os.environ.get("CLOUDFLARE_PUBLIC_URL", "").strip().rstrip("/")
    if explicit:
        return explicit if explicit.startswith("http") else f"https://{explicit}"

    if mode != "quick" and config_path:
        return public_url_from_config(config_path)

    if mode != "quick" and URL_FILE.is_file():
        saved = URL_FILE.read_text(encoding="utf-8").strip()
        if saved and "trycloudflare.com" not in saved:
            return saved.rstrip("/")

    return None


def detect_tunnel_mode() -> tuple[str, Path | None]:
    token = os.environ.get("CLOUDFLARE_TUNNEL_TOKEN", "").strip()
    if token:
        return "named-token", resolve_config_path()

    tunnel_name = os.environ.get("CLOUDFLARE_TUNNEL_NAME", "").strip()
    config_path = resolve_config_path()
    if tunnel_name or config_path:
        return "named-config", config_path

    return "quick", None


def mode_label(mode: str) -> str:
    return {
        "named-token": "NAMED (token)",
        "named-config": "NAMED (config)",
        "quick": "QUICK (ephemeral trycloudflare.com)",
    }[mode]


def _looks_like_placeholder(value: str) -> bool:
    lowered = value.lower()
    return any(marker.lower() in lowered for marker in PLACEHOLDER_MARKERS)


def parse_config_fields(config_path: Path) -> dict[str, str | None]:
    try:
        text = config_path.read_text(encoding="utf-8")
    except OSError as exc:
        return {"error": str(exc)}

    tunnel_name: str | None = None
    credentials: str | None = None
    hostname: str | None = None

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("- "):
            line = line[2:].strip()

        if line.lower().startswith("tunnel:"):
            tunnel_name = line.split(":", 1)[1].strip().strip("'\"")
        elif line.lower().startswith("credentials-file:"):
            credentials = line.split(":", 1)[1].strip().strip("'\"")
        elif line.lower().startswith("hostname:"):
            host = line.split(":", 1)[1].strip().strip("'\"")
            if host and host not in ("localhost", "127.0.0.1"):
                hostname = host

    return {
        "tunnel": tunnel_name,
        "credentials_file": credentials,
        "hostname": hostname,
    }


def collect_checklist(mode: str, config_path: Path | None) -> tuple[list[str], list[str]]:
    """Return (ok_items, missing_or_warn_items) for --check output."""
    ok: list[str] = []
    issues: list[str] = []

    admin = os.environ.get("SIM_ADMIN_TOKEN", "").strip()
    if admin and not _looks_like_placeholder(admin):
        ok.append("SIM_ADMIN_TOKEN is set")
    elif admin:
        issues.append("SIM_ADMIN_TOKEN still uses a placeholder — set a real secret")
    else:
        issues.append("SIM_ADMIN_TOKEN not set (run_public.py defaults to 'changeme')")

    public_url = resolve_public_url(mode, config_path)
    if mode == "quick":
        ok.append("Quick tunnel needs no DNS or config file")
        issues.append(
            "Public URL changes every restart (*.trycloudflare.com) — "
            "use named tunnel for a fixed URL (setup_named_tunnel.md)"
        )
        return ok, issues

    if mode == "named-token":
        token = os.environ.get("CLOUDFLARE_TUNNEL_TOKEN", "").strip()
        if token:
            ok.append("CLOUDFLARE_TUNNEL_TOKEN is set")
        else:
            issues.append("CLOUDFLARE_TUNNEL_TOKEN is empty")
        if public_url and not _looks_like_placeholder(public_url):
            ok.append(f"CLOUDFLARE_PUBLIC_URL: {public_url}")
        else:
            issues.append(
                "Set CLOUDFLARE_PUBLIC_URL=https://sim.yourdomain.com "
                "(or in start_local.ps1)"
            )
        issues.append(
            "Ensure DNS route exists in Cloudflare dashboard "
            "(Public Hostname -> http://localhost:8080)"
        )
        return ok, issues

    # named-config
    if config_path:
        ok.append(f"Config file found: {config_path}")
    else:
        issues.append(
            "No cloudflared config — copy cloudflared-config.yml.example to "
            "cloudflared-config.yml (or set CLOUDFLARE_TUNNEL_CONFIG)"
        )
        issues.append(
            "Or set CLOUDFLARE_TUNNEL_TOKEN from Cloudflare Zero Trust dashboard"
        )
        return ok, issues

    fields = parse_config_fields(config_path)
    if "error" in fields:
        issues.append(f"Cannot read config: {fields['error']}")
        return ok, issues

    tunnel_name = fields.get("tunnel")
    if tunnel_name:
        ok.append(f"Tunnel name in config: {tunnel_name}")
    else:
        issues.append("Add `tunnel: fantasy-football-sim` to cloudflared-config.yml")

    cred_path_raw = fields.get("credentials_file")
    if not cred_path_raw:
        issues.append(
            "Add credentials-file path to cloudflared-config.yml "
            "(from `cloudflared tunnel create` output)"
        )
    elif _looks_like_placeholder(cred_path_raw):
        issues.append(
            f"Replace placeholder credentials-file in config: {cred_path_raw}"
        )
    else:
        cred_path = Path(cred_path_raw).expanduser()
        if cred_path.is_file():
            ok.append(f"Credentials file exists: {cred_path}")
        else:
            issues.append(
                f"Credentials file not found: {cred_path} — "
                "run `cloudflared tunnel create fantasy-football-sim`"
            )

    hostname = fields.get("hostname")
    if not hostname:
        issues.append("Add hostname under ingress in cloudflared-config.yml")
    elif _looks_like_placeholder(hostname):
        issues.append(
            f"Replace placeholder hostname in config: {hostname}"
        )
    else:
        ok.append(f"Hostname in config: {hostname}")

    env_tunnel = os.environ.get("CLOUDFLARE_TUNNEL_NAME", "").strip()
    if env_tunnel:
        ok.append(f"CLOUDFLARE_TUNNEL_NAME: {env_tunnel}")

    if public_url and not _looks_like_placeholder(public_url):
        ok.append(f"Public URL: {public_url}")
    elif hostname and not _looks_like_placeholder(hostname):
        ok.append(f"Public URL (from config): https://{hostname}")
        issues.append(
            "Set CLOUDFLARE_PUBLIC_URL for banners and data/public_url.txt "
            "(edit start_local.ps1 or set env var)"
        )
    else:
        issues.append(
            "Set CLOUDFLARE_PUBLIC_URL=https://sim.yourdomain.com"
        )

    issues.append(
        "Run once if not done: "
        f"cloudflared tunnel route dns {tunnel_name or 'fantasy-football-sim'} "
        f"{hostname or 'sim.yourdomain.com'}"
    )
    issues.append(
        "Run once if not done: cloudflared tunnel login (pick your domain zone)"
    )

    return ok, issues


def build_tunnel_command(exe: str, mode: str, config_path: Path | None) -> list[str]:
    if mode == "named-token":
        token = os.environ["CLOUDFLARE_TUNNEL_TOKEN"].strip()
        return [exe, "tunnel", "run", "--token", token]

    if mode == "named-config":
        cmd = [exe, "tunnel"]
        if config_path:
            cmd.extend(["--config", str(config_path)])
        cmd.append("run")
        tunnel_name = os.environ.get("CLOUDFLARE_TUNNEL_NAME", "").strip()
        if tunnel_name:
            cmd.append(tunnel_name)
        return cmd

    return [exe, "tunnel", "--url", f"http://127.0.0.1:{PORT}"]


def write_public_url(public_url: str) -> None:
    URL_FILE.parent.mkdir(parents=True, exist_ok=True)
    URL_FILE.write_text(public_url + "\n", encoding="utf-8")


def print_public_banner(public_url: str) -> None:
    print("\n" + "=" * 60)
    print("PUBLIC URLS (share these on the internet):")
    print(f"  Login:        {public_url}/login")
    print(f"  Experiments:  {public_url}/")
    print(f"  Team lab:     {public_url}/lab")
    print(f"\nADMIN (keep private): {public_url}/admin")
    print("=" * 60 + "\n")


def run_check() -> int:
    try:
        exe = find_cloudflared()
    except SystemExit as exc:
        print(f"FAIL: {exc}")
        print("\nInstall (Windows, one time):")
        print("  winget install Cloudflare.cloudflared")
        print("Then reopen the terminal and run this check again.")
        return 1

    mode, config_path = detect_tunnel_mode()
    public_url = resolve_public_url(mode, config_path)
    ok_items, issues = collect_checklist(mode, config_path)

    print("=" * 60)
    print("CLOUDFLARE TUNNEL CHECK")
    print("=" * 60)
    print(f"cloudflared:  {exe}")
    print(f"Tunnel mode:  {mode_label(mode)}")
    print(f"Local port:   {PORT} (set SIM_PORT to change)")
    if config_path:
        print(f"Config:       {config_path}")
    print()

    if ok_items:
        print("OK:")
        for item in ok_items:
            print(f"  [+] {item}")
        print()

    blocking = [i for i in issues if not i.startswith("Run once if not done:")]
    hints = [i for i in issues if i.startswith("Run once if not done:")]

    if blocking:
        print("MISSING or NEEDS ACTION:")
        for item in blocking:
            print(f"  [!] {item}")
        print()

    if hints:
        print("ONE-TIME SETUP (if you have not done these yet):")
        for item in hints:
            print(f"  [?] {item.replace('Run once if not done: ', '')}")
        print()

    if mode == "quick":
        print("QUICK MODE URL:")
        print("  Assigned at runtime, e.g. https://random-words.trycloudflare.com")
        print("  Saved to data/public_url.txt while the tunnel is running.")
    elif public_url and not _looks_like_placeholder(public_url):
        print("YOUR FIXED URL (same every restart):")
        print(f"  Viewers:  {public_url}/login")
        print(f"  Admin:    {public_url}/admin")
    elif config_path:
        fields = parse_config_fields(config_path)
        host = fields.get("hostname")
        if host and not _looks_like_placeholder(host):
            print("YOUR FIXED URL (after tunnel starts):")
            print(f"  Viewers:  https://{host}/login")
            print(f"  Admin:    https://{host}/admin")

    print()
    print("LOCAL DATA (persists on your laptop across restarts):")
    data_dir = ROOT / "data"
    for sub in ("experiments", "tournaments", "player_stats_cache.json", "web_state.json"):
        path = data_dir / sub
        exists = path.exists()
        mark = "[+]" if exists else "[ ]"
        print(f"  {mark} {path}")
    print()

    cmd = build_tunnel_command(exe, mode, config_path)
    print(f"Would run: {' '.join(cmd)}")

    ready = mode == "quick" or (
        not any(
            "not found" in i.lower()
            or "placeholder" in i.lower()
            or "empty" in i.lower()
            or "no cloudflared config" in i.lower()
            or "cannot read config" in i.lower()
            for i in blocking
        )
        and (mode != "named-config" or config_path is not None)
    )
    if ready and mode != "quick":
        print("\nStatus: READY for named tunnel — run start_local.bat or python run_public.py")
    elif mode == "quick":
        print("\nStatus: READY for quick tunnel — URL will change each restart")
    else:
        print("\nStatus: NOT READY — fix items marked [!] above, then re-run --check")
        return 1
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="Validate cloudflared and tunnel mode without starting a tunnel",
    )
    args = parser.parse_args()

    if args.check:
        sys.exit(run_check())

    exe = find_cloudflared()
    mode, config_path = detect_tunnel_mode()
    cmd = build_tunnel_command(exe, mode, config_path)
    public_url = resolve_public_url(mode, config_path)

    print(f"Tunnel mode: {mode_label(mode)}")
    if mode == "quick":
        print("Tip: for a fixed URL, see setup_named_tunnel.md\n")
    elif public_url:
        write_public_url(public_url)
        print(f"Stable URL: {public_url}\n")
    else:
        print(
            "Set CLOUDFLARE_PUBLIC_URL or add hostname to cloudflared-config.yml "
            "to save the link in data/public_url.txt\n"
        )

    print(f"Starting tunnel -> http://127.0.0.1:{PORT}")
    print("Keep this window open while others use the public link.\n")

    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )

    banner_shown = public_url is not None
    if banner_shown and public_url:
        print_public_banner(public_url)

    assert proc.stdout is not None
    for line in proc.stdout:
        print(line, end="")
        if mode == "quick" and not banner_shown:
            match = QUICK_URL_PATTERN.search(line)
            if match:
                public_url = match.group(0)
                write_public_url(public_url)
                print_public_banner(public_url)
                banner_shown = True

    proc.wait()
    if proc.returncode != 0:
        sys.exit(proc.returncode or 1)


if __name__ == "__main__":
    main()
