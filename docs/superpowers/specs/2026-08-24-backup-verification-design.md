# Backup verification and test restore

Date: 2026-08-24
Status: approved for planning

## Why

Proxmox VE's `vzdump` never verifies what it writes. `verify_state` is written
by Proxmox Backup Server and by nothing else, so on a plain NFS, CIFS or
directory store every archive reads "unverified" for its whole life, and the
Backups page cannot answer the only question that matters about a backup: would
it restore?

PVE ships two tools that do answer it, neither exposed through its HTTP API:

- `vma verify` reads a VM archive and checks its internal structure.
- A restore into an unused vmid proves the archive end to end.

This wires both into Proxploy for the setups that have no PBS.

## Decisions taken during design

1. **Three triggers**: a per-archive action, an optional check chained after a
   backup run, and a schedulable sweep.
2. **The scratch guest is destroyed immediately** when a test restore finishes.
   It is never started and never kept.
3. **Containers get a lighter check.** `vma verify` is VM-only; a CT archive is
   read through `zstd` and `tar`, which catches truncation and bit rot but has
   no per-block digest. The UI names it as the lighter check it is.
4. **One meaning for "verified".** Our results write `backups.verify_state`,
   the same column PBS's own verdict lands in. There is no second vocabulary.
5. **PBS wins, per archive.** An archive on a `pbs`-type datastore gets no
   Proxploy check: PBS verifies it properly and our weaker check would only
   muddy the column. An archive on NFS/CIFS/dir on the same cluster still gets
   ours.

## Settled after review

- **No entitlement key.** Both actions ship ungated. Everything is open today,
  and inventing `backups.verify` now would be guessing at a plan boundary
  nobody has drawn. The routes still carry their normal `authorize()` checks.
- **Test restore target storage**: defaults to the datastore the archive names,
  changeable in the dialog with the same picker the backup dialogs use.

## Job phrasing

Neither kind gets a neutral label plus a status word: "Backup Verify Done" is
the thing this product stopped saying. They join `JOB_PHRASE` in
`frontend/src/lib/activityDisplay.ts`, which already carries the five existing
backup kinds:

| Status | `backup.verify` | `backup.test_restore` |
|---|---|---|
| queued | Check Queued | Test Restore Queued |
| running | Checking Backup | Test Restore Started |
| succeeded | Check Finished | Test Restore Completed |
| failed | Check Could Not Run | Test Restore Failed |
| canceled | Check Stopped | Test Restore Stopped |
| interrupted | Check Interrupted | Test Restore Interrupted |

"Check Finished" and "Check Could Not Run", deliberately, rather than Passed
and Failed: a verify job's success means the check RAN, and whether the archive
passed is the row's own verdict. A toast reading "Verify Failed" over an
archive that is merely corrupt, or "Verify Succeeded" over one that just failed
its check, would state the opposite of what happened. The four words are worth
it.

## Job kinds

### `backup.verify`

Read-only. Runs over SSH, because neither tool has an HTTP endpoint.
`executor/ssh.py::SSHExecutor.run_for_host` already gives root, streamed output
and a timeout; `services/appstore.py` is the precedent caller.

Steps:

1. Resolve the archive to a filesystem path with `pvesm path <volid>`, never by
   assembling `/mnt/pve/<store>/dump/...`. The mount point is the storage
   plugin's business and a guessed path breaks the first time someone uses a
   non-default one.
2. Choose the command from the guest type and the extension:
   - VM: `zstdcat <path> | vma verify -v -`, with `lzop -dc` or `cat` in place
     of `zstdcat` for `.lzo` and uncompressed `.vma`.
   - CT: `zstdcat <path> | tar -tf - >/dev/null`, same substitution.
3. Stream stdout and stderr into the job log line by line.
4. Exit status 0 is `ok`, anything else is `failed`. Both are written to
   `verify_state` with `checked_at`, and both are a *finished* job: a failed
   verification is a successful check that found a bad archive, so the job
   succeeds and the archive is marked failed. A job only fails when the check
   could not be run at all (no SSH key, host unreachable, `pvesm path` empty).

### `backup.test_restore`

1. Preflight: free space on the target store must exceed the archive's
   `size_bytes`. Refuse with a plain message rather than filling the pool.
2. Pick a scratch vmid: the lowest free id at or above 900, from the poller's
   guest list. PVE may still reject it if something took the id in between; one
   retry with the next free id, then fail.
3. Restore with the existing `services/proxmox.py::restore_guest`, the same call
   the real restore path uses, which returns a UPID. `qmrestore` was considered
   and rejected: it is the same operation with no UPID, so no task log, no
   progress and no cancellation.
4. Never start the guest. Never touch its network.
5. Destroy it in a `finally`. If the destroy fails, the job FAILS naming the
   vmid and the node, because a silent orphan holding a disk is worse than a
   red job.
6. A successful restore-and-destroy writes `verify_state = ok` and
   `checked_at`, exactly as a verify does.

### Serialisation

A verify reads the whole archive off the share; 40 GB over 1GbE saturates the
link for six minutes. One check job at a time per host, guarded the way
`backupjobs.py::sync_in_flight` already guards sync. Both kinds are
cancellable, and cancelling a test restore still runs the destroy.

