# Phase 8 (Scale) — verification notes

> In progress. Amendments are recorded here as they are decided, not at the
> end of the phase, so a behavior change is documented rather than
> rediscovered.

## Amendments

### A1 — Authorization is fail-closed; a membership-less user is denied everything

**What changed.** Before Phase 8, `api/deps.py::user_role()` computed a
user's role as `max(their memberships, default="viewer")`. The `default=`
meant a user belonging to **no** team was silently treated as a viewer and
could read every resource in the product.

Phase 8's authorizer (`services/authz.py::enforce`) derives every decision
from the g-lines built out of `team_members`. A user with no membership has
no g-line, matches no policy, and is denied — including reads.

**Why this is right.** "Belongs to nothing" is not a statement that someone
should see everything; it is the absence of a statement. Reading the absence
of an authorization record as a grant is precisely the accidental-access
failure mode this phase exists to close, and doc 10's Phase 8 Definition of
Done ("a viewer cannot mutate anything, verified by test-suite against every
route") only means something if the role a user holds is a real record rather
than a fallback constant.

**Why it does not lock a fresh install out of itself.** It never could:
`api/users` `POST` has always forced the **first** user on an empty
`users` table to `role="owner"` (`api/auth.py:70-72`, doc 08 §8) and has
always written that user a real `TeamMember` row in the "default" team
(`api/auth.py:95`). That path predates Phase 8 and is unchanged by it.

What Phase 8 changes is its status: the bootstrap owner's membership used to
be incidental — the fallback would have covered a mistake there — and is now
load-bearing. It is therefore pinned by test rather than left implicit. Two
guarantees, both asserted directly against `enforce`:

- an ordinary user in no team is denied, reads included;
- the first-run bootstrap owner is **not** denied, and holds real owner
  permissions on a fresh database.

**Consequence to watch.** Any code path that mints a `User` without also
minting a `TeamMember` now produces an account that can do nothing. Before
Phase 8 there was exactly one such path (`api/auth.py:95`, which does both).
Phase 8 adds a second — OIDC just-in-time provisioning — which is why A2
exists.

### A2 — OIDC just-in-time provisioning assigns membership at mint time

**The problem.** OIDC first-login creates a user by a different path than
`POST /users`. Under A1, provisioning that user without a membership yields a
silent lockout: authentication succeeds, every subsequent request 403s, and
nothing in the UI explains why.

**The policy.** Two settings, `PROXPLOY_OIDC_DEFAULT_ROLE` (unset by default)
and `PROXPLOY_OIDC_DEFAULT_TEAM_SLUG` (`"default"`):

- **Role configured** — the user row and a `TeamMember` row carrying that
  role are written in one transaction. An unknown role or a missing team slug
  is a loud configuration error, never a silent fallback to no membership.
- **Role not configured (the default)** — the user is provisioned
  `is_active=False`. Login fails with an explicit "awaiting administrator
  approval" error and writes an audit row, so an admin can see who is
  waiting and activate them through the existing users/teams API.

**Why deny-with-an-explanation is the default.** An identity provider's user
population is not automatically the application's authorized population —
pointing Proxploy at a company-wide Authelia should not hand every employee
in the directory a Proxmox console. Requiring the operator to opt in to
auto-provisioning makes the unconfigured case safe. The pending state is what
keeps "safe" from meaning "silent": the account exists, the operator is told,
and the user is told why they cannot get in.

**Why `is_active` rather than a new column.** It already exists on `users`,
is already honored by `services/authn.py:44` and by the password login path
at `api/auth.py:41`, and already means exactly this. No migration, no second
state machine to keep consistent with the first.

**What was explicitly rejected.** Provisioning OIDC users as admins (grants
the IdP the ability to mint privilege in Proxploy); and widening the viewer
default to cover them (re-opens A1 for every user, to paper over one path).
