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

## Open at the end of 2026-08-16

Cluster peer auto-enrolment shipped in seven phases today. What it leaves open:

1. **None of it has met real Proxmox.** Every node in every test is a
   `FakePVE`, including the browser tests. Two things a fake cannot answer:
   whether the `ip` a node reports in `/cluster/status` is one the API actually
   answers on, and whether each node presents the certificate the panel shows
   before you tick its box. Both are cheap to check against a real two node
   cluster and expensive to be wrong about, since the second one is what the
   pinning rests on. Check them before anyone relies on the feature.

2. **The certificate swap refusal has no browser coverage, deliberately.** The
   panel echoes back the fingerprint it displayed and enrolment refuses a peer
   that presents something else, but nothing reachable from a browser can
   change what the fake presents between those two moments. Faking it would
   mean a fixture that lies about how certificates change. Covered against the
   real handler in `test_hosts_peers.py`, and worth one manual check on real
   hardware alongside item 1.

3. **`journey.spec.ts:163` fails.** VM create never shows "succeeded" within
   twenty seconds. Pre-existing from the VM wizard work of 2026-08-15,
   confirmed identical against the commit before today's. It matters more than
   it looks: the `chromium` Playwright project depends on the `journey`
   project, so this one failure skips 14 other tests and the suite needs
   `--no-deps` to run at all.

4. **Duplicate React key at `frontend/src/routes/store.tsx:372`.** The category
   skeleton uses its class string as the key over a list where `w-20` and
   `w-16` each appear twice. Only fires when the catalog query is slow enough
   to render the skeleton, which is why it is intermittent, and it is what
   `smoke.spec.ts` currently fails on.

Still carried from 2026-08-15: the swallowed error detail, the node shell
toggle that can be enabled without `Sys.Console`, the SSH enrolment checkbox
granting the key silently, and the history purge decision on the committed
`master.key`.

---

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

Open decisions carried: admin-approval policy for installs (1), delta
pre-copy migration (2), agent timing (3), Postgres recommendation threshold
(4), hosted catalog mirror timing (5), PVE EOL support window (7), app-group
cosmetics (8), recovery kit (9), release signing key (10). Each names the
data that resolves it; none blocks the build sequence.
