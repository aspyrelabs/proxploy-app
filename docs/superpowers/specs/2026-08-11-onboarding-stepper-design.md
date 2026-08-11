# Onboarding wizard: reachable steps and a side rail

**Date:** 2026-08-11
**Status:** implemented. Revised twice during implementation, see "Changes made
while building" at the end; those revisions are the authority where this
document's earlier sections disagree.
**Scope:** `frontend/` only. No backend or API changes.

## Problem

Two complaints, one root cause.

1. **There is no way back.** `Wizard`'s local step override is forward-only
   (`frontend/src/routes/onboarding.tsx`, `advanced`/`advance()`), so a typo in
   the admin display name or the host address is uncorrectable without
   finishing setup and hunting through Settings.
2. **The step indicator is a row of chips** across the top of the card, which
   overlaps the wordmark at 1440px and shows no completion state.

The reason back was never built is real, and any fix has to respect it: each
step commits server state as you pass it, and `stepFrom()` derives the current
step from that state. Back cannot mean undo. It has to mean *go edit the thing
that was already created*.

## What the API allows

The narrowness here is deliberate, and this design does not widen it.

| Correction | Endpoint | Available |
|---|---|---|
| Admin display name | `PATCH /users/{id}` | yes |
| Admin password | `POST /users/{id}/password` | yes |
| Admin email | — | **no** (`UserPatchIn` is `is_active` + `display_name`) |
| Host name / address in place | — | **no** (`HostPatchIn` is explicitly not a general update endpoint) |
| Host, wholesale | `DELETE /hosts/{id}` | yes, gated on typing the host name |

So the email is fixed once the account exists, and a mistyped host address is
corrected by removing the host and adding it again.

## Design

### Layout

Two panes replacing the centred 520px card.

- **Left rail, 152px, fixed full height** (`bg-panel`, right border): wordmark,
  a "Setup · N of 4" line, the four steps, and a version footnote. New
  component `frontend/src/components/OnboardingRail.tsx`.
- **Content pane**: centres a ~380px column, each step carrying a heading and
  one line of helper text.
- Below the `md` breakpoint the rail becomes a horizontal strip along the top.

### Step state

`advanced: number | null` is replaced by two distinct ideas:

- **`serverStep`** — `stepFrom(ob)`, unchanged. The first genuinely incomplete
  step, and still the thing that survives a reload.
- **`view`** — which step is rendered. Defaults to `serverStep`. Back is
  `setView(view - 1)`.

A step is reachable, and so clickable in the rail, when it is complete, when it
was skipped, or when it is `serverStep` itself. Status is derived from the
server (`admin_exists`, `host_added`, `!ssh_pending`), never from what the user
clicked, so a green tick always means the server agrees.

`skipped` is session-local state. Skipping is not persisted server-side, so a
reload correctly lands back on the host step. This matches today's behaviour
and is not a regression.

### Per-step back behaviour

| Step | Revisited shows | Calls |
|---|---|---|
| 1 Admin account | Email read-only, with a note that it is fixed once created. Display name editable. "Set a new password". | `PATCH /users/{id}`, `POST /users/{id}/password` |
| 2 First host | Host summary and **Remove and re-add** | `HostRemoveDialog` → `DELETE /hosts/{id}` |
| 3 Authorize installs | Unchanged; already re-runnable | `POST /hosts/{id}/ssh/verify` |
| 4 Done | Back returns to 3, or to 2 when the host was skipped | — |

Two deliberate consequences, both signed off:

- **The password reset revokes the caller's own session.** That is intentional
  in the backend: an admin-set password is a recovery mechanism, so every
  session dies with it. Mid-wizard it would drop the user at the login screen.
  After a successful reset the wizard immediately re-logs in with the new
  password, the same `POST /auth/login` that `createAdmin` already performs.
- **Host removal keeps its confirmation.** `DELETE /hosts/{id}` requires the
  host name typed back, and is owner-only. The wizard reuses
  `HostRemoveDialog` rather than adding a bypass. A safety gate that a wizard
  can skip is not a safety gate.

Skipping the host step marks steps 2 and 3 "Skipped" in the rail with a grey
dash rather than a tick, and both stay clickable, so changing your mind costs
one click instead of a trip through Settings. "Open the dashboard" stays
available throughout.

### Motion

CSS only, no new dependency.

- Connector bar fills top to bottom (`scaleY`), the dot swaps to green with the
  tick scaling in, the active dot carries a soft amber ring.
- Content cross-fades and slides ~8px, direction-aware: back slides opposite to
  forward.
- Every transition sits behind `@media (prefers-reduced-motion: reduce)` and
  collapses to instant.

## Testing

`frontend/src/tests/onboarding.test.tsx` has 10 passing tests covering step
resumption and the SSH-verify gate. They stay green; the ones asserting on chip
markup are updated to the rail.

New coverage:

- Rail renders all four statuses, and only reachable steps are clickable.
- Back from the host step shows the admin email read-only.
- A password reset issues the follow-up login call.
- A skipped step stays clickable and does not render as done.
- `journey.spec.ts` gains a back-navigation step.

## Changes made while building

Three revisions, all from review of the running app.

**The rail sits inside the card, not against the page edge.** The mockup that
was picked dissolved the card into a full-height left panel; seen for real that
was wrong. The card is 820px, split into a 224px rail and the step content. The
224px is not arbitrary: `Brand` renders the lockup ~168px wide at its native
30px height, and anything narrower makes it overhang the divider.

**Five steps, not four:** Account, Host, Install, Verify, Done. Install and
Verify both sit on `ssh_pending`, because the server cannot distinguish "the
operator has pasted the key" from "they have not", only whether the key works.
So `stepFrom` lands on Install and reaching Verify is a local acknowledgement;
both tick green together when `ssh_pending` flips false. The rail is scaled ~30%
from its first size (dot 16→21px, label 11→14px, detail 9.5→12px).

**The account step reviews before it commits.** Rather than only explaining
after the fact that the email is now fixed, the form commits to a local review
screen and only that screen calls `POST /users`. This does not remove the
after-the-fact constraint, the edit panel above still applies on a revisit, but
it means the common case, a typo, is caught while it is still free.

One extra guard came out of testing: `admin_exists` true with `/auth/me`
returning 401 means the session died mid-setup. That used to re-offer the create
form, which would `POST /users` for an existing account and surface as "your
password is bad", the exact confusion `stepFrom` was written to kill. It now
shows a "you are signed out" panel instead.

## Out of scope

- Widening `UserPatchIn` to accept an email change.
- A general host-update endpoint.
- Any change to the Settings screens that already own post-setup editing.
