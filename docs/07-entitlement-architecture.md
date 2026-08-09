# Proxploy: Entitlement Architecture (day-0, dormant)

Status: planning. Governed by `00-decision-brief.md` §5 (Entitlements row) and
§7; this doc elaborates, never contradicts. Doc 09 references §9 of this doc
as the shared app↔api contract.

## 1. What this layer is and is not

Entitlements are a **licensing** mechanism, not an ops feature-flag system.
The problem is offline-verifiable "is this install allowed to use feature X,"
not gradual rollouts, which is why Unleash/Flagsmith were rejected in the
brief. The entire layer ships in the first commit and stays **dormant**:
every flag resolves to *on* for everyone until Aspyre decides to sell tiers.
Arming is a config change on proxploy-api. It is never a refactor, because
every feature is already wrapped.

We also accept, per brief §11, that self-hosted code can be patched around
any gate. The moat is hosted-signed tokens plus honesty, not DRM. Nothing in
this design pretends otherwise.

## 2. The in-app Entitlements service

One service, OpenFeature-shaped so the mental model (and any future migration
to a real OpenFeature provider) is free:

```python
class Entitlements:
    def enabled(self, key: str) -> bool: ...        # the whole hot-path API
    def snapshot(self) -> dict[str, bool]: ...      # resolved map for the SPA
    def status(self) -> EntitlementStatus: ...      # tier, source, expiry, grace state
```

Resolution order inside `enabled(key)`:

1. **Licensed install:** the disk-cached entitlement token (validated per §5)
   → `features` claim → key lookup. Unknown key → `False` (fail closed for
   keys the token doesn't know; a token minted before a feature existed
   should not silently grant it).
2. **No license configured:** the **built-in default feature map** (§6), 
   a static dict shipped in the app package. Unknown key → `False` here too,
   which makes a missing map entry a loud dev-time bug rather than a silent
   grant.

The result is memoized per process and recomputed only when the token
changes; `enabled()` is a dict lookup, never I/O, safe to call on every
request.

### Backend enforcement

One FastAPI dependency, used on every gated route:

```python
def require_entitlement(key: str):
    def dep(ent: Entitlements = Depends(get_entitlements)):
        if not ent.enabled(key):
            raise HTTPException(403, {"error": "entitlement_required", "feature": key})
    return Depends(dep)

@router.post("/api/v1/catalog/{slug}/install",
             dependencies=[require_entitlement("store.install")])
async def install_app(...): ...
```

Non-route call sites (scheduler-triggered jobs, notification dispatch) call
`entitlements.enabled(key)` directly and skip/deny with the same audit trail.

### Frontend flag map

`GET /api/v1/entitlements` returns the resolved snapshot:

```json
{
  "tier": "free",
  "features": {"hosts.multi": true, "apps.console": true, "...": true},
  "grace": null
}
```

The SPA fetches it once at boot (TanStack Query, refetched on
window-focus/interval), and a `useEntitlements()` hook (doc 06 §(e)) drives
hide-or-veil decisions in the UI. This is **cosmetic only**: the server re-enforces every
gated endpoint via the dependency above, so a hand-edited flag map buys a
prettier button and a 403.

## 3. Flag key convention and day-0 wrapping

Keys are dotted, namespaced by domain, one flag per feature; the full
catalogue lives in doc 01 alongside the feature list it mirrors. From the
brief: `hosts.multi`, `apps.lifecycle`, `apps.console`, `store.install`,
`store.auto_update`, `vms.console`, `migrate.cross_host`, `backups.pbs`,
`alerts.rules`, `auth.oidc`, `teams.rbac`, `api.tokens`, and so on.

Rules, enforced in review from the first commit:

- Every new user-facing feature lands **with** its flag key: registered in
  the built-in default map, gated by `require_entitlement` on its routes, and
  checked by `useEntitlement` in its UI entry points. A feature without a key
  does not merge.
- Keys are `domain.feature`, lowercase, no versions in the key. A feature's
  key never changes once shipped (tokens in the field reference it).
- Coarse over fine: one key per sellable feature, not per endpoint. If we
  can't imagine ever selling it separately, it shares its domain's key.

Because the default map is *all on*, this discipline costs nothing at runtime
and no user ever sees a gate during the dormant phase, but the day tiers are
armed, the map on proxploy-api is the only thing that changes.

