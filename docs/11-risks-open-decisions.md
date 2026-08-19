# Proxploy: Risks & Open Decisions

Doc 11. Subordinate to `00-decision-brief.md`. This is the honest register:
what can hurt us, how likely, what we do about it, and which decisions we are
deliberately not making yet, with the information that would settle each one.

Likelihood/impact scale: Low / Medium / High.

---

## 1. Script execution requires root on the PVE node

**Risk.** App Store installs and updates run community bash scripts as root on
the user's hypervisor over SSH. A malicious, compromised, or simply buggy
script can destroy the node. There is no API-level containment; the Proxmox
HTTP API deliberately has no "run host command," which is exactly why we need
SSH at all.

**Likelihood:** Medium (upstream is active and well-reviewed, but it is a
third-party repo of root shell scripts). **Impact:** High.

**Mitigations, provenance and honesty, not sandboxing theater:**

- Script content is **pinned** at install time into `app_scripts`; every
  subsequent run executes the pinned content, never a silent upstream fetch.
- **Diff-vs-upstream** shown before any run whose pinned content differs from
  current upstream (or whose local edits diverge), so the user reviews exactly
  what changed.
- Explicit consent UX on every install/update: "this runs as root on
  <node>, exactly as if you ran it yourself." No euphemisms.
- Every invocation audit-logged; full stdout/stderr streamed live and
  archived permanently with the job.
- Dedicated ed25519 key used only by the executor, enrolled with explicit
  user action, revocable per host.
- We do **not** claim sandboxing, containment, or safety review we don't do.
  Any future hardening (e.g. `ForceCommand` wrappers, restricted key options)
  is additive, never marketed as isolation.
- **Non-root/API-first spike (Phase 4 entry gate, doc 08 §4, doc 10); RAN,
  SETTLED:** confirmed raw SSH-root is structurally necessary, not assumed.
  Community-scripts creates every LXC via the host-local `pct create` CLI
  (never the Proxmox API) and enforces `root_check()`; Proxmox's own REST
  API additionally has no LXC equivalent of the QEMU guest-agent `exec`
  endpoint, so even a Proxploy-authored container-create-via-API path would
  still need host-CLI access (`pct exec`/`pct push`) to run the install
  script afterward. Full findings, methodology, and the install-feasibility
  classifier rule this unlocked: `docs/notes/phase-4-spike.md`. Phase 4's
  `SSHExecutor` proceeds as designed below.

**Deferred decision:** whether to add an opt-in "hold installs until diff
approved by an admin" policy for teams. Resolves with: first multi-user
customer feedback after Phase 8.

## 2. Cross-host migration without a Proxmox cluster

**Risk.** Proxmox's native migration only works inside a cluster. Many target
users run independent hosts. Our non-clustered path is backup/restore:
PBS-mediated (backup → restore on target) or vzdump + transfer where no PBS
exists. That means real downtime proportional to disk size, plus MAC/IP/DHCP
wrinkles on the new host, and a window where the guest exists in two places.

**Likelihood:** High (the feature will be used on non-clustered hosts, that's
the audience). **Impact:** Medium (downtime and confusion, not data loss, if
we sequence correctly).

**Mitigations:**

- Preflight (`migrate.preflight`): capacity check, storage/network mapping,
  transfer size and **honest time/downtime estimate** before commit.
- UX states the truth: "this is stop → backup → transfer → restore → start;
  expect ~N minutes of downtime," never "live migration."
- Safe ordering: source guest is stopped and kept intact (renamed/flagged, not
  destroyed) until the target boots and passes a health check; single-click
  rollback = start the source again.
- Cluster-native `migrate` used automatically when hosts do share a cluster.

**Deferred decision:** offering an rsync-based delta pre-copy (sync while
running, short final stop-and-sync) to shrink downtime. Resolves with:
measured downtime numbers from Phase 8 testing on realistic disk sizes, 
build it only if PBS-path downtime is unacceptable in practice.

## 3. Agentless SSH vs. optional agent

**Risk.** The agentless default requires users to authorize an SSH key with
root capability on their hypervisor, a trust hurdle and a standing credential
we hold (encrypted). An agent avoids inbound SSH but adds a daemon to install,
update, and secure on every node, plus a second code path to maintain.

**Likelihood:** Medium (some security-conscious users will balk at SSH).
**Impact:** Medium (adoption friction, support burden; not correctness).

**Mitigations:**

- Agentless is the default and the only Phase 1–9 path; the brief pins this.
- Key is dedicated, ed25519, used only by the executor, revocable, encrypted
  at rest via SecretStore; docs show exactly what it's used for.
- Consoles/lifecycle/backups never touch SSH (Proxmox API websockets), so the
  SSH surface is limited to install/update/migrate, refusing SSH still
  yields a mostly-working product, and the UI says precisely which features
  need it.
- The executor is behind one interface, so the later agent is a pluggable
  implementation, not a rewrite (brief §8: nothing else may depend on it).

**Deferred decision:** whether/when to build the outbound-only agent, and its
update channel. Resolves with: post-launch demand data, count of users who
decline SSH enrolment (we can see feature-blocked states locally, reported
only via opt-in error/feedback channels, never telemetry).

## 4. SQLite write load from metrics

**Risk.** 30s samples across many hosts/guests plus job events plus audit all
write to one SQLite file. Write contention can stall the API or corrupt the
"live" feel; SQLite has one writer at a time.

**Likelihood:** Medium at >3–4 hosts or >100 guests; Low below.
**Impact:** Medium.

**Mitigations:**

- WAL mode from day one; single writer task batching metric inserts (one
  transaction per poll cycle, not per sample).
- Rollups (5m/1h) + retention pruning keep raw tables small; queries hit
  rollups for anything beyond the recent window.
- Postgres via DSN is a first-class, tested path; the escape hatch is a
  connection string, and the schema stays in the portable subset.
- VictoriaMetrics behind the `MetricsStore` seam as the arm's-length swap for
  genuinely big fleets.

**Deferred decision:** the exact host/guest count at which docs recommend
Postgres. Resolves with: load-testing numbers from Phase 2 (synthetic fleet
benchmark is part of Observe's DoD hardening).

## 5. community-scripts upstream drift, breakage, licensing

**Risk.** We don't control upstream: metadata schema can change (breaking
catalog ingest), scripts can break or change behavior between our pin and
their HEAD, entries can be removed, and individual scripts may carry licenses
or embedded third-party installers we must not misrepresent. Upstream repo is
MIT, but that must be re-verified, per brief §3, and per-entry anomalies are
possible.

**Likelihood:** High over any 12-month window (schema/scripts *will* drift).
**Impact:** Medium (store degrades; installed apps keep running).

**Mitigations:**

- Server-side ingest validates against a versioned schema; on mismatch the
  cached catalog keeps serving with a staleness banner, drift never breaks
  installed apps or the rest of the product.
- Pinning (risk 1) means upstream changes never silently alter what runs;
  diffs surface them instead.
- License verification at import: repo-level license recorded per catalog
  sync ("verified <date>" per brief §3); entries with unclear licensing are
  displayed with their upstream link and license field, and we consume
  metadata + call entrypoints only, we never vendor their code.
- Ingest failures alert us (proxploy-api side canary fetch) so we fix the
  parser before most users notice.

