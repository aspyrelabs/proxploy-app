"""The ONLY app→Aspyre call path: activate / refresh / revoke.
Never called unless a license is configured."""
import logging

import httpx

# httpx logs every request at INFO as `HTTP Request: POST <full url> "..."`, and
# that URL is rendered with its userinfo intact: so an api_base_url carrying
# basic-auth credentials (an ordinary self-hosted reverse-proxy setup) puts the
# password on the root logger. Exactly the urllib3 case handled in
# services/notifier.py. httpcore's own DEBUG tree logs only host/port and
# `<Request [b'POST']>`: no URL, no headers, no body; so it is left alone.
logging.getLogger("httpx").propagate = False


class LicenseApiError(RuntimeError):
    pass


class SeatOccupied(LicenseApiError):
    """The licence is live on another installation.

    A subclass so every existing `except LicenseApiError` keeps catching it:
    a new sibling exception here would escape those handlers as a 500. Carries
    only what the service chose to disclose about the occupant, which is what
    lets the activation UI name the server the owner has to recognise.
    """

    def __init__(self, detail: dict):
        super().__init__(detail.get("error", "license already active"))
        self.detail = detail


class LicenseClient:
    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")

    def _post(self, path: str, payload: dict) -> dict:
        try:
            r = httpx.post(f"{self.base_url}{path}", json=payload, timeout=10)
        except httpx.HTTPError as e:
            raise LicenseApiError(str(e)) from e
        if r.status_code >= 400:
            # The remote body is NOT relayed. `refresh()` sends a credential the
            # caller never sees (decrypted from license.refresh_credential.enc),
            # and a licensing API that names the offending value in its error, 
            # ordinary REST behaviour: would land it verbatim in the HTTP 502
            # `detail` that api/entitlements.py builds from this message. Status
            # and path are the whole diagnostic we are entitled to echo.
            # The 409 body is the exception: it carries only the occupant
            # summary the service chose to disclose (installation name, last
            # seen), never a credential, and the activation UI cannot explain
            # itself without it.
            if r.status_code == 409:
                try:
                    detail = r.json().get("detail")
                except ValueError:
                    detail = None
                if isinstance(detail, dict):
                    raise SeatOccupied(detail)
            raise LicenseApiError(f"{path} -> HTTP {r.status_code}")
        return r.json()

    def activate(self, license_key: str, install_id: str,
                 fingerprint: list[str] | None = None) -> dict:
        return self._post("/v1/licenses/activate",
                          {"license_key": license_key, "install_id": install_id,
                           "fingerprint": fingerprint})

    def transfer(self, license_key: str, install_id: str, recovery_code: str,
                 fingerprint: list[str] | None = None) -> dict:
        return self._post("/v1/licenses/transfer",
                          {"license_key": license_key, "install_id": install_id,
                           "recovery_code": recovery_code, "fingerprint": fingerprint})

    def release(self, refresh_credential: str, install_id: str) -> dict:
        return self._post("/v1/licenses/release",
                          {"refresh_credential": refresh_credential,
                           "install_id": install_id})

    def refresh(self, refresh_credential: str, install_id: str,
                fingerprint: list[str] | None = None,
                heartbeat_seq: int | None = None) -> dict:
        return self._post("/v1/entitlements/refresh",
                          {"refresh_credential": refresh_credential,
                           "install_id": install_id, "fingerprint": fingerprint,
                           "heartbeat_seq": heartbeat_seq})

    def activations(self, refresh_credential: str, install_id: str) -> dict:
        return self._post("/v1/licenses/activations",
                          {"refresh_credential": refresh_credential,
                           "install_id": install_id})

    def revoke(self, refresh_credential: str, install_id: str) -> dict:
        return self._post("/v1/licenses/revoke",
                          {"refresh_credential": refresh_credential, "install_id": install_id})