## 4. proxploy-api: the hosted half

A separate, Aspyre-hosted FastAPI service (brief §6). **Never bundled** with
the app; never called unless a license is configured. It has exactly three
licensing endpoints on this path (plus an operational health check) and
carries **no analytics or telemetry**, the request bodies contain a license
key/id and nothing about the install's contents.

| Endpoint | Purpose |
|---|---|
| `POST /v1/licenses/activate` | License key in → first entitlement token + a per-install refresh credential out. Called once, when the user enters a key. |
| `POST /v1/entitlements/refresh` | Refresh credential in → fresh entitlement token out. Called in the background well before `exp`; see the Lifecycle note below for what actually drives it. |
| `POST /v1/licenses/revoke` | Deactivates this install's refresh credential (user moved the license, refund, etc.). Subsequent refreshes fail; the app falls back per the failure matrix. |
| `GET /v1/health` | Operational liveness for Aspyre's own monitoring. The app never depends on it. |

The **tier→features mapping** lives on proxploy-api as a config artifact
(a static file/table mapping tier names to feature maps). During dormancy it
contains one rule, every tier resolves to all-entitled, and is filled in
only when Aspyre decides to sell. That file is the "arming switch."

### Signing key custody (launch-critical even while dormant)

The Ed25519 **private** signing key is not deferrable to "when we sell": a
lost or leaked key means re-releasing the app. It lives in a KMS (preferred)
or a root-only file on proxploy-api infrastructure, with an **offline
encrypted backup** kept outside the serving environment (doc 09), losing it
without a backup makes every issued token unrecoverable and forces every
install through re-activation. A documented **rotation runbook** covers both
routine rotation and leak response: mint a new Ed25519 keypair, publish its
public half in the next proxploy-app release's bundled key **set** (the app
already carries a `kid`-keyed set of valid public keys, not a single key; 
§5, §9), sign new tokens with the new `kid` while the old key remains valid
for verification through its `grace_until` horizon, then retire the old key.
Because the app must ship a release to learn a new public key, rotation
always **survives** an app release by construction, which is exactly why
the multi-`kid` set is built into the app from **Phase 1** (doc 10), not
bolted on the day rotation is first needed.

**Amendment, 2026-08-08 (PXP-14, root-signed leaf certificates):** the
single hosted signing key described above is superseded by a two-key,
root-signed-leaf model (§5 below, doc 09 SHARED CONTRACT). proxploy-api now
holds a short-lived **leaf** Ed25519 signing key, the key that actually
signs entitlement tokens, plus a certificate for that leaf key signed by an
offline **root** Ed25519 key. The root private key never touches the API
host: it lives offline, is used only to sign new leaf certificates, and
signs nothing else, it is not part of the API's runtime attack surface at
all. The leaf private key lives on proxploy-api infrastructure the way the
old single key did (KMS preferred, root-only file fallback, offline
encrypted backup), but rotates far more often, since a leaked leaf key
costs only that key's certificate validity window, not a full app release.
The app no longer bundles a `kid`-keyed set of entitlement signing public
keys at all; it bundles root public key(s) only, and trusts a leaf key
solely because a certificate signed by a bundled root vouches for it.
Rotation and revocation both move from "ship a new app release" to "mint,
or let expire, a certificate," which is the point: certificate `exp` is
what makes revocation work on installs that never update again (§5, §8).

### License and issued-token data model (defined now, not deferred)

Two tables live in proxploy-api's own schema (SQLAlchemy + Alembic, doc 09
`models/`), created in **Phase 1** alongside the dormant resolver, even
though no license is sold yet:

**`licenses`**: one row per issued license key.

| Column | Type | Notes |
|---|---|---|
| id | int PK | |
| license_key | text | unique index; the value a user enters in Proxploy |
| tier | text | `free` \| `pro` \| … ; inert value while dormant |
| install_id | text | NULL until the first `activate` call binds it to one install |
| refresh_credential_hash | text | hash of the per-install refresh credential; NULL until activated |
| status | text | `active` \| `revoked` |
| issued_at / revoked_at | datetime | |
| created_at / updated_at | datetime | |

**`issued_tokens`**: append-only log of every signed entitlement token,
for audit and revocation support.

