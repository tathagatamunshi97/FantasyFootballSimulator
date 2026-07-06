# Start the simulator locally with a Cloudflare named tunnel (fixed public URL).
# One-time setup: follow setup_named_tunnel.md, then edit the two lines below.

$env:SIM_ADMIN_TOKEN = "your-secret-token-here"
$env:CLOUDFLARE_PUBLIC_URL = "https://sim.yourdomain.com"

Set-Location $PSScriptRoot

Write-Host ""
Write-Host "Checking tunnel setup..." -ForegroundColor Cyan
python share_public.py --check
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host ""
Write-Host "Starting web server + tunnel (data stays in .\data\)..." -ForegroundColor Cyan
Write-Host "Press Ctrl+C to stop.`n"
python run_public.py
