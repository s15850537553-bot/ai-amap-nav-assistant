$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
$cloudflared = Join-Path $root "tools\cloudflared.exe"

if (!(Test-Path $cloudflared)) {
  New-Item -ItemType Directory -Force -Path (Split-Path -Parent $cloudflared) | Out-Null
  Invoke-WebRequest `
    -Uri "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe" `
    -OutFile $cloudflared `
    -UseBasicParsing
}

Write-Host "Starting Cloudflare Quick Tunnel for http://127.0.0.1:8000 ..."
& $cloudflared tunnel --url http://127.0.0.1:8000 --no-autoupdate
