import { Button } from './ui/button'
import { Dialog } from './ui/dialog'

/**
 * What backups can and cannot do here, said once before the operator relies on
 * them. Every limit below is Proxmox VE's own `vzdump`, not a Proxploy choice,
 * and the card says so: someone who reads "no incremental backups" on our page
 * will otherwise conclude we skipped the feature.
 *
 * Acknowledged per browser, the same way lib/sidebar.ts and lib/console-prefs.ts
 * keep their state. Not a server-side per-user flag: this is a "have you read
 * this" note, and the worst case of losing it is reading it again. Say so if a
 * fleet ever wants it recorded centrally.
 */
const ACK_KEY = 'proxploy.backups.limits-ack'

export function limitsAcknowledged(): boolean {
  try {
    return localStorage.getItem(ACK_KEY) === 'yes'
  } catch {
    return false   // private mode / storage blocked: show it, never crash the page
  }
}

function acknowledge(): void {
  try {
    localStorage.setItem(ACK_KEY, 'yes')
  } catch {
    /* nothing to do: the card simply appears again next time */
  }
}

/** Each limit, and what Proxploy does about it. A list of four things that are
 *  wrong leaves the reader with a problem and no move; one of these four we
 *  genuinely answer, and saying plainly which one is the point of the card. */
const LIMITS: { limit: string; body: string; answer: string }[] = [
  {
    limit: 'Every backup is a full copy',
    body: 'Proxmox writes the whole guest every time. Ten nightly backups of a '
      + '40 GB machine take ten times the space.',
    answer: 'Cannot fix it, that is how vzdump writes. Proxploy gives you retention '
      + 'rules and a preview that shows exactly what a rule would delete, before it '
      + 'deletes it.',
  },
  {
    limit: 'Nothing checks that a backup is readable',
    body: 'Proxmox VE never reads an archive back after writing it. One can sit in '
      + 'this list looking fine and fail when you need it.',
    answer: 'Checks them for you. Verify reads the whole archive and checks its '
      + 'structure. Test restore goes further: it restores the backup into a spare '
      + 'id, confirms Proxmox finished, then deletes the copy, without ever touching '
      + 'your real machine. Run either from a backup’s row, after every backup, '
      + 'or on a schedule.',
  },
  {
    limit: 'You restore a whole machine, not one file',
    body: 'There is no way to open a backup and pull a single file out of it.',
    answer: 'Cannot fix it. A vzdump archive carries no file index to browse.',
  },
  {
    limit: 'Backups are not encrypted',
    body: 'Anyone who can read the share they sit on can read what is inside them.',
    answer: 'Cannot fix it. Whatever the share and the filesystem give you is what '
      + 'you have.',
  },
]

export function BackupLimitsDialog({ onClose, onAgree }:
  { onClose: () => void; onAgree: () => void }) {
  return (
    <Dialog title="Before you rely on these backups" width={560} onClose={onClose}>
      <p className="mt-2 text-[13px] text-text-2">
        Proxploy runs your backups through Proxmox VE&apos;s built-in tool. It is
        dependable and it is what most home setups use, but there are four things
        it cannot do. These are limits of Proxmox VE itself, not of Proxploy.
      </p>

      <dl className="mt-4 space-y-3">
        {LIMITS.map((l) => (
          <div key={l.limit}>
            <dt className="text-[13px] font-semibold text-text">{l.limit}</dt>
            <dd className="mt-0.5 text-[12.5px] text-text-3">{l.body}</dd>
            <dd className="mt-1 text-[12.5px] text-text-2">
              <span className="text-text-3">Proxploy: </span>{l.answer}
            </dd>
          </div>
        ))}
      </dl>

      <p className="mt-4 rounded-ctl border border-amber/30 bg-amber-dim p-3 text-[12.5px] text-text-2">
        All four go away with <strong className="text-text">Proxmox Backup Server</strong>,
        a free companion product from the same people. It stores only what changed
        since the last run, checks every archive, restores single files, and encrypts
        what it writes. The checks Proxploy runs are not as thorough as its own: PBS
        verifies every block against a stored digest on its own schedule, instead of
        reading the whole archive back over the network each time. If your backups
        matter, it is worth the afternoon it takes to set up. Add it here with
        &quot;Add storage&quot; once it is running.
      </p>

      <div className="mt-5 flex justify-end gap-2">
        <Button variant="ghost" onClick={onClose}>Remind me later</Button>
        <Button onClick={() => { acknowledge(); onAgree() }}>I understand</Button>
      </div>
    </Dialog>
  )
}
