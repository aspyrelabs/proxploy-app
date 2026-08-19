import { useState } from 'react'
import {
  CONSOLE_THEMES, FONT_SIZE_RANGE, readConsolePrefs, setConsolePrefs,
} from '../lib/console-prefs'

const label = 'mb-1 block text-[11px] uppercase tracking-wide text-text-3'
const input = 'w-full rounded-ctl border border-line-soft bg-elev px-3 py-2 text-[13px]'

const SIZES = (() => {
  const [min, max] = FONT_SIZE_RANGE
  const out: number[] = []
  for (let n = min; n <= max; n += 1) out.push(n)
  return out
})()

/** Console appearance, stored per browser (lib/console-prefs.ts).
 *
 *  No entitlement gate and no role check: how a terminal is drawn on this
 *  machine is nobody's decision but the person looking at it, the same status
 *  as the app theme toggle in the topbar.
 *
 *  Applies to the INTERACTIVE console (node shell, app console). The static
 *  log panels stay dark whatever is chosen here: they are transcript, not a
 *  terminal, and they have no setting to disagree with.
 */
export function ConsoleCard() {
  const [prefs, setPrefs] = useState(readConsolePrefs)
  const theme = CONSOLE_THEMES[prefs.theme].theme

  const save = (next: typeof prefs) => {
    setPrefs(next)
    setConsolePrefs(next)
  }

  return (
    <section className="rounded-card border border-line-soft bg-panel p-5">
      <h2 className="mb-1 font-display text-[15px] font-semibold">Console</h2>
      <p className="mb-4 text-[12.5px] text-text-3">
        How the node shell and app console are drawn on this browser. An open
        console keeps the settings it started with; reopen it to apply a change.
        A VM console is not affected: that one is a remote screen Proxmox draws
        over VNC, so it has no text of its own to theme or resize.
      </p>

      <div className="grid gap-4 sm:grid-cols-2">
        <div>
          <label className={label} htmlFor="console-theme">Theme</label>
          <select id="console-theme" className={input} value={prefs.theme}
            onChange={(e) => save({ ...prefs, theme: e.target.value })}>
            {Object.entries(CONSOLE_THEMES).map(([id, t]) => (
              <option key={id} value={id}>{t.label}</option>
            ))}
          </select>
        </div>
        <div>
          <label className={label} htmlFor="console-font-size">Font size</label>
          <select id="console-font-size" className={input} value={String(prefs.fontSize)}
            onChange={(e) => save({ ...prefs, fontSize: Number(e.target.value) })}>
            {/* The stored default is 12.5, which is not a whole number and so
                is not in the list below; offer it so the current value is
                always selectable rather than silently reading as 12. */}
            {[...new Set([prefs.fontSize, ...SIZES])].sort((a, b) => a - b).map((n) => (
              <option key={n} value={String(n)}>{n}</option>
            ))}
          </select>
        </div>
      </div>

      {/* A colour choice you cannot see before saving is a guess. */}
      <div className="mt-4 rounded-ctl border border-line-soft p-3 font-mono"
        style={{ background: theme.background, color: theme.foreground,
                 fontSize: `${prefs.fontSize}px` }}>
        <div><span style={{ color: theme.green }}>operator@node1</span>:~$ uptime</div>
        <div>14:22:07 up 9 days,  2:11,  1 user,  load average: 0.14</div>
        <div><span style={{ color: theme.red }}>error</span>{' '}
          <span style={{ color: theme.yellow }}>warning</span>{' '}
          <span style={{ color: theme.blue }}>info</span></div>
      </div>
    </section>
  )
}
