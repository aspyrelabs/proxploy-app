# Step two: the host capability UI

**Date:** 2026-08-13
**Status:** queued, not started. Step one landed as commit `b4bf275`.

Queued. Dispatch only after step one (privilege sweep, diagnostic fix, storage
migration) has landed and been pushed, because it changes the storage shape this
UI reads and writes.

## The framing, stated by the user, which must not get lost

> Its PRIMARY job is the add-a-capability-to-an-enrolled-host flow, not just
> growing the token inputs.

This is the point of the whole piece of work. An earlier agent found it
independently and recorded it as a pre-existing gap:

> no general "add a capability to an already-enrolled host" UI flow exists for
> any capability, not just node power

That is why the four scoped tokens the `pveum` script generates had nowhere to
go. Enrolment takes one token. After enrolment there is no path at all to grant
a capability the host did not get on day one. Growing the inputs on the forms is
the smaller half of the job and must not be mistaken for the whole of it.

## Requirements

1. **`HostEditDialog` lets a user add a capability to an existing host.** Paste
   the token id and secret for that capability, verify it against the node, and
   store it. This is the flow that does not exist today.

2. **It also lets a user remove a capability.** Removing must not be able to
   strip `monitoring`, which is required, and must say what stops working.

3. **Verification before storage.** Rotation already refuses to store an
   unusable credential, because doing so takes the host offline with no way back
   except editing the database. The same property must hold per capability.

4. **A capability-satisfied readout**, driven by what `GET /hosts/{id}` already
   returns. The user should be able to see at a glance which capabilities the
   host has and which are missing, rather than discovering it when a feature
   fails.

5. **`HostForm` and `HostRotateDialog` grow to one token pair per ticked
   capability.** This is the smaller half.

6. **Node power stays a typed-confirmation action with no toggle.** The
   confirmation naming the node is a stronger gate than a boolean, and the
   node-power agent recommended against a per host switch. Node shell keeps its
   existing checkbox in Settings, in the card titled "Hosts", unchanged and not
   duplicated.

## Constraints carried forward

- No em dashes anywhere.
- Plain forms, not a wizard. This product favours plain forms.
- No hardcoded colours. Light theme is real.
- Do not kill ports 8000 or 5173, and do not run Playwright.
- The node shell toggle already exists in Settings. Do not add a second one.
  If discoverability is the real problem, that is a separate change.

## Source material

- `.superpowers/sdd/per-capability-tokens-plan.md`, the investigation.
- `.superpowers/sdd/node-power-privilege-report.md`, and commit `4a16ac7`.
- Step one's own report, once it lands.