**Deferred decision:** whether the optional Aspyre-hosted catalog mirror
(brief §5, dumb CDN, app always falls back to upstream) ships at launch or
later. Resolves with: observed upstream rate-limit/outage behavior during
Phases 4–9 dogfooding.

## 6. Entitlement free-rider risk

**Risk.** Proxploy is self-hosted source-available code; anyone can patch
`Entitlements.enabled()` to return true and unlock armed Pro features. This is
**accepted, not mitigated away**.

**Likelihood:** High (someone will do it). **Impact:** Low–Medium (lost
revenue at the margin; paying customers are buying support, updates, and
honesty, not un-patchable bits).

**Mitigations:**

- The moat is hosted-signed Ed25519 tokens plus a fair deal: offline grace
  (~30 d), air-gapped free tier forever, no phone-home beyond entitlement
  refresh, no telemetry on that path. People pay products that respect them.
- **No DRM arms race**: no obfuscation, no kill switches, no remote
  attestation, ever. Cost of the race exceeds recovered revenue and poisons
  trust, which is the actual product.
- Server-side things stay server-side: anything genuinely hosted (the mirror,
  future hosted services) is naturally gated.

**Deferred decision:** none. This is decided; recorded here so it isn't
relitigated every quarter.

### 2026-08-06 amendment: the repository went private, and this section's premise did not get updated

**What this section says.** The risk above is framed entirely on Proxploy
being **source-available**: "anyone can patch `Entitlements.enabled()`" is
only a live risk if anyone can read the source to find `Entitlements.
enabled()` in the first place, and the "Deferred decision: none" line closes
the book on it as *accepted* rather than mitigated, reasoning that customers
buy "support, updates, and honesty, not un-patchable bits"; a sentence that
only makes sense addressed to people who can see the bits.

**What actually changed.** `proxploy-app` is **private**, and staying
private is Aspyre Labs' own decision, made 2026-08-06. This was not decided
by anything in Phase 9c's plan or spec; it is an owner decision the docs
are catching up to, not a mitigation this phase engineered.

**Why that makes the section's premise stale, not wrong.** The reasoning
above still holds *if the repo is public*. It doesn't hold today:

- The patching risk this section accepts is now closer to moot than
  mitigated, nobody can patch a copy of `Entitlements.enabled()` they were
  never given. That is a stronger position than the "accepted, not
  mitigated away" framing describes, and it happened by policy change, not
  by anything in the entitlement design itself.
- The source-available claim this section's opening sentence rests on is no
  longer true of the product, and "source-available" is a specific,
  checkable claim, repeating it in marketing or trust copy while the repo
  is private would be a false statement about the product, not a stale
  risk note. `proxploy-docs`' trust page (`src/content/docs/trust/index.md`,
  written in this same phase) already states the current, accurate
  position, **"Proxploy is not source-available today"**, precisely
  because it was written after the repo went private and this doc was not.

**This is recorded as an open decision, not resolved here.** Per this
document's own convention (§6 was itself marked "none" to close the book on
a question, this note reopens exactly that framing, deliberately, rather
than silently rewriting the text above it), two paths exist and neither is
taken by this note:

1. **Amend §6 above** to drop the source-available framing and restate the
   free-rider risk in terms that hold for a private repo (the risk shrinks,
   it does not vanish, an employee leak, a compromised build host, or a
   future decision to open the repo all reintroduce it).
2. **Make the repository public**, restoring §6's original premise and
   argument as written.

Which of these happens, and when, is **owned by Aspyre Labs**; a business
and trust-posture decision this build phase has no standing to make on its
own. Until one is chosen, this document carries a contradiction on
purpose: §6 above is left as originally written (per this file's own rule
against silently rewriting history), and this amendment is the record that
its premise no longer matches the product.

### 2026-08-06 resolution: path 2: source-available stands, private is temporary

Aspyre Labs chose **option 2 above**, same day: Proxploy **is**
source-available as §6 describes, and the repository will be made public.
Private is a **staging state, not a posture**; it holds until the owner
judges the project ready to launch, and is not a decision to close the
source.

Consequences, so later work does not re-litigate this:

- **§6 above stands as originally written.** Its premise is deferred, not
  falsified. Do not rewrite it.
- **Entitlement enforcement is bounded by §6's own concession.** Anyone can
  patch `Entitlements.enabled()` once the source is public, and this
  document accepts that. Enforcement work should be proportionate to that
  reality, enough to make the honest path obvious, not an arms race §6
  already declined to enter.
- **Distribution stays as Phase 9a designed it**: a public repo plus GitHub
  Releases. No alternative artifact host is needed, and the install URLs the
  9c docs print are the ones that will work.
- **Trust and marketing copy must not claim source-available until it is
  true.** `proxploy-docs`' trust page currently states "not source-available
  today", which is accurate now and **must be updated as part of going
  public**, not before. Publishing the claim ahead of the repo would make
  it false in the window between.

## 7. Proxmox API version drift (PVE 8 / PVE 9)

**Risk.** We manage hosts across PVE major versions with differing API
behavior (endpoint params, return shapes, termproxy/vncproxy details,
vzdump/PBS options). A fleet can legitimately mix 8.x and 9.x mid-upgrade.
proxmoxer is thin; it will not paper over semantic differences for us.

**Likelihood:** High (PVE 9 is current; 8.x remains widespread).
**Impact:** Medium.

**Mitigations:**

- Capture `pveversion` per host at onboarding and each poll; all
  version-dependent calls go through one internal Proxmox client layer
  (`backend/proxploy/services/proxmox.py`, adapted from the existing
  lab-cluster-deploy proxmoxer module, doc 02 §4, doc 03; the only place
  allowed to branch on version), not scattered call sites.
- CI matrix: integration tests against disposable PVE 8.latest and 9.latest
  instances (doc 10 Phase 1 test-infrastructure deliverable); release notes
  state the supported window (current and previous major).
- Unknown-version hosts get a warning banner, not a refusal; degrade
  honestly.

**Deferred decision:** how long to support a PVE major after Proxmox EOLs it.
Resolves with: user base version distribution after launch (support-request
data, not telemetry).

## 8. One-CT-per-app vs. upstream multi-container patterns

**Risk.** The apps-only model promises one app = one CT. Most community
scripts already build single-CT apps (Immich's script bundles its services in
one container), but some upstream apps are docker-compose-shaped or split
across helpers; upstream could trend toward multi-CT or Docker-in-LXC
patterns that strain the model. Forcing everything into one tile could
misrepresent what's actually running.

**Likelihood:** Medium. **Impact:** Medium (model confusion, awkward special
cases in the store).

**Mitigations:**

- The model is a **product rule, not a hope**: the store surfaces only
  entries installable as a single CT; the catalog ingest classifies entries
  (`catalog_entries.installable` / `unsupported_reason`, doc 04) and
  anything that can't honor one-CT is excluded from install (visible with an
  "unsupported pattern" explanation rather than silently missing). The
  Phase 4 entry-gate spike confirms this is the common case, not a hope:
  568 of 572 upstream `ct/` scripts (99.3%) call `build_container` exactly
  once (`docs/notes/phase-4-spike.md`).
