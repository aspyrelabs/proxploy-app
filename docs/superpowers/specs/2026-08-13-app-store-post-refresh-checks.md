# App Store, after the first real refresh

**Date:** 2026-08-13
**Status:** queued, not started. Two checks on the catalog expansion that landed
in commit `f465d99`, now that it has run against the live upstream repo.

Both are investigation first. Report which of the two failure modes is in play
before changing code.

## 1. The "584 checking" state

The catalog expansion deliberately does not fetch the `ct/` plus `install/`
script pair during discovery. That would be roughly 1,168 raw fetches. Instead a
script pair is fetched when a card is opened or an install starts, and a low
priority background pass fills in the installable versus unsupported badges
after the store is already usable.

So a store showing 584 entries in a "checking" state immediately after a refresh
is the **expected initial state**, not a bug. It is a bug only if it never
resolves.

Report:

- Is the background pass actually scheduled and running after a refresh?
- How many of the 584 have resolved to installable or unsupported so far?
- How long does a full pass take end to end?

If it is not running, or is stuck at 584 checking, find out why. Likely
candidates worth eliminating in order: the pass is never scheduled, it is
scheduled but its job never starts, it starts and dies on the first failure
instead of continuing, or it is rate limited by `raw.githubusercontent.com` and
backing off silently.

## 2. Missing logos, descriptions and categories

This is the larger question of the two.

Enrichment (display name, description, logo, category) comes from
community-scripts.org's Next.js hydration payload. That is an undocumented
internal, it 403s without a browser User-Agent, and it has no rate-limit
contract. The parser for it was **tested only against a synthetic fixture and
never against a live fetch**, which the implementing agent flagged at the time.

So there are two candidate explanations and they need different fixes:

- **Parser mismatch.** The live payload's shape differs from the fixture, so
  enrichment runs and finds nothing. Entirely plausible: the fixture was written
  from documentation of the shape, not from a live response.
- **Not triggered.** The parser is fine but enrichment is never invoked, or is
  invoked at a point that does not persist its result.

**Do one real live fetch. One probe, not 584.** Compare the actual payload to
what the parser expects, and report which of the two it is **before** changing
code. Then fix that one.

Include a couple of concrete before and after example cards in the report, so
the difference is visible rather than asserted.

## Constraints, unchanged from the original brief

- Enrichment stays **best effort**. A card with no logo, description or category
  must still render cleanly with name, type and an initial tile, exactly as it
  does today. Store appearance must never depend on the scrape.
- If the payload 403s, rate limits or lags the repo, degrade silently.
- Scripts stay the source of truth. Enrichment is a bonus layer on top.
- The refresh stays at **2 `api.github.com` requests**, flat, at any catalog
  size. There is a test asserting the call count does not scale with the number
  of entries; it must keep passing.
- Respect rate limits while investigating. The dev machine shares the same 60
  requests per hour as production.
- No em dashes anywhere.

## Context worth carrying in

- `.superpowers/sdd/catalog-expansion-report.md` has the implementation detail,
  including the fifth dual-variant slug (`runtipi`) found during live
  verification and the dynamic collision detection that replaced the hardcoded
  list of four.
- `.superpowers/sdd/app-store-catalog-plan.md` has the original investigation:
  discovery via the git trees API, the type-by-directory mapping, and why the
  old `frontend/json` metadata directory no longer exists upstream.
- Both live in a gitignored directory, so they are local to the machine that
  produced them.
