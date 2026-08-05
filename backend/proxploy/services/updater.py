"""Update check and install-shape detection (Phase 9a).

`check()` never raises. A self-hosted box may sit behind a proxy, on an
air-gapped network, or in front of a mirror serving nonsense; none of that is
a reason for the Settings page to fail. Every failure becomes a string the
operator can act on.
"""
import os
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
