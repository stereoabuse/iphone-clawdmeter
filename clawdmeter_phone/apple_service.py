"""Start Apple's USB device service (usbmuxd) without opening iTunes.

The Microsoft Store iTunes only runs AppleMobileDeviceProcess while iTunes is open. Its package
registers iTunesMobileDeviceLauncher.exe as a startup task, and Windows lets us run that launcher
inside the package (Invoke-CommandInDesktopPackage), which starts the service with no window.
"""

import logging
import subprocess
import time

log = logging.getLogger(__name__)
MIN_INTERVAL = 30

_PS = r"""
$p = Get-AppxPackage AppleInc.iTunes | Select-Object -First 1
if (-not $p) { exit 2 }
if (Get-Process AppleMobileDeviceProcess -ErrorAction SilentlyContinue) { exit 0 }
Invoke-CommandInDesktopPackage -PackageFamilyName $p.PackageFamilyName -AppId iTunes `
  -Command (Join-Path $p.InstallLocation 'iTunesMobileDeviceLauncher.exe')
exit 1
"""

_last_try = 0.0


def ensure_running() -> str | None:
    """Try to start the service; returns a short note for the log, or None if skipped."""
    global _last_try
    now = time.time()
    if now - _last_try < MIN_INTERVAL:
        return None
    _last_try = now
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", _PS],
                           capture_output=True, timeout=20, creationflags=subprocess.CREATE_NO_WINDOW)
    except (OSError, subprocess.TimeoutExpired) as e:
        return f"couldn't start Apple's device service: {e!r}"
    return {0: None, 1: "started Apple's device service (no iTunes needed)",
            2: "Store iTunes isn't installed; can't start Apple's device service"}.get(
        r.returncode, f"starting Apple's device service failed (exit {r.returncode})")
