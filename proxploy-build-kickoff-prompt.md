# Claude Code: Proxploy docs amendment + build kickoff

This file is the step **between** your finished `/superpowers:brainstorming` output and
`/superpowers:write-plan`. Its whole job is to correct the `/docs` set so the plans get
written against the amended design. It does not write feature code. Give it to Claude Code
in the proxploy-app repo with the `/docs` set (00 through 11) and `proxploy-prototype.html`
present.

---

The planning set in `/docs` (00 through 11) is reviewed and approved as the basis for the
build. It is strong and internally consistent; do not relitigate the settled decisions
listed below. Your task in this pass is only to apply the amendments to the relevant docs,
run the license verification, and stop. Building happens later, through write-plan and
execute-plan, one phase at a time.

## Settled (do not reopen)

These were decided deliberately and are correct. Do not re-argue them:

- The reuse-over-reinvention discipline and the licensing rules (permissive port/link,
  copyleft arm's-length only, no BUSL/SSPL). Keep the license-verification protocol in doc 03.
- The honest trust model: App Store install equals root on the node, provenance and evidence
  rather than sandboxing. Do not add DRM, obfuscation, or telemetry.
- The entitlement design: EdDSA-signed offline tokens, roughly 30 day grace, air-gapped free
  tier, dormant all-on default, fail-closed unknown keys.
- The one-CT-per-app rule and Apps-only nav.
- The single-process, agentless, seam-based architecture and the four-property topology.
- The locked stack (Python/FastAPI/SQLAlchemy/proxmoxer; React/TS/Vite/Tailwind/shadcn/
  TanStack) and the provisional-behind-seams choices.

## Required amendments (apply to `/docs`)

### A. The executor is the highest-risk component

1. **Spike a non-root / API-first install path before committing to raw SSH-root.**
   Before Phase 4, investigate whether current community-scripts tooling exposes a
   non-interactive or API-drivable install path (env-var/silent mode, an official headless
   entrypoint, or create-CT-via-API-then-configure) that reduces or removes the need for a
   root shell. Document the finding in doc 08/11. If raw SSH-root remains necessary (likely),
   proceed, but make this spike a Phase 4 entry gate rather than an afterthought.
2. **`asyncssh` license is the first verification, before any install of it.** It is believed
   EPL-2.0 (weak, file-level copyleft): acceptable as an unmodified linked dependency,
   unacceptable to port. Verify against the repo at the pinned version and record the ruling
   in doc 03 before Phase 1 closes. If unacceptable, fall back to the system `ssh` binary at
   arm's-length, never paramiko.
3. **Isolate and over-test `executor/`.** It is the one component holding root-on-node power.
   It gets the highest test coverage in the repo (unit plus integration against a throwaway
   PVE), the tightest review bar, and a hard structural rule enforced in CI: no module outside
   `executor/` may import the SSH client or retrieve the SSH key.

### B. The core loop (catalog to install) is fragile

4. **Add an install-feasibility classifier to catalog ingest.** Not every catalog entry is
   installable under Proxploy's constraints (one CT and drivable non-interactively). Amend
   doc 01/04/11: ingest classifies each entry as installable or unsupported, the store shows
   only installable entries as installable (unsupported ones appear with an honest note plus
   an upstream link), and Phase 4's definition of done includes the true count so "300+
   scripts" is replaced with the real installable number.
5. **Prefer Proxmox bulk endpoints for polling.** Amend doc 02/04: pollers use
   `/cluster/resources` and node `rrddata` rather than per-guest calls, to avoid an API
   request storm at scale. Define a per-cycle API-call budget per host in doc 02.

### C. First-run experience has a gap

6. **Define the discovery-and-adopt flow for pre-existing CTs.** As written, a fresh install
   against a host with existing containers shows an empty Apps page until each CT is manually
   adopted. Amend doc 06 (and doc 01 `apps.adopt`): the Apps page (or a clearly linked panel)
   surfaces discovered-but-unadopted CTs with a bulk Adopt affordance and catalog-match
   suggestions, so a new user with existing infra sees their containers immediately.

### D. proxploy-api needs more than a dormant resolver

7. **Treat the Ed25519 signing key and the license data model as launch-critical even while
   dormant.** Amend doc 07/09: proxploy-api's private signing key must live in a KMS or a
   root-only file with an offline backup and a documented rotation runbook that survives an
   app release (rotation ships a new public key in the app's bundled key set, so build the
   multi-key `kid` set into the app from Phase 1). Define the `licenses` and issued-token
   tables now. A lost or leaked signing key means re-releasing the app, so this is not
   deferrable to "when we sell."

### E. Correctness and consistency

8. **Self-management guardrail.** Amend doc 02/08: Proxploy must refuse destructive actions
   (stop, delete, migrate) against its own CT and host when it can detect them, or at minimum
   require a typed confirmation with an explicit warning. A tool that can stop its own CT can
   brick its own recovery.
9. **Reconcile the dependency lists.** doc 06 introduces cmdk, sonner, CodeMirror 6, and
   TanStack Table; none appear in doc 03. Add them to doc 03 (all believed MIT, verify) so the
   license audit covers everything actually shipped.
10. **Make the arming nuance explicit.** Amend doc 07: arming the paid tier is pure proxploy-api
    config, but defining the free-tier ceiling ships in the app's built-in default map and
    therefore rides an app release. State this plainly so "arming is config, never refactor" is
    not read as "no app release ever needed."

### F. Build-process requirements (for the plans, not this pass)

11. **Test infrastructure is a Phase 1 deliverable.** The Phase 1 plan must produce: (a) a
    proxmoxer fake/fixture layer so unit tests and most development run with no live PVE; (b) an
    integration path against a disposable PVE (used in CI for the PVE 8.latest / 9.latest matrix
    from doc 11); and (c) the app-to-api entitlement contract test wired in both repos from day
    one. Add these to doc 10 Phase 1.
12. **Reuse the existing proxmoxer engine.** `backend/proxploy/services/proxmox.py` must adapt
    the existing lab-cluster-deploy proxmoxer module (CT lifecycle, cluster/node/guest reads,
    migration calls), not be written from scratch. That module will be provided as a labeled
    reference; put all version-branching (PVE 8 vs 9) in this one layer. Note this in doc 02/03.

## What to do in this pass, then stop

1. Apply amendments 1 through 12 to the relevant `/docs` files. Keep the brief (doc 00) at the
   top of the hierarchy: if any amendment touches the brief, change the brief first, then the
   topic doc.
2. Run the doc-03 license-verification protocol for every Phase 1 dependency, `asyncssh` first,
   recording verified dates and the EPL-2.0 ruling.
3. **Stop and report the doc diffs** for review. Do not scaffold or write feature code in this
   pass. The next step is `/superpowers:write-plan` for Phase 1, which will read these amended
   docs.

## After this pass (your workflow, not Claude Code's job here)

- Review the doc diffs.
- Run `/superpowers:write-plan` for **Phase 1 only** (doc 10 order), pointing at the amended
  `/docs`. In the write-plan request, require that the security non-negotiables become explicit,
  testable acceptance criteria on the relevant tasks: scoped tokens never root, credentials
  encrypted at rest, every route wrapped in auth plus RBAC plus audit plus an entitlement check,
  and the executor-isolation rule from amendment 3. The review gate can only enforce what the
  plan states.
- Run `/superpowers:execute-plan`, then review at the end of Phase 1 before planning Phase 2.
  Plan one phase at a time; do not write all nine phases up front.
