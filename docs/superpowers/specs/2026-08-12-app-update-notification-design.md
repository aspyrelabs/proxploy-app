# Telling someone their apps have updates

**Date:** 2026-08-12
**Status:** agreed, not started. Queued for the next session.

## The gap

`apps.update_available` is set correctly and rendered correctly: an amber
`UPDATE` tag on the app card, and the update panel. But nothing ever tells you
it happened. You find out by looking.

That is worse than it sounds, because of when the value changes.
`mark_updates_available` runs in exactly one place, at the end of the
`catalog.refresh` job, and that is the only moment the answer can change. So
updates appear silently, at a moment the operator has no reason to be looking,
and then wait to be noticed.

The product now has somewhere to put this. The notification tray is a single
surface anchored to the bell, it holds job and action notifications together,
and dismissals persist per user, so a notification here is seen once and stays
dismissed.

## What to build

When a catalog refresh finishes and the number of apps with updates is greater
than zero, raise one notification in the tray:

> **N apps have updates**

with a link to the list of apps that have them.

One notification, not one per app. A refresh that marks twelve apps must not
produce twelve cards.

## Where it hooks in

`proxploy/services/catalog.py::refresh_catalog` already calls
`mark_updates_available` and already receives the counts back:

```python
counts = await asyncio.to_thread(_mark)
result["updates_marked"] = counts["marked"]
result["updates_cleared"] = counts["cleared"]
ctx.log(f"{counts['marked']} app(s) have an update available")
if counts["marked"] or counts["cleared"]:
    app.state.bus.publish("resource", {"type": "app", "change": "list"})
```

So the number is already computed, already logged, and already triggers an SSE
publish. The notification is a small addition at a point that already knows
everything it needs.

## Open questions for whoever picks this up

- **`marked` counts newly marked apps, not the total with updates outstanding.**
  Decide which number the notification should carry. "3 apps have updates" when
  nine are actually pending would be misleading; "9 apps have updates" fired
  because 3 changed may be the more useful message.
- **A refresh that marks nothing must stay silent.** No "0 apps have updates".
- **Repeat refreshes must not re-notify** for the same apps if the operator has
  already dismissed the card. Dismissals persist per user now, and the tray
  deduplicates job backed items by job id; an update notification is not job
  backed, so it needs its own identity to dedupe on.
- **Where the link goes.** `/apps` exists but shows everything. The list needs to
  be filtered to apps with `update_available` set, which may mean a filter the
  apps route does not have yet.
- **Severity.** Probably `info`. An available update is not a warning.

## Constraints

- No em dashes anywhere. `frontend/src` is at zero and stays there.
- `notify.inapp` gates the notification surface, not the data. That check does
  not move.
- One notification per refresh, never one per app.