## Storage of the verdict

`backups.verify_state` is reused, plus one new column:

```
checked_at  DateTime | None   -- when Proxploy last checked this archive
```

One Alembic migration under `proxploy/migrations/versions/`.

**Required change to sync.** `sync_host_backups` currently writes
`verify_state = (item.get("verification") or {}).get("state") or "none"` on
every sweep, so a store that reports no verification overwrites our result with
`"none"` within fifteen minutes. It will write the field only when upstream
actually reports a `verification` object, and leave it untouched otherwise.
That keeps PBS authoritative where PBS speaks and leaves our value alone where
nothing else does.

## Surfaces

- **Recent backups row**: Verify and Test restore beside Restore and Delete.
  Disabled on a `pbs`-type archive with "Proxmox Backup Server verifies this one
  itself." The existing Status column already renders verified / failed /
  unverified and now reflects our checks too.
- **After a backup**: a checkbox in the Run now dialog and in the schedule form,
  "Check the archive afterwards", carried as `params.verify` on the
  `backup.run` job. The run handler enqueues a SEPARATE `backup.verify` job
  after its resync, rather than verifying inline: a backup that succeeded must
  read as succeeded even when the check that follows it fails, and the two have
  very different durations.
- **Scheduled sweep**: `backup.verify` joins `SCHEDULABLE` in
  `frontend/src/api/schedules.ts`, so New job can create "Verify backups, Sunday
  3am". Params: `host_id`, optional `storage`, and a cap on how many archives one
  sweep walks. It takes unverified archives on non-PBS stores, oldest first.
- **Limitations card** (`components/BackupLimitsDialog.tsx`) is restructured, not
  edited. Today it is a list of four things that are wrong, which leaves the
  reader with a problem and no move. It becomes four pairs: what Proxmox VE
  cannot do, and what Proxploy does about it. Two of the four we genuinely help
  with, two we cannot, and saying which is which is the point of the card.

  | Proxmox VE's limit | What Proxploy does |
  |---|---|
  | Every backup is a full copy. Ten nightly backups of a 40 GB machine take ten times the space. | Cannot fix it, it is how vzdump writes. Proxploy gives you retention rules and a prune preview that shows exactly what a rule would delete before it deletes it. |
  | Nothing checks that an archive is readable. It can sit in this list looking fine and fail when you need it. | **Checks them for you.** Verify reads the whole archive and checks its structure: Proxmox's own `vma verify` for a virtual machine, a full read of the compressed tar for a container. Test restore goes further and restores the backup into a spare id, confirms Proxmox finished, then deletes the copy immediately, without touching your real machine. Run either from a backup's row, after every backup, or on a schedule. |
  | You restore a whole machine, not one file. | Cannot fix it. There is no file index in a vzdump archive to browse. |
  | Archives are not encrypted. Anyone who can read the share can read what is in them. | Cannot fix it. Whatever the share and the filesystem give you is what you have. |

  The card then keeps its closing panel, with one sentence added: the checks
  Proxploy runs are **not as thorough as Proxmox Backup Server's**, which
  verifies every block against a stored digest on its own schedule instead of
  reading the whole archive back over the network each time.
- **Verified · 30d**: starts reporting on PVE-only setups, because our checks
  now populate the column it reads. The "Backups completed · 30d" fallback stays
  for the case where nothing has been checked yet.

## Error handling

| Case | Behaviour |
|---|---|
| Host has no `ssh_key` credential | Job fails: "Verifying needs SSH access to the node; add it on the host." |
| `pvesm path` returns nothing | Job fails naming the volid. The archive is not marked. |
| `vma verify` exits non-zero | Job SUCCEEDS, archive marked `failed`. This is the tool working. |
| Archive gone since the list was drawn | Job fails, and the sync that follows drops the row. |
| Not enough free space for a test restore | Refused before any PVE call, with the two numbers in the message. |
| Scratch destroy fails | Job fails naming vmid and node. Never swallowed. |
| Archive is on a PBS store | Route refuses with 409; the UI never offers it. |

## Testing

- Fake SSH executor (the existing `connect_factory` seam): exit 0 and exit 1
  paths, the CT command versus the VM command, `.zst` versus `.lzo` versus
  plain, and the "no ssh key" refusal.
- Fake PVE for the restore path: scratch id skips ids in use, destroy runs on
  the success path, destroy runs on the failure path, destroy failure fails the
  job.
- `sync_host_backups` no longer clobbers a verdict when upstream reports no
  verification, and still honours PBS's when it does.
- Route tests: PBS archive refused, verdict and `checked_at` written.
- Frontend: row actions disabled with the reason on a PBS archive, the
  post-backup checkbox reaching the request body, and the schedule form
  offering the new kind.

## Out of scope

- A history table of past checks. The latest verdict is what the page shows;
  add history when someone asks to see a trend.
- Verifying PBS archives through PBS's own verify API. PBS schedules its own
  verification and owns that job.
- Booting the scratch guest or checking anything inside it. A restore that
  completes is the claim being made; "the OS came up" is a different feature.
- File-level restore. Still not possible without PBS.
