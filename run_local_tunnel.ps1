$ErrorActionPreference = "Stop"

$python = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    Write-Error "Create the virtual environment first: python -m venv .venv"
}

if (-not (Get-Command cloudflared -ErrorAction SilentlyContinue)) {
    Write-Error "Install cloudflared first: https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/"
}

$server = Start-Process -FilePath $python -ArgumentList "-m uvicorn main:app --host 127.0.0.1 --port 8000" -PassThru
try {
    Write-Host "Video Agent is running. Copy the https:// URL printed by cloudflared."
    cloudflared tunnel --url http://127.0.0.1:8000
}
finally {
    if ($server -and -not $server.HasExited) {
        Stop-Process -Id $server.Id -Force
    }
}
