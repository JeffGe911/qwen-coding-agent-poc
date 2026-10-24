# Start the portable Ollama with explicit, recorded settings. Loopback only; no cloud models.
# Refuses to start if the port is already in use (never touches an existing service).
# Usage: powershell -ExecutionPolicy Bypass -File scripts\start_ollama.ps1 [-Port 11437] [-Context 4096] [-NumParallel 2] [-MaxQueue 512] [-ExtraEnv "K=V",...]
# Runtime (ollama.exe + models) defaults to ..\..\..\work\runtime; override with -Runtime or $env:QWEN_POC_RUNTIME.
# -ExtraEnv adds server variables for drills (e.g. CUDA_VISIBLE_DEVICES=-1); they are written to the launch record.
# Last output line is RECORD=<launch record path> for scripts.
param(
    [int]$Port = 11437,
    [int]$Context = 4096,
    [int]$NumParallel = 2,
    [int]$MaxQueue = 512,        # Ollama default; requests beyond the queue get HTTP 503
    [int]$KeepLogs = 20,         # keep the newest N stderr/stdout log pairs for this port
    [string]$KeepAlive = "30m",
    [string[]]$ExtraEnv = @(),
    [string]$Runtime = $(if ($env:QWEN_POC_RUNTIME) { $env:QWEN_POC_RUNTIME } else { Join-Path $PSScriptRoot "..\..\..\work\runtime" }),
    [string]$Evidence = (Join-Path $PSScriptRoot "..\evidence\serving")
)
$ErrorActionPreference = "Stop"
if (-not (Test-Path $Runtime)) { throw "Runtime folder not found: $Runtime. Pass -Runtime or set QWEN_POC_RUNTIME to the folder holding ollama\ollama.exe and models\" }
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
    OLLAMA_MAX_QUEUE          = "$MaxQueue"
    OLLAMA_MAX_LOADED_MODELS  = "1"
    OLLAMA_KEEP_ALIVE         = $KeepAlive
    OLLAMA_NO_CLOUD           = "1"
}
# powershell -File passes "A=1,B=2" as one string, so split on , and ; as well.
foreach ($pair in @($ExtraEnv -join ";" -split "[;,]" | Where-Object { $_ })) {
    $k, $v = $pair -split "=", 2
    if (-not $k -or $null -eq $v) { throw "-ExtraEnv expects K=V, got: $pair" }
    $settings[$k] = $v
}
# Server-relevant variables inherited from the caller are recorded too, so a launch is reproducible.
$inherited = [ordered]@{}
Get-ChildItem env: | Where-Object { $_.Name -match "^(OLLAMA_|CUDA_|GGML_|HIP_|HTTPS?_PROXY$|NO_PROXY$)" -and -not $settings.Contains($_.Name) } |
    ForEach-Object { $inherited[$_.Name] = $_.Value -replace "//[^/@\s]+@", "//***@" }  # never record proxy credentials
foreach ($k in $settings.Keys) { Set-Item "env:$k" $settings[$k] }

$logs = Join-Path $Runtime "logs"
New-Item -ItemType Directory -Force $logs, $Evidence | Out-Null
$stamp = (Get-Date).ToUniversalTime().ToString("yyyyMMddTHHmmssZ")
$errLog = Join-Path $logs "ollama-$Port-$stamp.err.log"
$outLog = Join-Path $logs "ollama-$Port-$stamp.out.log"
# Log retention: each start writes a new log pair; prune old pairs for this port (our own files only).
Get-ChildItem $logs -Filter "ollama-$Port-*.log" -ErrorAction SilentlyContinue | Sort-Object LastWriteTime -Descending |
    Select-Object -Skip ($KeepLogs * 2) | Remove-Item -Force -ErrorAction SilentlyContinue
# Launch through ShellExecute (Start-Process without -Redirect*), which hands no handles to the child. With
# -Redirect*, Windows passes every inheritable handle of this PowerShell to ollama.exe, including a caller's
# output pipe (Git Bash, Python subprocess), and that caller then waits for as long as the server runs.
# cmd.exe does the log redirection instead; it exits when ollama.exe exits.
$t0 = Get-Date
$wrapper = Start-Process -FilePath (Join-Path $env:SystemRoot "System32\cmd.exe") -WindowStyle Hidden -PassThru `
    -ArgumentList "/d /c `"`"$exe`" serve 1>`"$outLog`" 2>`"$errLog`"`""

$version = $null
for ($i = 0; $i -lt 60 -and -not $version; $i++) {
    Start-Sleep -Milliseconds 500
    try { $version = (Invoke-RestMethod "http://127.0.0.1:$Port/api/version" -TimeoutSec 2).version } catch {}
}
if (-not $version) {
    try { & taskkill.exe /PID $wrapper.Id /T /F 2>&1 | Out-Null } catch {}  # do not leave an unrecorded server behind
    throw "Ollama did not become ready on port $Port; see $errLog"
}
$readySeconds = [math]::Round(((Get-Date) - $t0).TotalSeconds, 2)
# The server PID is the process listening on the port; it must be this runtime's ollama.exe started by our wrapper.
$listen = Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue | Select-Object -First 1
$proc = Get-CimInstance Win32_Process -Filter "ProcessId=$($listen.OwningProcess)"
if ($proc.ExecutablePath -ne $exe -or $proc.ParentProcessId -ne $wrapper.Id) {
    throw "Port $Port is served by pid $($proc.ProcessId) ($($proc.ExecutablePath), parent $($proc.ParentProcessId)), not the ollama.exe just started"
}

# Ollama prints the effective configuration and GPU discovery at startup.
Start-Sleep -Seconds 4  # GPU discovery is logged a few seconds after the listener starts.
# Cast to plain strings; Get-Content lines carry PS metadata that would bloat the JSON.
$startup = @(Get-Content $errLog -Encoding utf8 | Where-Object { $_ -match "server config|inference compute|Listening on|total_vram|library=" } | ForEach-Object { [string]$_ })
$record = [ordered]@{
    started_at_utc   = $stamp
    pid              = $proc.ProcessId
    wrapper_pid      = $wrapper.Id
    command          = "`"$exe`" serve"
    exe_sha256       = (Get-FileHash $exe -Algorithm SHA256).Hash.ToLower()
    server_version   = $version
    api_ready_seconds = $readySeconds
    environment      = $settings
    inherited_environment = $inherited
    stderr_log       = $errLog
    startup_log_lines = @($startup)
    note             = "nvidia-smi 'CUDA Version' is the driver capability. Ollama ships its own CUDA runtime (lib\ollama\cuda_v12, cuda_v13); no CUDA Toolkit is installed on this host."
}
$file = Join-Path $Evidence "ollama-launch-$Port-$stamp.json"
$record | ConvertTo-Json -Depth 5 | Out-File -FilePath $file -Encoding utf8
Write-Output "Ollama $version API ready on 127.0.0.1:$Port in $readySeconds s (pid $($proc.ProcessId)). Model loads on first request."
Write-Output "RECORD=$file"
