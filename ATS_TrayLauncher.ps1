# ATS Xeon Stealth Tray Launcher (Mission Control)
# This script runs the ATS Xeon engine in the background and provides a System Tray menu.

Add-Type -AssemblyName System.Windows.Forms, System.Drawing

# --- Configuration (Dynamically calculate root based on script location) ---
$ATS_ROOT = Split-Path -Parent $MyInvocation.MyCommand.Path
if (-not $ATS_ROOT) { $ATS_ROOT = Get-Location } # Fallback
$ATS_EXE = "$ATS_ROOT\ATS_Xeon.exe"
$ATS_LOG = "$ATS_ROOT\log"
$ATS_URL = "http://localhost:8080"
$ICON_PATH = "$ATS_ROOT\myicon.ico"

# --- State ---
$Global:Process = $null

function Start-Engine {
    if ($Global:Process -and -not $Global:Process.HasExited) {
        return
    }
    Write-Host "Starting ATS Xeon Engine..."
    $Global:Process = Start-Process -FilePath $ATS_EXE -WindowStyle Hidden -PassThru
}

function Stop-Engine {
    Write-Host "Forcing all ATS Xeon processes to stop..."
    # Kill by name to ensure no background orphans remain
    Get-Process "ATS_Xeon" -ErrorAction SilentlyContinue | Stop-Process -Force
}

# --- Tray Icon Setup ---
$NotifyIcon = New-Object System.Windows.Forms.NotifyIcon
if (Test-Path $ICON_PATH) {
    $NotifyIcon.Icon = New-Object System.Drawing.Icon($ICON_PATH)
} else {
    $NotifyIcon.Icon = [System.Drawing.Icon]::ExtractAssociatedIcon($ATS_EXE)
}
$NotifyIcon.Text = "ATS Xeon Mission Control"
$NotifyIcon.Visible = $true

# Double click action
$NotifyIcon.add_DoubleClick({
    Start-Process $ATS_URL
})

# Context Menu
$ContextMenu = New-Object System.Windows.Forms.ContextMenu
$MenuOpen = $ContextMenu.MenuItems.Add("Open Dashboard")
$MenuOpen.add_Click({ Start-Process $ATS_URL })

$MenuLogs = $ContextMenu.MenuItems.Add("View Logs Folder")
$MenuLogs.add_Click({ Start-Process "explorer.exe" $ATS_LOG })

$ContextMenu.MenuItems.Add("-") # Separator

$MenuRestart = $ContextMenu.MenuItems.Add("Restart Engine")
$MenuRestart.add_Click({ 
    Stop-Engine
    Start-Engine
})

$MenuExit = $ContextMenu.MenuItems.Add("Exit ALL (Stop Engine)")
$MenuExit.add_Click({
    Stop-Engine
    $NotifyIcon.Visible = $false
    [System.Windows.Forms.Application]::Exit()
    exit
})

$NotifyIcon.ContextMenu = $ContextMenu

# --- Watchdog Loop ---
Start-Engine

# We use a timer to check the process status instead of a blocking loop 
# so the UI thread (Tray Icon) stays responsive.
$Timer = New-Object System.Windows.Forms.Timer
$Timer.Interval = 5000 # Check every 5 seconds
$Timer.add_Tick({
    if ($Global:Process -and $Global:Process.HasExited) {
        if ($Global:Process.ExitCode -eq 99) {
            # Dashboard requested full shutdown
            $NotifyIcon.Visible = $false
            [System.Windows.Forms.Application]::Exit()
            exit
        }
        Write-Host "Engine exited/crashed. Restarting..."
        Start-Engine
    }
})
$Timer.Start()

# Run the UI Message Loop
[System.Windows.Forms.Application]::Run()
