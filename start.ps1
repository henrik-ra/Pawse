<#
.SYNOPSIS
    Start Pawse with live Xiaomi-watch syncing in a single command.

.DESCRIPTION
    Launches two things together so the dashboard shows near-real-time data:
      1. The Gadgetbridge sync loop in the background
         (watch -> phone -> laptop DB, every -IntervalSeconds).
      2. The Pawse web server in the foreground.

    Press Ctrl+C to stop the server; the background sync loop is stopped
    automatically on exit.

    Without this launcher, `python server.py` only serves whatever
    Gadgetbridge.db is already on disk -- it does NOT pull fresh watch data.
    Use -NoSync to get that old behaviour (serve only, no live pulling).

.PARAMETER IntervalSeconds
    Seconds between watch syncs (default 120). Practical floor is ~60-90s.

.PARAMETER NoSync
    Skip the background sync loop and just serve the existing DB.

.PARAMETER Wearable
    Wearable source for the server (default "xiaomi").

.EXAMPLE
    ./start.ps1
    ./start.ps1 -IntervalSeconds 120
    ./start.ps1 -NoSync
#>
[CmdletBinding()]
param(
    [int]$IntervalSeconds = 120,
    [switch]$NoSync,
    [string]$Wearable = "xiaomi"
)

$ErrorActionPreference = 'Stop'
$Root    = $PSScriptRoot
$LocalDb = Join-Path $env:USERPROFILE 'Pawse\data\gadgetbridge-db\Gadgetbridge.db'

# adb is a system tool (not a pip package); the sync loop needs it on PATH.
function Resolve-AdbDir {
    $cmd = Get-Command adb -ErrorAction SilentlyContinue
    if ($cmd) { return Split-Path $cmd.Source }
    $found = Get-ChildItem "$env:LOCALAPPDATA\Microsoft\WinGet\Packages" -Recurse `
                -Filter adb.exe -ErrorAction SilentlyContinue |
             Select-Object -First 1 -ExpandProperty FullName
    if ($found) { return Split-Path $found }
    return $null
}

$job = $null
if (-not $NoSync) {
    $adbDir = Resolve-AdbDir
    if ($adbDir) { $env:PATH = "$adbDir;$env:PATH" }

    if (-not (Get-Command adb -ErrorAction SilentlyContinue)) {
        Write-Warning "adb not found -- starting WITHOUT live sync. Install with: winget install Google.PlatformTools"
    }
    else {
        $sync = Join-Path $Root 'devices\xiaomi\sync_gadgetbridge.ps1'
        Write-Host ("Starting watch sync loop (every {0}s) in the background ..." -f $IntervalSeconds) -ForegroundColor Cyan
        $job = Start-Job -Name PawseSync -ScriptBlock {
            param($script, $interval, $path)
            $env:PATH = $path
            & $script -Trigger -Loop -IntervalSeconds $interval
        } -ArgumentList $sync, $IntervalSeconds, $env:PATH
        Write-Host "  (background sync log: Receive-Job -Name PawseSync)" -ForegroundColor DarkGray
    }
}

# Serve the dashboard in the foreground; Ctrl+C stops it.
$env:PAWSE_WEARABLE  = $Wearable
$env:GADGETBRIDGE_DB = $LocalDb
Push-Location $Root
try {
    python server.py
}
finally {
    Pop-Location
    if ($job) {
        Write-Host "Stopping background sync loop ..." -ForegroundColor Cyan
        Stop-Job   $job -ErrorAction SilentlyContinue
        Remove-Job $job -Force -ErrorAction SilentlyContinue
    }
}
