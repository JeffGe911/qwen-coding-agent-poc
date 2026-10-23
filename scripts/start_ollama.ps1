# Start the portable Ollama with explicit, recorded settings. Loopback only; no cloud models.
# Refuses to start if the port is already in use (never touches an existing service).
# Usage: powershell -ExecutionPolicy Bypass -File scripts\start_ollama.ps1 [-Port 11437] [-Context 4096] [-NumParallel 2]
param(
    [int]$Port = 11437,
    [int]$Context = 4096,
    [int]$NumParallel = 2,
    [string]$KeepAlive = "30m",
    [string]$Runtime = (Join-Path $PSScriptRoot "..\..\..\work\runtime"),
    [string]$Evidence = (Join-Path $PSScriptRoot "..\evidence\serving")
)
$ErrorActionPreference = "Stop"
$Runtime = (Resolve-Path $Runtime).Path
$exe = Join-Path $Runtime "ollama\ollama.exe"
$models = Join-Path $Runtime "models"
if (-not (Test-Path $exe)) { throw "Ollama binary not found: $exe" }
if (Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue) {
    throw "Port $Port is already listening. Not starting a second server; inspect it first."
}

$settings = [ordered]@{
    OLLAMA_HOST               = "127.0.0.1:$Port"   # loopback only
    OLLAMA_MODELS             = $models
    OLLAMA_CONTEXT_LENGTH     = "$Context"
    OLLAMA_NUM_PARALLEL       = "$NumParallel"
    OLLAMA_MAX_LOADED_MODELS  = "1"
    OLLAMA_KEEP_ALIVE         = $KeepAlive
    OLLAMA_NO_CLOUD           = "1"
}
foreach ($k in $settings.Keys) { Set-Item "env:$k" $settings[$k] }

$logs = Join-Path $Runtime "logs"
New-Item -ItemType Directory -Force $logs, $Evidence | Out-Null
$stamp = (Get-Date).ToUniversalTime().ToString("yyyyMMddTHHmmssZ")
$errLog = Join-Path $logs "ollama-$Port-$stamp.err.log"
$outLog = Join-Path $logs "ollama-$Port-$stamp.out.log"
$proc = Start-Process -FilePath $exe -ArgumentList "serve" -WindowStyle Hidden -PassThru `
    -RedirectStandardError $errLog -RedirectStandardOutput $outLog

$version = $null
for ($i = 0; $i -lt 60 -and -not $version; $i++) {
    Start-Sleep -Milliseconds 500
    try { $version = (Invoke-RestMethod "http://127.0.0.1:$Port/api/version" -TimeoutSec 2).version } catch {}
}
if (-not $version) { throw "Ollama did not become ready on port $Port; see $errLog" }

# Ollama prints the effective configuration and GPU discovery at startup.
Start-Sleep -Seconds 4  # GPU discovery is logged a few seconds after the listener starts.
# Cast to plain strings; Get-Content lines carry PS metadata that would bloat the JSON.
$startup = @(Get-Content $errLog -Encoding utf8 | Where-Object { $_ -match "server config|inference compute|Listening on|total_vram|library=" } | ForEach-Object { [string]$_ })
$record = [ordered]@{
    started_at_utc   = $stamp
    pid              = $proc.Id
    command          = "`"$exe`" serve"
    exe_sha256       = (Get-FileHash $exe -Algorithm SHA256).Hash.ToLower()
    server_version   = $version
    environment      = $settings
    stderr_log       = $errLog
    startup_log_lines = @($startup)
    note             = "nvidia-smi 'CUDA Version' is the driver capability. Ollama ships its own CUDA runtime (lib\ollama\cuda_v12, cuda_v13); no CUDA Toolkit is installed on this host."
}
$file = Join-Path $Evidence "ollama-launch-$Port-$stamp.json"
$record | ConvertTo-Json -Depth 5 | Out-File -FilePath $file -Encoding utf8
Write-Output "Ollama $version ready on 127.0.0.1:$Port (pid $($proc.Id)). Record: $file"
