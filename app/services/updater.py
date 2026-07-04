"""Checks GitHub Releases for a newer version. For the Inno Setup-installed copy only,
downloads and silently re-runs the installer to update in place; the loose portable exe
just gets a download link -- self-patching a running standalone exe is riskier and out
of scope here.
"""

import ctypes
import json
import os
import sys
import tempfile
import urllib.request
from datetime import datetime

REPO = "rhybiq/cs2-viewer-sim"
API_LATEST_RELEASE = f"https://api.github.com/repos/{REPO}/releases/latest"

# The update check runs silently in the background of a windowed (no-console)
# app, so a swallowed exception is otherwise completely invisible -- log the
# real reason here instead of just returning None, same reasoning as the
# ffmpeg/Ollama diagnostics fixes.
LOG_PATH = os.path.join(
    os.environ.get("LOCALAPPDATA", tempfile.gettempdir()), "CS2ViewerSim", "update_check.log"
)

# The installer itself requires admin rights (see packaging/installer.iss --
# PrivilegesRequired defaults to "admin"), so if the silent run ever fails
# (e.g. the file copy step hitting a locked exe), this is the only trace of
# why -- Inno Setup's own /LOG output, not just "it didn't work."
INSTALL_LOG_PATH = os.path.join(
    os.environ.get("LOCALAPPDATA", tempfile.gettempdir()), "CS2ViewerSim", "installer.log"
)


def _log_error(context, exc):
    try:
        os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(f"{datetime.now().isoformat()} {context}: {exc!r}\n")
    except Exception:
        pass  # logging must never crash the update check itself


def get_current_version():
    """None when running from source (python run_app.py) -- there's no version to compare."""
    try:
        from app._version import VERSION
        return VERSION
    except ImportError:
        return None


def is_installed_via_setup():
    """True only for the Inno Setup-installed copy (unins000.exe sits next to it) --
    the only case where silent self-update is safe.
    """
    if not getattr(sys, "frozen", False):
        return False
    exe_dir = os.path.dirname(sys.executable)
    return os.path.exists(os.path.join(exe_dir, "unins000.exe"))


def _version_tuple(tag):
    parts = tag.lstrip("v").split(".")
    return tuple(int(p) for p in parts[:3] if p.isdigit())


def get_latest_release(timeout=5):
    """{"tag": str, "installer_url": str|None, "page_url": str} or None on any failure."""
    try:
        req = urllib.request.Request(API_LATEST_RELEASE, headers={"Accept": "application/vnd.github+json"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.loads(r.read().decode())
        installer_url = None
        for asset in data.get("assets", []):
            name = asset.get("name", "")
            if name.startswith("CS2ViewerSim-Setup") and name.endswith(".exe"):
                installer_url = asset.get("browser_download_url")
                break
        return {
            "tag": data.get("tag_name", ""),
            "installer_url": installer_url,
            "page_url": data.get("html_url", ""),
        }
    except Exception as e:
        _log_error("get_latest_release", e)
        return None


def check_for_update():
    """The latest release dict if it's newer than the running version, else None."""
    current = get_current_version()
    if not current:
        return None
    latest = get_latest_release()
    if not latest or not latest.get("tag"):
        return None
    try:
        if _version_tuple(latest["tag"]) > _version_tuple(current):
            return latest
    except Exception:
        pass
    return None


def download_installer(url, timeout=120):
    """Downloads the installer to a temp file and returns its path."""
    fd, path = tempfile.mkstemp(suffix=".exe", prefix="CS2ViewerSim-Setup-")
    os.close(fd)
    req = urllib.request.Request(url, headers={"User-Agent": "cs2-viewer-sim-updater"})
    with urllib.request.urlopen(req, timeout=timeout) as resp, open(path, "wb") as f:
        f.write(resp.read())
    return path


def run_installer_silently(installer_path):
    """Launches the installer (elevated) and detached. Caller should exit the app right after.

    Uses ShellExecuteW with the "runas" verb, not subprocess.Popen: the
    installer's manifest requires admin (PrivilegesRequired=admin in
    installer.iss), and Windows only honors that -- showing the UAC prompt --
    via ShellExecute. subprocess.Popen calls CreateProcess directly, which
    does NOT elevate a requireAdministrator exe; it fails immediately with
    WinError 740 (ERROR_ELEVATION_REQUIRED) instead. That failure was
    previously invisible: it happened inside a Tkinter `.after()` callback in
    a windowed/no-console app, so the exception was silently discarded and
    the installer never actually ran.
    """
    try:
        os.makedirs(os.path.dirname(INSTALL_LOG_PATH), exist_ok=True)
    except Exception:
        pass
    params = f'/VERYSILENT /SUPPRESSMSGBOXES /NORESTART /LOG="{INSTALL_LOG_PATH}"'
    result = ctypes.windll.shell32.ShellExecuteW(None, "runas", installer_path, params, None, 1)
    if result <= 32:
        raise OSError(f"Could not launch the installer (ShellExecute error {result}). "
                      "The elevation prompt may have been declined.")
