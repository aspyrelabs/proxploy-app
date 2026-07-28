"""The ONLY app→Aspyre call path (doc 02 §8): activate / refresh / (revoke later).
Never called unless a license is configured."""
import httpx


class LicenseApiError(RuntimeError):
    pass


class LicenseClient:
    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")

    def _post(self, path: str, payload: dict) -> dict:
        try:
            r = httpx.post(f"{self.base_url}{path}", json=payload, timeout=10)
        except httpx.HTTPError as e:
            raise LicenseApiError(str(e)) from e
        if r.status_code >= 400:
            raise LicenseApiError(f"{path} -> {r.status_code}: {r.text[:200]}")
        return r.json()

    def activate(self, license_key: str, install_id: str) -> dict:
        return self._post("/v1/licenses/activate",
                          {"license_key": license_key, "install_id": install_id})

    def refresh(self, refresh_credential: str) -> dict:
        return self._post("/v1/entitlements/refresh",
                          {"refresh_credential": refresh_credential})
