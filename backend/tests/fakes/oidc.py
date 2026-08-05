"""In-process mock OIDC provider. HONEST SUBSTITUTE (doc 10 DoD says "a real
Authelia"; there is no browser, no Authelia, and no live IdP on this machine):
this serves a real discovery document, enforces PKCE S256 end-to-end
(challenge stored at /authorize, verifier checked at /token), and signs real
RS256 ID tokens verified by the app against this fixture's real /jwks — the
protocol is fully exercised; only the third-party implementation is absent."""
import base64
import hashlib
import secrets

from fastapi import FastAPI, HTTPException, Request
from joserfc import jwt
from joserfc.jwk import RSAKey

ISSUER = "https://idp.test"


def make_idp(*, sub="alice-1", email="alice@example.com", name="Alice",
             client_id="proxploy", client_secret="s3cret"):
    key = RSAKey.generate_key(2048, {"alg": "RS256", "kid": "test-1"})
    codes: dict[str, dict] = {}   # code -> {nonce, code_challenge}
    idp = FastAPI()
    idp.state.key = key           # mutable: tests reassign this to sign with a
                                   # key the app's cached JWKS doesn't have, to
                                   # prove signature verification isn't skipped

    @idp.get("/.well-known/openid-configuration")
    def discovery():
        return {"issuer": ISSUER,
                "authorization_endpoint": f"{ISSUER}/authorize",
                "token_endpoint": f"{ISSUER}/token",
                "jwks_uri": f"{ISSUER}/jwks",
                "id_token_signing_alg_values_supported": ["RS256"]}

    @idp.get("/jwks")
    def jwks():
        return {"keys": [idp.state.key.as_dict(private=False)]}

    @idp.get("/authorize")
    def authorize(state: str, nonce: str, code_challenge: str,
                  code_challenge_method: str, redirect_uri: str,
                  client_id_q: str | None = None):
        assert code_challenge_method == "S256"
        code = secrets.token_urlsafe(16)
        codes[code] = {"nonce": nonce, "challenge": code_challenge}
        return {"redirect": f"{redirect_uri}?state={state}&code={code}"}

    # FastAPI's Form(...) rejects unknown fields once any field is declared via
    # Form(), so this reads the raw form body instead of declaring `client_id`/
    # `client_secret`/`redirect_uri` params for the extra fields Authlib sends.
    @idp.post("/token")
    async def token(request: Request):
        body = await request.form()
        code = body.get("code")
        code_verifier = body.get("code_verifier")
        entry = codes.pop(code, None) if code else None
        if entry is None:
            raise HTTPException(400, "bad code")
        digest = hashlib.sha256(code_verifier.encode()).digest()
        if base64.urlsafe_b64encode(digest).rstrip(b"=").decode() != entry["challenge"]:
            raise HTTPException(400, "PKCE verifier mismatch")
        id_token = jwt.encode(
            {"alg": "RS256", "kid": "test-1"},
            {"iss": ISSUER, "aud": client_id, "sub": sub, "email": email,
             "name": name, "nonce": entry["nonce"], "exp": 9999999999},
            idp.state.key)
        return {"access_token": "at", "token_type": "Bearer",
                "id_token": id_token}

    idp.state.codes = codes
    return idp