- Docker-in-LXC entries (upstream has these) are still one CT, the CT is
  the app boundary; what runs inside is the script's business, shown honestly
  on the app detail page.
- Adoption (`apps.adopt`) maps one CT to one app only; no synthetic grouping.

**Deferred decision:** whether a future "app group" cosmetic layer (multiple
apps visually grouped, still one CT each) is ever worth it. Resolves with:
count of real catalog entries excluded by the one-CT rule after Phase 4
ingest, if it's a handful, never build it.

## 9. Secrets master-key loss / recovery

**Risk.** All host credentials and SSH keys are Fernet-encrypted under a
master key in a root-only file on the Proxploy host. Lose that file (host
dies, bad backup, careless reinstall) and every stored credential is
unrecoverable ciphertext; the DB alone is not enough to restore service.

**Likelihood:** Medium (self-hosters lose files). **Impact:** High for the
install, though bounded: re-onboarding hosts (new tokens + re-enrolled SSH
keys) fully recovers, infra state lives in Proxmox, app identity in the DB.

**Mitigations:**

- Install prints and docs stress: back up the key file alongside the DB; the
  built-in backup guidance and self-update pre-backup include both.
- MultiFernet rotation supported from day one, so key rotation after a
  suspected leak is routine, not surgery.
- Explicit recovery runbook in proxploy-docs: restore DB + key ⇒ full
  recovery; DB only ⇒ guided re-onboarding flow that preserves app identity
  and history (credentials are the only loss).
- App refuses to silently regenerate a missing key over an existing DB, it
  stops with the recovery instructions instead of bricking ciphertext
  ambiguously.

