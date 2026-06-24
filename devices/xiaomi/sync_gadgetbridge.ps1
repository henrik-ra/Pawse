<#
.SYNOPSIS
    Pull the latest Gadgetbridge database from the phone and refresh Pawse.

.DESCRIPTION
    Uses ADB (USB or wireless) to (optionally) trigger a watch sync + database
    export on the phone via Gadgetbridge's Intent API, then copies the exported
    database to this laptop and points Pawse at it. Designed to be run by hand or
    on a schedule (Windows Task Scheduler) so the dashboard always has fresh
    Xiaomi Watch data with no manual taps or file copying.

    Prerequisites:
      * Android platform-tools (adb) on PATH  -> winget install Google.PlatformTools
      * USB debugging enabled on the phone (Developer options), OR wireless adb.
      * For -Trigger (fully hands-free), enable in Gadgetbridge:
          Settings -> Developer options -> Intent API:
            * "Allow activity sync trigger"  (Activity sync)
            * "Allow database export"        (Auto export database)
        Without -Trigger, just make sure you tapped "Export Data" (or have
        auto-export on) so a recent DB file exists on the phone to pull.

.PARAMETER Date
    Day to summarise after pulling (yyyy-MM-dd). Defaults to today.

.PARAMETER Wireless
    "host:port" for wireless adb (e.g. 192.168.1.50:5555). If set, the script
    runs `adb connect` first. Omit when using a USB cable.

.PARAMETER Trigger
    Before pulling, broadcast Gadgetbridge intents to sync the watch and export
    the DB (requires the two Intent API toggles above). Makes the run fully
    hands-free.

.PARAMETER NoRun
    Only pull the DB; skip running the Pawse client.

.PARAMETER Loop
    Keep syncing continuously for near-real-time monitoring. Repeats every
    -IntervalSeconds until you press Ctrl+C. Best combined with -Trigger.

.PARAMETER IntervalSeconds
    Seconds between iterations in -Loop mode (default 120). The practical floor
    is ~60-90s: the watch only stores HR about once a minute and each sync +
    pull takes a few seconds. Lower values mainly cost battery, not freshness.

.EXAMPLE
    ./sync_gadgetbridge.ps1 -Trigger
    ./sync_gadgetbridge.ps1 -Wireless 192.168.1.50:5555 -Trigger
    ./sync_gadgetbridge.ps1 -Trigger -Loop -IntervalSeconds 90   # near real-time
    ./sync_gadgetbridge.ps1 -Date 2026-06-24 -NoRun
#>
[CmdletBinding()]
param(
    [string]$Date = (Get-Date -Format 'yyyy-MM-dd'),
    [string]$Wireless,
    [switch]$Trigger,
    [switch]$NoRun,
    [switch]$Loop,
    [int]$IntervalSeconds = 120
)

$ErrorActionPreference = 'Stop'

# --- config ------------------------------------------------------------------
# The plain "Export Data" action writes a file literally named "Gadgetbridge"
# (no extension) into the app's external files dir.
$Pkg       = 'nodomain.freeyourgadget.gadgetbridge'
$RemoteDb  = "/storage/emulated/0/Android/data/$Pkg/files/Gadgetbridge"
$LocalDir  = Join-Path $env:USERPROFILE 'Pawse\data\gadgetbridge-db'
$LocalDb   = Join-Path $LocalDir 'Gadgetbridge.db'
$RepoRoot  = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
# -----------------------------------------------------------------------------

function Assert-Adb {
    if (-not (Get-Command adb -ErrorAction SilentlyContinue)) {
        throw "adb not found on PATH. Install with: winget install Google.PlatformTools"
    }
}

function Invoke-Sync {
    if ($Trigger) {
        Write-Host "Triggering watch sync via Gadgetbridge Intent API ..." -ForegroundColor Cyan
        adb shell am broadcast -a "$Pkg.command.ACTIVITY_SYNC" -p $Pkg | Out-Host
        # Give the watch time to hand its samples to Gadgetbridge before exporting.
        Start-Sleep -Seconds 15

        Write-Host "Triggering database export ..." -ForegroundColor Cyan
        adb shell am broadcast -a "$Pkg.command.TRIGGER_EXPORT" -p $Pkg | Out-Host
        # Export is quick, but give it a moment to finish writing the file.
        Start-Sleep -Seconds 4
    }

    Write-Host "Pulling Gadgetbridge DB from phone ..." -ForegroundColor Cyan
    # Make sure the destination folder exists before pulling.
    if (-not (Test-Path $LocalDir)) {
        New-Item -ItemType Directory -Path $LocalDir -Force | Out-Null
    }
    # adb pull overwrites the destination; pull to a temp file first so a failed
    # transfer never corrupts the last-good DB.
    $tmp = "$LocalDb.tmp"
    adb pull $RemoteDb $tmp | Out-Host

    if (-not (Test-Path $tmp)) {
        throw "Pull failed. Check that Gadgetbridge auto-export is ON and the file exists at:`n  $RemoteDb"
    }

    Move-Item -Force $tmp $LocalDb
    $size = (Get-Item $LocalDb).Length
    Write-Host ("Saved {0} ({1:N0} bytes)" -f $LocalDb, $size) -ForegroundColor Green

    if ($NoRun) { return }

    # --- refresh Pawse -------------------------------------------------------
    $env:GADGETBRIDGE_DB = $LocalDb
    Push-Location $RepoRoot
    try {
        Write-Host "Today's Xiaomi Watch signals:" -ForegroundColor Cyan
        python devices/xiaomi/gadgetbridge_client.py $Date | Out-Host
    }
    finally {
        Pop-Location
    }
}

Assert-Adb

if ($Wireless) {
    Write-Host "Connecting to $Wireless ..." -ForegroundColor Cyan
    adb connect $Wireless | Out-Host
}

# Make sure exactly one device is reachable.
$devices = (adb devices) | Select-String -Pattern '\tdevice$'
if (-not $devices) {
    throw "No authorised adb device. Plug in via USB (allow the prompt) or use -Wireless host:port."
}

if ($Loop) {
    Write-Host ("Continuous sync every {0}s. Press Ctrl+C to stop." -f $IntervalSeconds) -ForegroundColor Yellow
    while ($true) {
        try {
            Invoke-Sync
        }
        catch {
            # Don't let a transient adb/sync hiccup kill the whole loop.
            Write-Host ("Sync iteration failed: {0}" -f $_.Exception.Message) -ForegroundColor Red
        }
        Write-Host ("--- next sync in {0}s ---`n" -f $IntervalSeconds) -ForegroundColor DarkGray
        Start-Sleep -Seconds $IntervalSeconds
    }
}
else {
    Invoke-Sync
}
