"""Update check and install-shape detection.

`check()` never raises: every failure becomes a string the operator can act on
instead of a Settings-page crash.
"""
import json
import os
import shutil
import subprocess
from pathlib import Path
from urllib.request import url2pathname

import httpx

import proxploy
from proxploy.config import Settings
from proxploy.services.release import ReleaseError, is_upgrade, verify_manifest

CAN_SELF_APPLY = {"lxc", "systemd"}
_TIMEOUT = 15.0


def detect_shape(settings: Settings) -> str:
    if settings.install_shape:
        return settings.install_shape
    if os.environ.get("PROXPLOY_IN_DOCKER") or Path("/.dockerenv").exists():
        return "docker"
    return "systemd"


def _pubkey(settings: Settings) -> bytes:
    if settings.release_pubkey_file:
        return Path(settings.release_pubkey_file).read_bytes()
    return (Path(proxploy.__file__).parent / "release_pubkey.pem").read_bytes()


def _fetch(base: str, name: str) -> bytes:
    """file:// for the test harnesses, https:// in production. Nothing else."""
    url = f"{base.rstrip('/')}/{name}"
    if url.startswith("file://"):
        return Path(url2pathname(url[len("file://"):])).read_bytes()
    r = httpx.get(url, timeout=_TIMEOUT, follow_redirects=True)
    r.raise_for_status()
    return r.content


def check(settings: Settings) -> dict:
    out = {"current": proxploy.__version__, "latest": None,
           "update_available": False, "notes_url": None,
           "channel": None, "error": None}
    try:
        raw = _fetch(settings.release_channel_url, "manifest.json")
        sig = _fetch(settings.release_channel_url, "manifest.json.sig")
        manifest = verify_manifest(raw, sig, _pubkey(settings))
    except ReleaseError as e:
        out["error"] = str(e)
        return out
    except Exception as e:                    # network, DNS, permissions, disk
        out["error"] = f"could not reach the release channel: {e}"
        return out
    out["latest"] = manifest["version"]
    out["notes_url"] = manifest.get("notes_url")
    out["channel"] = manifest.get("channel")
    out["update_available"] = is_upgrade(proxploy.__version__, manifest["version"])
    return out


def launch(settings: Settings, version: str) -> None:
    """Hand off to the updater and return immediately.

    Writes the version to a request file that a root owned systemd path unit
    watches (packaging/proxploy-update.path); its wrapper derives the
    channel itself from the installed version, so this process never gets to
    name a channel and a compromised app process can't point a root process
    at a server of its own choosing. That path unit still puts the actual
    update in its OWN unit, outside this process's cgroup, same reason as
    before: the script restarts proxploy.service, and anything living inside
    that cgroup would be killed mid-update, leaving the symlink swapped and
    nothing running.
    """
    settings.update_request_file.write_text(version)


UPDATE_PATH_UNIT = "proxploy-update.path"


def path_unit_active(settings: Settings) -> bool:
    systemctl = shutil.which("systemctl")
    if not systemctl:
        return False
    try:
        result = subprocess.run([systemctl, "is-active", UPDATE_PATH_UNIT],
                                capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.stdout.strip() == "active"


UPDATE_LOG_MAX_LINES = 2000


def read_log(settings: Settings) -> dict:
    updates_dir = Path(settings.data_dir) / "updates"
    status_files = (sorted(updates_dir.glob("*.status"), key=lambda p: p.stat().st_mtime)
                    if updates_dir.is_dir() else [])
    if not status_files:
        return {"state": "none", "version": None, "from": None,
                "updated_at": None, "reason": None, "lines": []}
    status_file = status_files[-1]
    try:
        status = json.loads(status_file.read_text())
    except (OSError, json.JSONDecodeError):
        status = {}
    version = status.get("version")
    log_file = updates_dir / f"{version}.log" if version else status_file.with_suffix(".log")
    lines: list[str] = []
    if log_file.exists():
        lines = log_file.read_text(errors="replace").splitlines()[-UPDATE_LOG_MAX_LINES:]
    return {
        "state": status.get("state", "unknown"),
        "version": version,
        "from": status.get("from"),
        "updated_at": status.get("updated_at"),
        "reason": status.get("reason"),
        "lines": lines,
    }