**Deferred decision:** optional passphrase-wrapped key export ("recovery
kit") in the onboarding wizard. Resolves with: whether the runbook proves
sufficient in beta support load; build the kit if key-loss reports appear.

## 10. Self-update failure modes

**Risk.** Self-update mutates the running system: a failed migration, a
half-written release, or an update that breaks the updater itself can strand
users on a broken install, the worst possible outcome for software whose
pitch is "manages your infrastructure."

**Likelihood:** Medium (updates are frequent; each is a chance).
**Impact:** High.

**Mitigations:**

- Pre-update snapshot: DB backup + key-file copy + current version retained;
  update applies to a new versioned directory/image and switches over, so
  rollback = switch back + restore DB. Never update in place.
- Alembic migrations are forward-tested in CI from every released schema
  version to head, on SQLite and Postgres.
- Health check after switch-over; automatic rollback if the new version
  fails to serve within a timeout.
- The updater is the most boring code in the repo: no dynamic cleverness,
  release artifacts are checksummed (signed manifests fetched from the
  release channel), and the manual-update path (installer re-run) always
  works as the fallback and is documented first.
- Per-channel staged rollout (e.g. publish to "edge" before "stable") so we
  break ourselves before users.

**Deferred decision:** artifact signing scheme (reuse the Ed25519
entitlement keypair vs. a dedicated release key, leaning dedicated, since
license and release trust should be revocable independently). Resolves with:
Phase 9 installer design; must be decided before the first public release,
and the checksummed-manifest requirement stands regardless.

---

## 11. The backups list is capped, and one lookup rides on it

`GET /backups` returns the 200 newest archives, capped after it was found
returning the whole table on a page that polls every 60s and can be open in
several tabs. The stats block beside it is computed with aggregates over the
whole table, so the totals stay true no matter what the list shows.

One caller reads more into the list than it now carries.
`frontend/src/routes/backups.tsx:149` finds a host id by scanning the returned
backups for the chosen datastore, so a datastore whose newest archive falls
outside the 200 newest overall yields null there.

Left as is, deliberately. The field was already nullable, the table is titled
"Recent backups", and the degradation is honest: a quiet null, not a wrong
host. Recorded here so it is not rediscovered later and filed as a bug. If it
ever needs fixing, the fix is a dedicated lookup rather than a bigger cap,
since raising the cap only moves the boundary.

`backups.taken_at` is indexed (`ix_backups_taken_at`, migration
b3e8c15a7d42), because the cap bounded what the route returned and not the
work it did: the ORDER BY sorted the whole table on every poll. A test pins
the query plan rather than a timing.

---

## 12. The audit log can now be cleared from the product

Doc 08 §7 used to promise "no delete path in the API or UI". `DELETE /audit`
breaks that promise on purpose, because the alternative operators had was
`sqlite3` against the app's own database, which is worse in every direction:
unrecorded, unbounded, and one typo from taking other tables with it. The
capability is real, so it is gated rather than hidden: owner only
(`("audit", "clear")`, the same floor as `host.remove`), a typed confirmation
of `clear audit log`, and one `audit.clear` row written *after* the delete
naming who did it, how many rows went, and whether the scope was everything or
everything older than a given instant. A refused attempt is recorded too.

Residual risk, stated plainly: an owner can erase the trail and the only thing
left behind is a single row saying they did. That is evidence, not prevention,
and it is the same posture as row 12 of doc 08's threat model. Anyone who needs
tamper evidence has to ship the export off-box, which is unchanged advice.
Archival-based retention (doc 08 §7) is still unbuilt, so `before` deletes
rather than archives; the "Usage cleanup" system schedule prunes metrics only
and has never touched `audit_events`.

---

## Open at the end of 2026-08-15

Not risks so much as the shortlist a fresh session should start from.

1. **Nothing built today has been looked at.** Roughly 45 user-facing changes
   landed: every audit label rewritten to the neutral convention in doc 13, a
   "Blocked" prefix on refused rows, renamed statuses, 19 pickers reworked,
   skeletons on four surfaces. Both suites are green and neither proves the
   activity feed reads well. Drive the app and look at it before building more.

2. **apiErrorDetail cannot read a Pydantic 422.** `main.py`'s validation
   handler returns `{"detail": [ ...objects... ]}`, a list, and the helper only
   reads a string detail, so it falls through to the caller's fallback. Every
   422 in the app therefore shows a generic sentence instead of the field that
   was wrong. Found while splitting the profile password errors, left alone
   because it wants a decision about how field errors should read, not a patch.

3. **Two `/auth/me` queries under different keys.** `useMe` in `api/hooks.ts`
   is `['me']`; `useTotpStatus` in `api/account.ts` is `['auth', 'me']`. Both
   hit the same route. Nothing is broken, but an invalidation aimed at one does
   not touch the other, which is a trap already worth one wrong guess.

4. **AlertRuleForm's target select is a near miss.** `targetType` starts "any"
   while `targetOptions` drops "any" for a single-target metric, so the control
   would display "host" while the state says "any" and the POST would send
   "any". Unreachable today because the initial metric is multi-target. It goes
   live the day that changes.

5. **Hardware checks 7, 8, 9, 11 and 12** in doc 12. None blocked on effort:
   7 needs the nodes unclustered, 8 can cost connectivity to the node running
   it, 9 needs backups that exist, 11 needs a real IdP, 12 means deliberately
   breaking quorum.

   **All five closed by 2026-08-18.** Worth recording what the estimates got
   wrong, since the same reasoning will show up again: "11 needs a real IdP" was
   read as needing someone's cloud account for three days, when the App Store
   carries five self-hostable identity providers and a Keycloak on the lab is a
   third-party implementation on the wire. The blocker was never access, it was
   the assumption.

## Open at the end of 2026-08-16

Cluster peer auto-enrolment shipped in seven phases today. What it leaves open:

1. **None of it has met real Proxmox.** Every node in every test is a
   `FakePVE`, including the browser tests. Two things a fake cannot answer:
   whether the `ip` a node reports in `/cluster/status` is one the API actually
   answers on, and whether each node presents the certificate the panel shows
   before you tick its box. Both are cheap to check against a real two node
   cluster and expensive to be wrong about, since the second one is what the
   pinning rests on. Check them before anyone relies on the feature.

   **Answered 2026-08-17 against cluster `lab-cluster` on PVE 9.2.10**, in both
   directions, by `backend/scripts/verify_cluster_peers.py`. Both nodes serve
   distinct certificates, stable across reads, and Proxmox's own `pve_fp` join
   record agrees with what the socket returned. Pins are enforced: the right one
   connects, a corrupted one is refused. Tokens do replicate cluster-wide. Doc
   12 checks 13 to 16 carry the detail and the two things a pass on this lab
   does NOT cover: a cluster with a dedicated corosync link, and a narrow token
   in place of this lab's root one.

2. **The certificate swap refusal has no browser coverage, deliberately.** The
   panel echoes back the fingerprint it displayed and enrolment refuses a peer
   that presents something else, but nothing reachable from a browser can
   change what the fake presents between those two moments. Faking it would
   mean a fixture that lies about how certificates change. Covered against the
   real handler in `test_hosts_peers.py`, and worth one manual check on real
   hardware alongside item 1.

   **Observed for real 2026-08-17, and the guard worked.** No manual sequence
   was needed in the end: `pvecm add` regenerates the joining node's
   certificate, so rejoining `node1` to the cluster changed its fingerprint and
   the pinned client refused every connection with `kind=tls_fingerprint`. A
   legitimate cause, not a contrived one. Doc 12 check 16 has the detail.

   **Fully closed 2026-08-17: the browser half was run and passed.** `node1`'s
   certificate was regenerated deliberately (`pvecm updatecerts --force`) and
   the real Edit dialog was driven in a real browser against the real node. It
   named the change, printed both fingerprints in full, offered "Accept the new
   certificate", and reported Connected after accepting, with the stored pin
   matching what the node presents. Doc 12 check 16 carries two presentation
   notes worth reading before relying on it: three 502s land in the browser
   console while the pin is stale, and the accept control sits below the fold at
   laptop viewports because the dialog scrolls.

3. **`journey.spec.ts:163` fails.** VM create never shows "succeeded" within
   twenty seconds. Pre-existing from the VM wizard work of 2026-08-15,
   confirmed identical against the commit before today's. It matters more than
   it looks: the `chromium` Playwright project depends on the `journey`
   project, so this one failure skips 14 other tests and the suite needs
   `--no-deps` to run at all.

   **FIXED 2026-08-17, and it was the test that was wrong, not the app.**
   Playwright's error context showed the dialog saying `pve-01 has no lifecycle
   API token configured; add one in Settings -> Hosts before this operation can
   run.` The VM wizard gained a lifecycle-capability gate and the journey was
   never given the token: its onboarding step filled only the monitoring pair,
   under a comment claiming that was all this journey needed, which stopped
   being true the moment the gate landed. So the app refused correctly and the
   test asserted a success that could not happen. The step now ticks the
   Lifecycle capability, which reveals its token pair, and fills it.

   Worth noting the failure shape: a capability gate reads as a timeout,
   because the assertion waits for "succeeded" while the dialog is showing an
   actionable refusal the whole time. Twenty seconds of waiting hid a message
   that was correct and immediate.

   The journey now passes in 4.0s, and the full suite runs 15/15 with
   dependencies intact, no `--no-deps` needed.

4. **Duplicate React key at `frontend/src/routes/store.tsx:372`.** The category
   skeleton uses its class string as the key over a list where `w-20` and
   `w-16` each appear twice. Only fires when the catalog query is slow enough
   to render the skeleton, which is why it is intermittent, and it is what
   `smoke.spec.ts` currently fails on.

   **FIXED 2026-08-17.** Keyed by index instead: it is a fixed-length
   placeholder that never reorders, which is the case an index key is correct
   for. `smoke.spec.ts` (login and every nav page with a clean console) passes
   with it.

5. **Peer addresses could come from `pve_addr`, and deliberately do not.**
   `/cluster/config/join` reports `ring0_addr` and `pve_addr` as separate fields
   per node, so on a cluster with a dedicated corosync link the address the
   panel builds from `/cluster/status` may be one the API never answers on.
   Reading `pve_addr` instead would remove that risk entirely, and a
   `PVEAuditor` token may read the endpoint, so nothing blocks it.

   **BUILT 2026-08-17.** Both prerequisites had cleared (a PVEAuditor token can
   read the endpoint, verified on PVE 9.2.10), and the deferral rested on "no
   such cluster has been reported" while the hazard itself was confirmed real by
   PVE storing `ring0_addr` and `pve_addr` as separate fields.

   `ProxmoxClient.cluster_join_info()` reads the endpoint, and a shared
   `_api_addresses(client)` helper turns it into `{node: pve_addr}`, used by
   BOTH discovery and enrolment so the address an operator was shown is the one
   that gets enrolled. Deliberately best effort and per node: an unreadable
   endpoint, an absent nodelist, or a nodelist that omits one node all fall back
   to the `/cluster/status` address, which is what was used before and is
   correct whenever the two coincide. Failing discovery outright because one
   extra endpoint was unreadable would be the worse trade.

   Four tests cover it, including a modelled split-network cluster where the
   corosync address has no server at all: the peer is offered at `pve_addr` and
   is reachable, where before it would have been offered at the corosync address
   and reported dead. Verified against the real `lab-cluster` cluster too, where the
   two addresses coincide and the offered address is unchanged.

   Still true, and still not used: `pve_fp` is written at join time, so it is a
   second opinion on a node's certificate and never a replacement for reading
   the live one.

6. **A pin is silently invalidated by anything that regenerates a node
   certificate, and there is no way back except re-pinning.** Found the hard
   way on 2026-08-17: `pvecm add` regenerates the joining node's certificate, so
   a host that was pinned stops working the moment it rejoins a cluster. The
   same applies to `pvenode cert set` and to an ACME renewal.

   **Correction, same day: the second half of this item was wrong when first
   written, and the affordance it asks for already exists.** It claimed there
   was "no affordance saying this changed legitimately, re-pin it". There is,
   and it is exactly the shape this item went on to propose: `HostEditDialog`
   runs Test connection, and when `POST /hosts/{id}/test` comes back with
   `tls_fingerprint_seen` differing from `tls_fingerprint` it says
   "<host>'s TLS certificate has changed", prints BOTH fingerprints in full
   (never truncated, so they can be compared against the node), and offers
   "Accept the new certificate", which PATCHes the new pin and confirms with
   "<host> is now pinned to the certificate it is presenting."
   `tests/host-edit-dialog.test.tsx` covers both that flow and the case where
   the two match and nothing is offered.

   The claim came from watching a pinned client refuse a connection in a
   script and inferring the product had no recovery, rather than from reading
   the product. Recorded rather than quietly deleted, because "I hit the guard
   and assumed there was no way back" is the mistake worth not repeating.

   **What genuinely remains is small.** Nothing warns AHEAD of time that
   joining a cluster regenerates the certificate and will invalidate the pin,
   so the sequence is: rejoin, host goes unreachable, operator opens Edit, runs
   Test connection, accepts. That works and is one dialog away, so this is a
   documentation note rather than a gap. The `pvecm add` fact itself is the
   useful part and is now in doc 12 check 16.

   Separately, and already documented in `api/hosts.py`: with `verify_tls` true
   the pin is not enforced at all, so a changed certificate never raises and
   the control never appears. CA validation is the trust anchor in that mode.
   That is deliberate, not a consequence of this item.

   **The SSH host key pin has the same problem and, unlike the TLS pin, no way
   back at all. Found 2026-08-17.** Rejoining `node1` to the cluster rotated its
   SSH host key too, and every App Store install on it then failed. Grepping
   every write site: `Host.ssh_host_key_fingerprint` is only ever set through
   `on_new_fingerprint`, which fires ONLY when the stored pin is already None.
   Nothing re-pins it. `POST /hosts/{id}/ssh/verify` reports
   `{"error": "host_key_mismatch"}` and stops there.

   So a legitimately rotated SSH host key bricks installs, updates and the
   transfer-strategy migration for that host, permanently, with the only fix
   being a manual database write. The TLS side has "Accept the new certificate";
   this side has nothing. The asymmetry is the bug.

   **FIXED the same day, as the same control.** `POST /hosts/{id}/ssh/verify`
   now returns `ssh_host_key_fingerprint` and `ssh_host_key_fingerprint_seen`
   on a mismatch (carried on the exception rather than parsed out of its
   message), `PATCH /hosts/{id}` accepts `ssh_host_key_fingerprint` with the
   same omitted-versus-null contract `tls_fingerprint` uses, and
   `HostEditDialog` shows "<host>'s SSH host key has changed" with both values
   in full and an "Accept the new host key" button.

   Two decisions worth keeping. **Test connection now checks SSH too**, because
   the whole failure mode is that a rotated key answers the API perfectly and
   fails every install: checking only the API reported a healthy host that could
   not do the thing the key exists for. And the copy names installs, updates and
   migration explicitly, and says that rejoining a cluster rotates the key, so
   the routine cause is stated rather than leaving an operator to assume an
   attack.

   Verified against `node1` itself: its pin was set stale, the dialog showed
   both real fingerprints, accepting re-pinned it and the panel went away. Five
   frontend tests and four backend ones, including that a host with no enrolled
   key stays silent.

   Worth pairing with the executor fix committed the same day (8b40161): the
   mismatch was additionally being reported as "saw None", because asyncssh had
   not called `validate_host_public_key` at all on that node, so an unread key
   was phrased as a rotated one.

9. **The swallowed error detail: fixed 2026-08-17.** Located in
   `HostForm.tsx::errText`. When the server named a known error kind,
   `KIND_COPY[kind]` was returned and `body.detail` was dropped on the floor.
   `KIND_COPY` says what to DO about a kind; only `detail` can say what
   happened, and it is the half the backend works hardest to get right: which
   privilege Proxmox refused (`_permission_detail`), or which fingerprint was
   pinned against which was presented.

   Bounded more narrowly than it sounds. `KIND_COPY` has four keys, `auth`,
   `unreachable`, `tls_fingerprint`, `refused`, and only those swallowed
   anything; `permission` was never in it, so a denied privilege already showed
   its detail. The one that mattered is `tls_fingerprint`, where the two
   fingerprints ARE the finding, and today's real certificate change on `node1`
   (item 6) is exactly the case an operator would have been shown generic advice
   for. Both are now returned, advice first: act on the first sentence, verify
   with the second. 409 and 403 deliberately keep their own wording, since there
   the detail restates the same fact.

10. **The SSH enrolment checkbox: nothing to fix, checked 2026-08-17.** Carried
    as "granting the key silently", which is not what the code does. The
    checkbox defaults OFF (`ssh_enroll: false`). Its label is itself the
    attestation: "I understand this authorizes a root shell on the node",
    followed by copy naming community scripts, root, and that skipping it leaves
    everything except installs, updates and migration working. And
    `POST /hosts` requires BOTH `ssh_enroll` and `ssh_consent`
    (`api/hosts.py:259`), so an API caller cannot get the key as a side effect
    of asking for installs.

    The one thing worth knowing is that the frontend supplies `ssh_consent`
    from the same tick (`HostForm.tsx:185`). That is correct here rather than a
    loophole, because the label carries the attestation wording, so one tick is
    one informed decision. The two-flag gate exists for API callers who have no
    label to read. Recorded so this is not "fixed" later by adding a second
    checkbox that asks the same question twice.

    The consent copy dates from 2026-07-29, well before this item was written on
    2026-08-15, so whatever the note meant is not recoverable from the
    repository. Which is the real lesson: all three of these carried items were
    one summary line with no write-up, and two of the three turned out to
    describe something other than what the line said.

8. **The node shell toggle and `Sys.Console`: fixed 2026-08-17, at the point of
   use rather than at the toggle.** The carried item read "the node shell
   toggle can be enabled without `Sys.Console`", and the obvious reading is
   that `PATCH /hosts/{id}` should refuse. It should not, and that is worth
   recording so it is not "fixed" that way later: doc 08 §9 makes the toggle a
   second deliberate gate ON TOP OF RBAC, not a privilege probe, and
   `pveum.py` keeps `Sys.Console` out of the console capability on purpose. A
   toggle that reached out to Proxmox to validate a privilege would also have
   to decide what to do when `/access/permissions` is unreadable, which is the
   tri-state `_missing_privileges` exists to handle.

   The actual defect was downstream, and worse than a missing check. All three
   console routes called `termproxy` / `node_termproxy` / `vncproxy` OUTSIDE
   the `except ProxmoxError` block that wrapped `client_for_host` on the line
   above, so a 403 from a narrow token escaped the route unhandled. The message
   was never missing: `_permission_detail` already turns Proxmox's own
   "Permission check failed (/nodes/pve1, Sys.Console)" into a readable
   sentence. Nothing was catching it to deliver.

   So enabling the toggle with a token that lacks `Sys.Console` is allowed, as
   designed, and opening the shell now says which privilege Proxmox refused
   instead of failing opaquely. Fixed at all three call sites, not just the node
   shell one, because the same gap sat in the app console and VM VNC routes.
   Three tests, one per route.

7. **The committed `master.key`: assessed 2026-08-17, and the answer is do not
   rewrite history.** This sat on the carried list as an open purge decision,
   phrased in a way that reads like an emergency. It is not one, and the
   evidence is worth recording so it stops being re-litigated.

   `2be341a` committed `backend/data.bak-142701/` whole: `master.key`,
   `proxploy.db`, `-wal` and `-shm`. Both the key AND the database it protects,
   which is the worst possible pairing. What is actually in them:

   - **The committed key is not the live key.** `backend/data/master.key`
     differs, because the reset procedure (`mv data data.bak-$(date +%H%M%S)`)
     moves the old dir aside and a fresh one gets a new key.
   - **The committed database holds no encrypted anything.** `hosts`: 0 rows.
     `host_credentials`: 0 rows, so `encrypted_blob` has 0 non-null values.
     `users.totp_secret_enc`: 0 non-null values. The committed `-wal` is 0
     bytes, so nothing is hiding there either. **The leaked master key
     decrypts nothing that was leaked with it.**
   - What DID leak: one `users` row. `admin@aspyrelabs.com`, a display name,
     and a `password_hash` that is **argon2id** (`$argon2id$v=19$`, 97 chars).
     No TOTP secret, no OIDC identity.
   - The repository is **private**.

   So the residual exposure is one argon2id hash and one email address in a
   private repo's history. argon2id is memory-hard, so that hash is not
   practically crackable unless the password behind it is weak.

   **Decision: do not rewrite history.** Rewriting `main` invalidates every
   clone and every existing checkout, to remove a key that decrypts nothing.
   That is disproportionate to one password hash.

   **Decision 2026-08-17: the account and its password stay as they are.**
   `admin@aspyrelabs.com` is the development test account and is in use until
   Proxploy is ready to deploy, so rotating it now buys nothing while costing a
   working login. The risk is accepted deliberately, on these grounds: the
   repository is private, the hash is argon2id, and the key committed beside it
   decrypts nothing.

   **The trigger, and it is a deployment gate rather than a suggestion:** this
   account must not survive into production. Before Proxploy is deployed
   anywhere real, either delete `admin@aspyrelabs.com` or change its password,
   and do not reuse that password for the production admin. The reason to write
   it down here is that an accepted risk with no trigger is just a forgotten
   one, and the hash in `2be341a` stays readable to anyone who ever has access
   to this repository's history.

   The cause is already fixed: `bd5eb22` added `data.bak-*/` to
   `backend/.gitignore` (line 9, with a comment explaining why), so the reset
   procedure can no longer produce a committable directory. Verified with
   `git check-ignore`.

## Open at the end of 2026-08-18

Doc 12 check 7's data movement passed today, on the third attempt, and the two
attempts that failed are the value: three defects and one leak, none of which
any suite could have caught. What that run leaves open:

1. **A storage's `nodes` restriction is invisible to the migration preflight.
   FIXED 2026-08-18.**
   `services/migrate.py::_storage_names` reads `cluster_storage()`, which is
   `GET /storage`, the cluster-wide CONFIG list. A PVE storage may carry
   `nodes <a,b>` restricting which nodes serve it, and that field is never
   consulted, so a pool restricted AWAY from a host still counts as "shared in
   common" for that host. Observed on hardware: with `nfs-shared` set to
   `--nodes node2`, `preflight` answered `strategy: shared_storage,
   shared_storage: nfs-shared` for a migration off node1, while `pvesm status`
   on node1 reported that same pool `disabled` in the same minute.

   The consequence is worse than a wrong label: STRATEGY_SHARED would vzdump to
   a pool the source cannot write, so a migration that had a working transfer
   path available refuses on a storage error instead. A disabled row (`disable
   1`) is the same shape, since `/storage` reports config rather than state.

   **Fixed by filtering the config rows**, the second of the two candidates
   considered: `_serves(row, node)` drops a storage whose `nodes` excludes this
   node or whose `disable` is set, and `_storage_names`/`_dir_storage` take the
   node. That reproduces PVE's own decision (it is why `pvesm status` called the
   pool disabled on node1) and costs no extra call, where
   `/nodes/{node}/storage` would have cost one per host. Two tests carry the
   exact row shape the real cluster returned, including `nodes: "pve-tgt"`, and
   both were confirmed to fail with the filter removed.

2. **The transfer strategy picks the target rootfs pool by first match, and
   preflight checked capacity on the wrong pool. THE CAPACITY HALF IS FIXED
   2026-08-18.** `capacity_ok` measured free space on the DIR storage that stages
   the ARCHIVE, not on the pool the rootfs lands on, so it could read true while
   the destination was full.

   Preflight now names both pools, `rootfs_storage` and `staging_storage`, and
   `capacity_ok` is false if EITHER is short and unknown if either is unknown,
   rather than rounding up to a pass. A target with no pool carrying `rootdir` is
   a blocker, which moves that refusal to before the source is stopped instead of
   after the archive has crossed the network. The handler takes the pool from its
   own preflight, so the pool named in the preview is the pool the restore uses,
   and the dialog shows "lands on X (staged via Y)".

   **The pick is now the operator's, 2026-08-18.** `rootfs_candidates` returns
   every active pool on the target that can hold a rootfs, preflight reports the
   set as `rootfs_options` alongside the chosen `rootfs_storage`, and both the
   preflight and migrate routes take a `storage` field. A name that cannot hold a
   rootfs is a blocker naming the real options, never a silent swap onto
   something else. The dialog is a select that re-previews on change, because
   capacity is per pool and the number above the button has to be about the pool
   actually selected. Omitting the field keeps the old behaviour exactly.

   **The hardware run supplied better evidence than the tests did.** Asked about
   the same cluster, `node1` and `node2` both offer `['local-lvm',
   'nfs-shared']` and both correctly exclude `local` (backups and templates, no
   `rootdir`), but the DEFAULT differs per node, `nfs-shared` on one and
   `local-lvm` on the other, purely because PVE returns the rows in a different
   order. Same code, same cluster, two different destinations depending on which
   node was asked. That is precisely the arbitrariness this closes, and it is
   also why the default is still first-match rather than "preserve the source's
   storage class": matching class across two hosts that need not share pool names
   is a guess, where naming the choice is not.

   Verified on hardware only for the cluster strategy, where both fields are
   correctly null because no restore happens. The transfer path's pool naming was
   observed in the morning's real run ("rootfs on nfs-shared" in the job
   transcript); the preflight fields themselves are covered by tests, not by a
   second split-cluster run.

3. **A restore now needs the Lifecycle capability, and nothing warns before the
   job runs.** `VM.Allocate` and `SDN.Use` are lifecycle privileges, so
   `backup.restore` and `migrate.app` both resolve a lifecycle client. A host
   carrying only a Backup token gets `CapabilityNotConfigured` from the job,
   which names the fix ("add one in Settings -> Hosts") but only after the job
   is queued and, for a migration, only after the source has been stopped. The
   route gates could check the capability up front the way
   `api/catalog.py::install_catalog_entry` checks for an `ssh_key`.

   **CLOSED 2026-08-18**, and it was as small as it looked: the route now
   resolves every token the job will spend before `enqueue_and_audit`.
   `client_for_host` raises `CapabilityNotConfigured` on a missing credential
   alone, with no network call, and `main.py` already turns that into a 409
   naming the capability and where to add it, so the gate is a loop and no new
   error shape.

   Which tokens are needed depends on the strategy, which is why the check sits
   after the preflight rather than in a dependency: a native cluster migrate
   never dumps anything, so demanding `backup` there would refuse a migration
   that would have worked. Both cases are tested. The backup restore route got
   the same treatment for `backup` + `lifecycle`.

   Verified on hardware against the real app: with node1's lifecycle token lifted
   out, `POST /apps/1/migrate` answered
   `409 node1.lab.local has no lifecycle API token configured; add one in
   Settings -> Hosts before this operation can run.`, zero jobs were queued, and
   CT 101 was still running on its own host.

4. **A real VM create was never run until today, and it was broken.** Closed
   the same day it was written: `VM.Config.HWType` was missing from the
   lifecycle role, so the first real `POST /nodes/{node}/qemu` from this
   environment refused outright. `scsihw` and a `virtio` NIC model are
   hardware-TYPE config to PVE, which `VM.Config.Disk` and `VM.Config.Network`
   do not cover. Added, and isolated in both directions; `VM.Config.CDROM`
   turned out NOT to be needed even with an ISO, so it stayed out. Doc 12 check
   17 carries the detail.

   What this leaves is the pattern rather than the bug: **capability gaps are
   found the first time a code path meets real PVE, and are invisible to a fake
   that accepts any token for any call.** So the rest of those calls were swept
   the same day (doc 12 check 18): snapshot, rollback and clone passed, the
   guest NIC edit did not, and a third gap fell out of it. `set_guest_nic` ran
   its config READ on the lifecycle token, which has no `VM.Audit`, so a NIC
   edit 403'd before touching the guest. Fixed in the code rather than the role,
   deliberately: reads move to monitoring, which every host has, and no operator
   has to regenerate a token.

5. **One VM appears once per enrolled host on a cluster.** Found by check 18 and
   half-fixed the same day. `/cluster/resources` answers for the whole cluster
   from any member, so every polled host mirrors every VM. The dangerous half is
   fixed: `vms.node_name` now records where a guest actually runs, so actions
   reach the right node instead of answering `500 Configuration file
   'nodes/<other>/qemu-server/<id>.conf' does not exist`.

   **The duplicate rows are now collapsed at every read, 2026-08-18.**
   `dedupe_vms(rows, hosts)` keys on `cluster_scope`, keeps the row belonging to
   the host registered AT the guest's node (lowest id as the tiebreak, so the
   choice is deterministic rather than whichever poll landed first), and leaves a
   guest on an unenrolled node visible: hiding it would remove working
   functionality, since a cluster-wide token acts on any member's guest.

   It turned out to matter in five places, not one: the VM list, the cluster
   summary counts, the search palette (where PER_KIND of 5 could be 5 copies of
   3 guests), the alert target expansion (an "any vm" rule fired and NOTIFIED
   once per enrolled host for one breach), and the network topology route, which
   read the same guest twice and read it at the wrong node for every host but the
   owning one, dropping that whole host's attachments into `errors`. Verified on
   the real cluster: two mirror rows, one API row attributed to the owning host,
   `vms: 1` in the summary, and `/network/bridges` returning each guest once with
   no errors.

   The helper moved to `services/hostclient.py` alongside `cluster_scope` so
   `services/alerts.py` could use it without importing from the API layer;
   `api/deps.py` re-exports both.

   **The App side is closed too, 2026-08-18.** `apps.node_name` follows the CT
   every cycle and `guest_node` needed no change, since it already reads
   `node_name` off whatever row it is given. Verified on the real app by making
   its row claim the wrong node: the preflight followed the row, and the next poll
   corrected it back.

6. **Hardware check 12 is closed, and it cost the health model a column.**
   Actual quorum loss was reached on 2026-08-18. The write half passed (PVE's
   own "cluster not ready - no quorum?" names the cause and the job fails in
   seconds), the health half failed exactly as doc 12 predicted: every host read
   `connected`, the test endpoint returned a version, and the sidebar said "All
   systems healthy" while `/etc/pve` was read-only. `hosts.quorate` now carries
   PVE's own `quorate` field and three surfaces show it. What that leaves:

   - **the stat rings, fixed:** `_pct` returned 0.0 for a total of zero, so a
     degraded poll drew calm 0% gauges and `0.0 B / 0.0 B` storage over an
     unwritable cluster. It returns None now, and the Ring component's existing
     `unknown` state (added for a failed query) covers the empty-answer case
     too;
   - **migration, fixed:** a host whose `quorate` is False is a preflight
     BLOCKER on either side, so the migration is refused before the source is
     stopped rather than after PVE rejects the write. Only False blocks: NULL is
     standalone or not yet polled. Other writes still fail at PVE, which is
     acceptable because they fail fast with PVE's own "cluster not ready - no
     quorum?" and nothing has been stopped first;
   - **alerting, fixed:** `quorum_lost` is a status metric alongside
     `host_offline` and `backup_failed`, so it needed no new machinery: no
     threshold, host-scoped, fires only when PVE said `quorate: 0`, resolves
     when quorum returns, and its message says installs and edits will fail
     rather than naming votequorum. The rule form renders from
     `/alert-rules/metrics`, so it appeared there with no frontend change.

     Verified at the unit level over a flag whose False state was itself
     hardware-verified; watching the alert fire would mean breaking the lab
     cluster a third time for little extra confidence.

7. **A linked clone can always be chosen and can never work. FIXED
   2026-08-18**, by taking the upgrade path the clone route's own `ponytail:`
   note described: `vms.template` mirrors `/cluster/resources`'s flag every poll
   cycle (refreshed, not written once, since `qm template <id>` converts a guest
   in place), the route refuses `full=false` on a non-template with a 409 naming
   templates, and the dialog disables the Linked radio instead of offering
   something that always fails. The radio is disabled and labelled rather than
   removed, so an operator who has used linked clones before sees why it is not
   available.

   Verified on hardware both ways: `qm template 100` then a linked clone through
   the app returned `exitstatus: OK` with `full: False`, and a linked clone of
   the resulting non-template guest was refused with
   `linked_clone_needs_template`.

8. **Every existing Lifecycle token predates `SDN.Use`. PROBE ADDED
   2026-08-18.** The privilege was
   added to the generated script today, along with `VM.Config.HWType`, so an
   operator who ran the old script has a token that 403s on any NIC write or VM
   create until they re-run it.

   `POST /hosts/{id}/test` now checks EVERY configured token against its own
   role, not just monitoring against `MONITORING_PRIVILEGES`, and returns
   `capability_gaps`. The Edit dialog lists them and says to re-run the script.
   Same tri-state discipline as the rest: a capability is absent when fully
   granted or unconfigured, and null when PVE refused `/access/permissions`,
   which renders as "could not check" rather than as clean.

   Deliberately not in the poll loop: it costs one `/access/permissions` per
   configured token, which is fine for an operator pressing a button and is not
   something to spend every 30 seconds per host.

   Verified on hardware both ways: with `SDN.Use` removed from node2's role the
   probe returned `{"lifecycle": ["SDN.Use"]}`, and `{}` once granted again.

   **Closed the same day: it warns without being asked.** `hosts.capability_gaps`
   (migration `f1c86b4a2d05`) stores the probe's answer, `POST /hosts/{id}/test`
   writes it as well as returning it, and the poll loop refreshes it every 30
   minutes (`CAPABILITY_GAP_INTERVAL_S`, kept in memory so a restart re-checks
   immediately). The host page shows "N tokens missing privileges" in amber
   beside the status pill, linking to Settings.

   Every-cycle was rejected on cost: it is one `/access/permissions` per
   configured token, and privileges change when an operator re-runs the setup
   script, not every 30 seconds. The probe is also best-effort in both
   directions: a failure inside it must not cost the poll cycle, since it is a
   warning about tokens rather than the poll itself.

   Verified on hardware end to end: `SDN.Use` and `VM.Config.HWType` were dropped
   from node2's role, the stored value was cleared, and the poll loop wrote
   `{"lifecycle": ["SDN.Use", "VM.Config.HWType"]}` for both hosts with nobody
   pressing anything; the chip rendered on the real page; and granting them back
   returned `{}`. Note both hosts report it, because a cluster shares one role
   definition.

---

## Networking: what exists, and the one control that was removed

Node network config (bridge create, edit, delete, stage, apply, revert) and guest
NIC editing (bridge, VLAN tag) are built. Apply is hardware-verified both ways,
including the case where it costs the node its network (doc 12 check 8).

**There is no firewall feature, and the toggle that implied one is gone
(2026-08-18).** What existed was a single per-NIC boolean that flips PVE's
`firewall=1` flag. Nothing else: no rules, no security groups, no aliases, no IP
sets, at guest, node or cluster level. So the switch could turn filtering ON for a
guest and this product had no way to then permit any traffic, which is a control
that can strand a guest with no in-product recovery.

The test applied was simple: nobody could state what the toggle would do without
going and checking PVE's default policy first, and if we cannot say it, an operator
cannot. Hidden rather than fixed, because making it safe means rule management,
which is a feature to scope deliberately rather than a gap to patch.

`NicIn.firewall` stays in the API so a caller can clear a flag PVE set, and the
NIC form still SHOWS the flag when it is on, because a guest whose traffic is being
filtered by something invisible is worse than one line of explanation. The rules
live in Proxmox's own web UI for now. Revisit on demand.

**The apply preview does not exist yet, and there is a rule waiting for it.**
`GET /network/bridges` returns interfaces and nothing else, so nothing previews an
apply today. Whoever builds one must show PVE's own `changes` diff rather than a
rendering of the operator's edit: staging one unused bridge on real hardware made
PVE rewrite unrelated stanzas in the same `.new` file, and all of them get promoted
by the same Apply (doc 12 check 8). The rule is stated at the site in
`api/network.py` so it cannot be missed by whoever gets there.

**And an apply that fails is genuinely ambiguous, which the UI now says.** A
network change can cut the connection carrying it, so the request fails while the
change has fully taken effect: on hardware the very same UPID reported TASK OK once
the node came back. The toast used to read "the node was not changed", which is the
one reading that sends an operator to re-apply something that already applied. It
now says the apply did not complete from here and may still have taken effect, and
the job transcript says the same BEFORE the call, so the warning survives even when
the job never writes another line.

**Guest addressing: containers editable, VMs read-only (2026-08-18).** PVE's own
schemas decided the split, read off the lab rather than from memory:
`pct set --net[n]` carries `ip=<IPv4/CIDR|dhcp|manual>`, `gw=`, `ip6=`, `gw6=`,
while `qm set --net[n]` has no address field at all. A VM's address is
`--ipconfig[n]`, which PVE labels cloud-init.

So a container can be given a static address, DHCP, manual, or have it cleared,
and it is applied for real. A VM cannot: `ipconfigN` is inert unless the VM has a
cloud-init drive AND something in the guest reads it, and Windows has no
cloud-init (Cloudbase-Init is a third-party port), which nothing out here can
detect. Writing it would be a config change with no stateable effect, so the route
refuses it with the reason. What a VM shows instead is what its QEMU guest agent
reports it actually has, and `null` renders as unknown rather than as "no
address", because no agent means no answer.

**Closed 2026-08-19, and not the way it was framed.** The open item was
"writing `ipconfigN` for a Linux VM that does have a cloud-init drive". Probing
a real PVE 9.2.10 first (doc 12) turned up a cheaper answer to the question the
write was meant to serve, which was only ever "show the operator the VM's
address".

What a throwaway VM with a cloud-init drive returns from a plain config read,
no guest agent anywhere:

| configured | what PVE reports |
|---|---|
| static | `ipconfig0: ip=192.168.50.77/24,gw=192.168.50.1` |
| DHCP | `ipconfig0: ip=dhcp`, the literal word |

So for a STATIC cloud-init VM, Proxmox already knows the address and Proxploy
simply was not reading it. For a DHCP VM it does not and cannot: PVE is not the
DHCP server and never sees the lease. The only other source is the guest agent,
which is the same `network-get-interfaces` call the Proxmox web UI's Summary
panel makes, and which `agent_addresses()` has always made.

**Built instead: the read, not the write.** `GET /network/bridges` reports one
`addresses` field per VM NIC. The agent first, because it reports what the guest
HAS; the static cloud-init address second, because that is what PVE was ASKED to
give it; null when neither knows, which the UI renders as no address block at
all rather than as an explanation nobody asked for.

Three things the hardware probe settled that guesswork would not have:

- The drive is detected by the volume name `vm-<vmid>-cloudinit`, not by "the
  config mentions cloudinit". The loose check also matched the probe VM's own
  `name`.
- `ipconfigN` on a VM with no cloud-init drive is stored happily by PVE and does
  nothing, so it is ignored rather than reported. Reporting it would invent an
  address for a guest with no way to receive one.
- The index pairs: `net1` takes `ipconfig1`.

**The write stays unbuilt, deliberately.** A static `ipconfigN` is what was
requested, not what the guest took, and a Windows guest ignores it entirely
without the third-party Cloudbase-Init. Reading it is honest because the agent
outranks it whenever the agent answers; writing it would put Proxploy back to
promising an effect it cannot confirm. If it is ever wanted, it still needs the
"takes effect on next boot" story and the Windows caveat.

## Summary table

| # | Risk | Likelihood | Impact | Posture |
|---|---|---|---|---|
| 1 | Root script execution on nodes | Medium | High | Provenance + consent + audit; no sandbox claims |
| 2 | Non-clustered migration downtime | High | Medium | Backup/restore path, honest UX, safe rollback |
| 3 | SSH trust hurdle vs. agent cost | Medium | Medium | Agentless default; agent later behind executor seam |
| 4 | SQLite metric write load | Medium | Medium | WAL + batching + rollups; Postgres/VM seams |
| 5 | community-scripts drift/licensing | High | Medium | Versioned ingest, pinning, license verify at import |
| 6 | Entitlement free-riders | High | Low–Med | Accepted; signed tokens + fairness, no DRM; closed |
| 7 | PVE 8/9 API drift | High | Medium | Version-aware client layer + CI matrix |
| 8 | One-CT rule vs. upstream patterns | Medium | Medium | Classify at ingest; exclude honestly; no grouping |
| 9 | Master-key loss | Medium | High | Backup guidance, rotation, recovery runbook |
| 10 | Self-update failure | Medium | High | Snapshot + switch-over + rollback; manual path always works |
| 11 | Backups list cap hides an older datastore's host id | Low | Low | Accepted; nullable already, degrades to null not to a wrong host |
| 12 | An owner can clear the audit log | Low | High | Owner-only + typed confirmation + the clear is itself audited; evidence, not prevention |

Open decisions carried: admin-approval policy for installs (1), delta
pre-copy migration (2), agent timing (3), Postgres recommendation threshold
(4), hosted catalog mirror timing (5), PVE EOL support window (7), app-group
cosmetics (8), recovery kit (9), release signing key (10). Each names the
data that resolves it; none blocks the build sequence.
