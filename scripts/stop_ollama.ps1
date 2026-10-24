# Stop the project's portable Ollama on one port, including its llama-server model runner.
# Safety: refuses unless the listening process is this workspace's ollama.exe (never stops other services).
# Usage: powershell -ExecutionPolicy Bypass -File scripts\stop_ollama.ps1 [-Port 11437]   (runtime: -Runtime or $env:QWEN_POC_RUNTIME)
param(
    [int]$Port = 11437,
    [string]$Runtime = $(if ($env:QWEN_POC_RUNTIME) { $env:QWEN_POC_RUNTIME } else { Join-Path $PSScriptRoot "..\..\..\work\runtime" })
)
$ErrorActionPreference = "Stop"
$expected = (Resolve-Path (Join-Path $Runtime "ollama\ollama.exe")).Path
$listen = Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue | Select-Object -First 1
if (-not $listen) { Write-Output "Nothing listening on $Port; already stopped."; Write-Output "STOPPED=none"; exit 0 }
$proc = Get-CimInstance Win32_Process -Filter "ProcessId=$($listen.OwningProcess)"
if ($proc.ExecutablePath -ne $expected) {
    throw "Port $Port belongs to pid $($proc.ProcessId) ($($proc.ExecutablePath)), not $expected. Refusing to stop it."
}
$children = @(Get-CimInstance Win32_Process -Filter "ParentProcessId=$($proc.ProcessId)" | ForEach-Object { "$($_.Name):$($_.ProcessId)" })
$before = (& nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits) -join ""
# /T kills the process tree (ollama.exe + llama-server runner that holds the VRAM).
& taskkill.exe /PID $proc.ProcessId /T /F | Out-Null
$closed = $false
for ($i = 0; $i -lt 40 -and -not $closed; $i++) {
    Start-Sleep -Milliseconds 250
    $closed = -not (Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue)
}
Start-Sleep -Seconds 1
$left = @(Get-CimInstance Win32_Process -Filter "ParentProcessId=$($proc.ProcessId)" -ErrorAction SilentlyContinue)
$after = (& nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits) -join ""
Write-Output ("Stopped pid {0} on port {1}; children {2}; port closed={3}; leftover children={4}; GPU memory used {5} MiB -> {6} MiB" -f `
    $proc.ProcessId, $Port, ($children -join ","), $closed, $left.Count, $before.Trim(), $after.Trim())
if (-not $closed -or $left.Count) { throw "Stop incomplete; inspect manually." }
Write-Output "STOPPED=$($proc.ProcessId)"
