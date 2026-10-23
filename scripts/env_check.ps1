# Read-only Windows environment inventory. Changes nothing; writes one text file.
# Usage: powershell -ExecutionPolicy Bypass -File scripts\env_check.ps1 [-Output evidence\env]
param([string]$Output = "evidence\env")

$ErrorActionPreference = "Continue"
New-Item -ItemType Directory -Force $Output | Out-Null
$stamp = (Get-Date).ToUniversalTime().ToString("yyyyMMddTHHmmssZ")
$file = Join-Path $Output "windows-$stamp.txt"
$lines = New-Object System.Collections.Generic.List[string]
function Section($name) { $lines.Add(""); $lines.Add("=== $name ===") }
function Add($text) { foreach ($l in ($text | Out-String -Width 200).TrimEnd() -split "`r?`n") { $lines.Add($l) } }
function Tool($name, [string[]]$arguments) {
    $cmd = Get-Command $name -ErrorAction SilentlyContinue
    if (-not $cmd) { Add "$name : NOT FOUND in PATH"; return }
    Add "path: $($cmd.Source)"
    try { Add (& $cmd.Source @arguments 2>&1) } catch { Add "error: $($_.Exception.Message)" }
}

$lines.Add("collected_at_utc: $stamp")
$lines.Add("host: $env:COMPUTERNAME")

Section "OS"
$os = Get-CimInstance Win32_OperatingSystem
Add "$($os.Caption) version=$($os.Version) build=$($os.BuildNumber) arch=$($os.OSArchitecture)"

Section "CPU"
Get-CimInstance Win32_Processor | ForEach-Object { Add "$($_.Name) cores=$($_.NumberOfCores) logical=$($_.NumberOfLogicalProcessors)" }

Section "Memory"
Add ("total_GiB={0:N2} free_GiB={1:N2}" -f ($os.TotalVisibleMemorySize / 1MB), ($os.FreePhysicalMemory / 1MB))

Section "Disks"
Get-PSDrive -PSProvider FileSystem | Where-Object { $null -ne $_.Used } | ForEach-Object {
    Add ("{0}: used_GiB={1:N1} free_GiB={2:N1}" -f $_.Name, ($_.Used / 1GB), ($_.Free / 1GB))
}

Section "Display adapters (WMI; AdapterRAM is capped at 4GB and is not reliable VRAM)"
Get-CimInstance Win32_VideoController | ForEach-Object { Add "$($_.Name) driver=$($_.DriverVersion)" }

Section "nvidia-smi (CUDA Version here = max CUDA supported by the DRIVER, not an installed toolkit)"
Tool "nvidia-smi" @()
Section "nvidia-smi query"
Tool "nvidia-smi" @("--query-gpu=index,name,memory.total,memory.used,driver_version,compute_cap", "--format=csv")

Section "CUDA Toolkit (nvcc)"
Tool "nvcc" @("--version")

Section "Python"
Tool "python" @("--version")
Tool "python" @("-c", "import importlib.util as u; print('pytest installed:', bool(u.find_spec('pytest'))); print('vllm installed:', bool(u.find_spec('vllm')))")

Section "Docker / NVIDIA Container Toolkit / WSL"
Tool "docker" @("--version")
Tool "nvidia-ctk" @("--version")
$wsl = Get-Command wsl.exe -ErrorAction SilentlyContinue
if ($wsl) {
    # wsl.exe writes UTF-16LE; decode it as such so the message is readable.
    $prev = [Console]::OutputEncoding
    [Console]::OutputEncoding = [System.Text.Encoding]::Unicode
    $raw = cmd.exe /c "wsl.exe --status 2>&1" | Out-String
    [Console]::OutputEncoding = $prev
    Add ("wsl --status (exit=$LASTEXITCODE): " + $raw.Trim())
} else { Add "wsl.exe : NOT FOUND" }

Section "Ollama / vLLM / llama processes"
Get-CimInstance Win32_Process | Where-Object { $_.Name -match "ollama|vllm|llama" } | ForEach-Object { Add "pid=$($_.ProcessId) name=$($_.Name) cmd=$($_.CommandLine)" }

Section "Listening ports of interest (11434-11437 Ollama, 8000 vLLM, 8080/11436 gateway)"
Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue | Where-Object { $_.LocalPort -in 8000, 8080, 11434, 11435, 11436, 11437 } |
    ForEach-Object { $p = Get-Process -Id $_.OwningProcess -ErrorAction SilentlyContinue; Add "$($_.LocalAddress):$($_.LocalPort) pid=$($_.OwningProcess) $($p.ProcessName)" }

Section "Model directories"
foreach ($dir in @("$env:USERPROFILE\.ollama\models", "$env:USERPROFILE\.cache\huggingface", (Join-Path $PSScriptRoot "..\..\..\work\runtime\models"))) {
    if (Test-Path $dir) {
        $sum = (Get-ChildItem $dir -Recurse -File -ErrorAction SilentlyContinue | Measure-Object Length -Sum).Sum
        Add ("{0} : {1:N2} GiB" -f (Resolve-Path $dir), ($sum / 1GB))
    } else { Add "$dir : missing" }
}

$lines | Out-File -FilePath $file -Encoding utf8
Write-Output $file