| Column | Type | Notes |
|---|---|---|
| id | int PK (BIGINT) | |
| license_id | int FK → licenses | |
| kid | text | which signing key issued this token |
| jti | text | token id, unique index; lets one token be recognized in support/abuse investigations |
| issued_at / expires_at / grace_until | datetime | mirrors the token's own claims |
| created_at | datetime | |

Neither table is exposed to proxploy-app; both exist purely on the hosted
side so licensing has a real data model from day one instead of being
bolted on at sale time.

## 5. The entitlement token (exactly per brief §7)

- **Format:** JWT, signed **EdDSA/Ed25519**. Signing via PyJWT on
  proxploy-api (Aspyre private key, never leaves Aspyre); verification via
  PyJWT in the app with the **public key bundled** in the app package. No
  hand-rolled crypto; no shared secrets; no HMAC (a bundled HMAC secret would
  be extractable and forgeable, asymmetric or nothing).
- **Claims:**

| Claim | Meaning |
|---|---|
| `sub` | License id |
| `tier` | Tier name (informational; `features` is authoritative) |
| `features` | Map of flag key → bool, the resolved entitlement set |
| `iat` | Issued at |
| `exp` | ~72 h after issue, forces regular background refresh |
| `grace_until` | ~30 d after issue, offline validity horizon |

- **Lifecycle:** the app refreshes in the background, caches
  the token **on disk** (the `entitlement_cache` row, encrypted at rest via
  SecretStore, docs 04, 08), and validates **offline**; signature via the bundled public key, then
  the time window. Between `exp` and `grace_until` the token is expired but
  still honored; past `grace_until` it is dead. A transient network failure
  therefore never locks a paying user out: they have ~30 days of fully
  offline operation from the last successful refresh.

  **Amendment, 2026-08-08 (audit follow-up, PXP-19):** this said the refresh
  was "an APScheduler job, starting at ~half of the `exp` window with jittered
  retry/backoff". None of that is what shipped. `main.py`'s lifespan starts a
  plain `asyncio` task (`_refresh_loop`) that sleeps ~24h plus up to 10
  minutes of jitter and retries on the next tick; APScheduler is not involved
  anywhere on this path, and the app's scheduler does not own it either. With
  `exp` at 72h, ~24h is roughly a third of the window rather than half, which
  is more headroom, not less: two refreshes can fail before a token expires.
  There is no backoff, a failed attempt simply waits out the next full
  interval, which is the right shape when the fallback is a 30-day grace
  window rather than an outage. The task is only started when a licence is
  actually present.
- **Verification is local and pure:** no call to proxploy-api is ever needed
  to *check* a token, only to *obtain* one.

  **Amendment, 2026-08-08 (PXP-14, root-signed leaf certificates):** "the
  public key bundled in the app package" above described direct trust: the
  app held a `kid`-keyed dict of valid entitlement-signing public keys and
  checked a token's signature against one of them. That model is
  superseded. Verification is now a **chain**, entitlement token → leaf key
  → certificate → bundled root public key:

  1. Read the entitlement token's header `kid` (a leaf key id).
  2. Read the certificate issued alongside the token (a separate JWT; doc 09
     SHARED CONTRACT, cert claims table). Its header `kid` names a **root**
     key id; look that up in the app's small bundled set of root public
     keys. An unrecognized root `kid` fails closed.
  3. Verify the certificate's own EdDSA signature against that root public
     key, and its `nbf`/`exp` claims. `nbf`/`exp`, not custom
     `not_before`/`not_after` names, so PyJWT validates them natively with a
     bounded `leeway`, raising distinct `ImmatureSignatureError` /
     `ExpiredSignatureError`.
  4. Confirm the certificate's claims `kid` equals the entitlement token's
     header `kid`. A valid certificate for a different leaf key does not
     vouch for this token.
  5. Take the leaf public key from the certificate's `pub` claim (bare
     base64 SPKI body, the same convention as `BUNDLED_PUBLIC_KEYS` and
     `proxploy/pubkey.py::load_public_key`) and verify the entitlement
     token's signature against it.
  6. Only then apply the token's own `exp`/`grace_until` handling, as
     before.

  The app's bundled key set shrinks to root public keys only; it never
  bundles or directly trusts a leaf key. This is what makes both rotation
  (mint a new leaf key and certificate, no app release) and revocation (let
  a certificate lapse, or simply stop minting new ones for a compromised
  leaf) possible without shipping a release, closing the gap the day-0
  design in §4 left open.

  **Offline horizon, amended:** because the certificate itself carries an
  `exp`, the cached-token offline horizon described above is no longer
  `grace_until` alone. A cached token is honored offline only until
  `min(grace_until, cert.exp + leeway)`. This is deliberate, not a bug: it
  is the mechanism that makes a leaf certificate's expiry work as
  revocation, one that holds even on installs that never come back online
  to learn they were revoked, because the bound already lives in what they
  cached (§8).

