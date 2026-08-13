# Capturing all four capability tokens

Date: 2026-08-13
Status: approved, ready for an implementation plan

## The problem

The onboarding script provisions a token per capability the operator selected.
`services/pveum.py` defines four: `monitoring` (required), `lifecycle`,
`console`, `backup`. The script prints all of them.

The UI has one box. `api/hosts.py:298` stores only `api_token:monitoring` on
create, and nothing in `frontend/src` calls the capability route at all
(`grep capability frontend/src` returns only comments in `HostForm.tsx`). So an
operator runs the script, gets four tokens, and has nowhere to put three of
them. The docs say to add them in settings; settings has no such control.

## What already exists, and does not need building

`POST /hosts/{host_id}/credentials` (`api/hosts.py:906`) already:

- takes a `capability` field, defaulted to `monitoring`
- validates it against `CAPABILITIES` in a `field_validator`, so the list cannot
  drift from `services/pveum.py`
- **verifies the token against the node before storing it**, via a real
  `ProxmoxClient(...).version()` call
- on rejection raises a 502 `token_rejected` naming the address, explicitly
  leaving the previous credential in place
- upserts `api_token:{capability}`, creating the row or replacing the blob

This spec builds a UI for a route that is already correct. Do not reimplement
its verification.

## The one backend addition

`GET /hosts` and `GET /hosts/{id}` gain per-capability credential state, derived
from which `api_token:{capability}` rows exist for that host.

**Presence only. Never the token, never the token id, never any part of the
encrypted blob.** The UI needs to know whether a capability is configured, and
nothing more. A shape like:

```json
"capabilities": { "monitoring": true, "lifecycle": true,
                  "console": false, "backup": false }
```

Key off `CAPABILITIES` so a capability added to `services/pveum.py` appears here
without a second list to maintain. A host with no credential rows at all reports
every capability false rather than omitting the field, so the UI never has to
distinguish "absent" from "unknown".

## Onboarding: create, then one call per capability

The form shows a field per capability the operator selected for the script.
On submit:

1. Create the host with the monitoring token, exactly as today.
2. For each additional capability with a token, `POST /hosts/{id}/credentials`.

Each token is verified against the node individually, and a rejection names the
capability it belongs to.

### Partial failure is a real state, and must not read as total failure

This sequence can leave a host created with some tokens stored and one rejected.
That is the accepted cost of reusing the existing route rather than duplicating
its verification, and the flow must handle it honestly:

- The host **exists and works** for the capabilities that verified. Do not roll
  it back, and do not present the screen as a failed onboarding.
- Show which capability was rejected, with the reason from the route's
  `token_rejected` detail.
- Let that one capability be retried inline, without redoing the ones that
  already succeeded.
- Monitoring is the exception: if the create call itself fails, no host exists
  and nothing else runs. That is unchanged from today.

## Host add and edit: all four, always visible

A capability list showing every capability in `CAPABILITIES` with its state:
stored, or missing.

- **Missing**: an inline field to paste the token, submitting to the same
  credentials route.
- **Stored**: a rotate control, which is what the route already does on an
  existing row.

`monitoring` is special-cased. It is `required=True` in `CAPABILITIES` and the
host cannot exist without it, so it renders as rotate-only and is never
presented as removable or missing.

Showing every capability rather than only the missing ones is deliberate: a
capability with no token fails at the moment the operator tries to use the
feature, far from any explanation. Listing all four makes the gap visible before
it becomes a confusing failure.

## What this does not do

- It does not provision anything. The script on the operator's node generates
  the tokens; this captures what the script printed.
- It does not add a capability, change what any capability grants, or touch
  `services/pveum.py`'s definitions.
- It does not remove a stored credential. Rotation replaces; there is no delete
  in this scope.
- It does not change the SSH key path, which is separate from API tokens and
  already has its own handling.

## Testing

- Per-capability state serializes correctly with zero, some, and all tokens
  present, and reports false rather than omitting for a host with none.
- The serialized state contains no token id, no secret, and no blob.
- A rejected token on one capability leaves the other capabilities' credentials
  stored and the host intact.
- The rejection surfaces to the UI with the capability named, not a bare 502.
- `monitoring` cannot be presented as missing or removable.
- A capability added to `CAPABILITIES` appears in the serialized state and in
  the UI list without a second list being edited.
- Onboarding with only monitoring selected behaves exactly as it does today.

## Unchanged constraints

- Proxploy never sees or asks for root credentials.
- Tokens are encrypted at rest through `SecretStore`, as the existing route
  already does.
- The capability list has one definition, `services/pveum.py::CAPABILITIES`.