## 6. The no-license path (free tier, air-gapped)

No license configured → the Entitlements service resolves purely from the
built-in default feature map. **Zero network calls, forever**: the refresh
scheduler job is not even registered, nothing dials proxploy-api, and the app
is fully functional on an air-gapped network. This is a hard product
guarantee, not a degraded mode; the free tier *is* this path.

## 7. Dormant defaults: the three switches that are all "on"

| Layer | Dormant state | Armed state (later, config-only) |
|---|---|---|
| Built-in default map (in-app) | Every key → `true` | Keys above the free tier → `false` (shipped in a normal app release; the *mechanism* doesn't change) |
| proxploy-api resolution | Every license → all-entitled | tier→features config artifact filled in with real tiers |
| Sales/checkout | Nonexistent | proxploy-web sells keys; api activates them |

The invariant: **arming is configuration, never refactor.** All enforcement
code paths, dependency, hook, token verification, grace handling; are live
and exercised from day 0; they just always answer "yes."

**Arming nuance, stated plainly:** "arming is configuration, never refactor"
describes the *tier→features resolution* on proxploy-api (the `tiers.yaml`
swap, §4/doc 09); that step alone is a config deploy, no app release
needed. It does **not** mean no app release is ever needed again: the
free-tier ceiling itself, which keys are `false` for an unlicensed/free
install, lives in the **app's** built-in default map (§6, a static dict
shipped inside the app package), so changing what the free tier gets
requires a normal proxploy-app release even though changing what the paid
tier gets does not. The two maps are deliberately independent: proxploy-api's
map can be edited the day pricing is decided; the app's built-in map only
changes when a release ships.

## 8. Failure matrix

Grace-window behavior means "keep working, tell the truth in the UI."

| Failure | App behavior |
|---|---|
| proxploy-api unreachable, cached token inside `exp` | Nothing changes. Background refresh retries with backoff. No UI noise. |
| Token past `exp` but before `min(grace_until, cert.exp + leeway)` | All features stay enabled from the cached token, its certificate still holds. Non-blocking banner: "License couldn't be refreshed, working offline until <the earlier of grace date and certificate expiry>." Refresh keeps retrying. |
| Past `min(grace_until, cert.exp + leeway)` | Token no longer honored → resolution falls back to the built-in default map (i.e., the free tier; which during dormancy is still everything). Clear banner with a re-activate action. Never a bricked install: the free tier floor always holds. |
| No license ever configured | §6 path. No network, no banners, full free tier. |
| Clock skew | Verification applies a bounded leeway (PyJWT `leeway`, on the order of minutes) to `exp`/`iat`, and to the certificate's `nbf`/`exp` the same way. A wildly wrong clock (days) can push a token past its offline horizon early, the UI surfaces "system clock appears incorrect" when `iat` is in the future beyond leeway, rather than a misleading license error. |
| Signing key rotation | Tokens carry a `kid` header naming a leaf key; the app bundles a small **set** of valid root public keys, never leaf keys directly (§5). Rotation = proxploy-api mints a new leaf key and a fresh certificate for it, signed by the same offline root; no app release needed unless the root itself rotates. Mirrors the MultiFernet pattern used for secrets at rest (doc 08). |
| `revoke` called | Refresh credential dead → refreshes fail → token ages through `exp` → offline horizon → free-tier floor. Revocation is eventually consistent by design (offline validation is the point); the bound is `min(grace_until, cert.exp + leeway)`. |
| Certificate missing (activate/refresh response has no `cert`, or the on-disk cache holds a token with no matching certificate) | Falls down the existing ladder: unusable as a live token → cached token, if its own offline horizon still holds → past that, the built-in default map. A response missing `cert` is a proxploy-api bug (doc 09: `cert` is required, never null), not something the app works around. |
| Certificate malformed (not a valid JWT, wrong `alg`, etc.) | Same ladder: live token unusable → cached token → default map. Logged distinctly from "missing" for support triage. |
| Unknown root `kid` (certificate header names a root key the app doesn't bundle) | Same ladder: fails closed, exactly like an unrecognized `kid` on the entitlement token today. A genuinely rotated root key ships in the next app release (§4's custody amendment). |
| Certificate not yet valid (`nbf` in the future, beyond leeway) | Same ladder. PyJWT raises `ImmatureSignatureError`, treated as a verification failure rather than a lookup miss. |
| Certificate expired (`exp` passed, beyond leeway) | Same ladder, and this is the deliberate revocation path (§5's offline-horizon amendment): once `cert.exp` passes, the entitlement token it vouches for stops being honored even if the token's own `grace_until` has not, so letting one leaf certificate lapse revokes every token it signed, offline, with no server round trip required. |
| Token `kid` does not match certificate claims `kid` | Same ladder: the certificate does not vouch for this particular leaf key, treated as a verification failure. Guards against pairing a valid token with an unrelated, otherwise-valid certificate. |

## 9. Shared app↔api contract (referenced by doc 09)

This section is the contract both repos implement; doc 09 places a copy of the
schema where both can vendor it.

**Token schema** (JWT, EdDSA/Ed25519, header `{"alg": "EdDSA", "kid": "<key id>"}`):

```json
{
  "sub": "lic_01H...",
  "tier": "free | pro | ...",
  "features": {"<flag key>": true},
  "iat": 1690000000,
  "exp": 1690259200,
  "grace_until": 1692592000
}
```

**Endpoints** (proxploy-api, versioned under `/v1`):

| Method + path | Request | Response |
|---|---|---|
| `POST /v1/licenses/activate` | `{license_key, install_id}` | `{token, refresh_credential}` |
| `POST /v1/entitlements/refresh` | `{refresh_credential}` | `{token}` |
| `POST /v1/licenses/revoke` | `{refresh_credential}` | `{revoked: true}` |
| `GET /v1/health` | n/a | `{status: "ok"}` (operational only; the app never depends on it) |

Contract rules: adding claims or endpoints is non-breaking; removing or
renaming either requires a `/v2` and a deprecation window at least as long as
`grace_until`. The app must ignore claims it doesn't know. Nothing beyond
these endpoints may ever be added to the app→api call path without
amending the brief (§6's "no analytics, no telemetry" rule).

**Amendment, 2026-08-08 (PXP-14, root-signed leaf certificates):** the token
schema above is unchanged, but it no longer travels alone, and the endpoint
responses above are superseded. Every entitlement token is now issued
together with a certificate for the leaf key that signed it (§4, §5); doc 09
carries the same update.

**Certificate schema** (JWT, EdDSA/Ed25519, header `{"alg": "EdDSA", "typ":
"JWT", "kid": "<root key id>"}`):

```json
{
  "kid": "<leaf key id>",
  "pub": "<bare base64 SPKI body of the leaf public key>",
  "iat": 1690000000,
  "nbf": 1690000000,
  "exp": 1690259200
}
```

`nbf`/`exp`, not custom `not_before`/`not_after` names, so PyJWT validates
them natively with a `leeway=` argument and raises distinct
`ImmatureSignatureError` / `ExpiredSignatureError`. `pub` is the bare base64
SPKI body, the same convention `BUNDLED_PUBLIC_KEYS` and
`proxploy/pubkey.py::load_public_key` already use.

**Endpoints, superseded** (proxploy-api, versioned under `/v1`):

| Method + path | Request | Response |
|---|---|---|
| `POST /v1/licenses/activate` | `{license_key, install_id}` | `{token, cert, refresh_credential}` |
| `POST /v1/entitlements/refresh` | `{refresh_credential}` | `{token, cert}` |
| `POST /v1/licenses/revoke` | `{refresh_credential}` | `{revoked: true}` |
| `GET /v1/health` | n/a | `{status: "ok"}` (operational only; the app never depends on it) |

`cert` is required in both responses and is never null: every entitlement
token is issued alongside the certificate for the leaf key that signed it,
so the app always has what it needs to verify the chain offline (§5).
