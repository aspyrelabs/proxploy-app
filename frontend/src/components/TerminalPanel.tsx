import { useEffect, useRef } from 'react'

export type TermLine = { stream: string; message: string }

// Doc 06 §c: log panels stay #0a0e14 in BOTH themes. Do not swap these for
// theme tokens, and do not wire them to the Console setting either: this is a
// transcript, not a terminal. A job log that changed colour under the operator
// because they set their SHELL to Solarized Light would be a surprise, and
// there is no per-panel control to change it back with. The interactive
// console (terminal/Terminal.tsx) is the one that follows that setting.
const STREAM_CLASS: Record<string, string> = {
  stdout: 'text-text-2',
  stderr: 'text-red',
  progress: 'text-blue',
  status: 'text-amber',
}

/** Strips ANSI color/cursor escape sequences before a line is rendered.
 *
 *  community-scripts installs print raw ANSI (color codes, spinner cursor
 *  moves); the API forwards those bytes as-is, correctly, because a real
 *  terminal would render them as color. The browser does not interpret ESC,
 *  so left alone a line like `\x1b[m\x1b[1m\x1b[32mRAM Size: \x1b[4;92m2048
 *  MiB\x1b[m` shows the bracket codes as literal text. This is the one place
 *  every log consumer (JobLog, AppLogs) renders a line through, so the strip
 *  happens once here rather than at each call site.
 *
 *  The ESC is REQUIRED, not optional: community-scripts logs are full of
 *  ordinary bracketed text with no ESC in front of it -- `[INFO] installing
 *  packages`, `[OK] done`, `msg_ok [ERROR] failed`. A leading `\x1b?` would
 *  eat the `[` of that real content as if it were a color code, mangling
 *  lines that were never ANSI. Requiring the ESC gives the same result on
 *  the real ANSI case above and leaves every plain `[...]` line untouched. */
function stripAnsi(s: string): string {
  // eslint-disable-next-line no-control-regex -- the ESC (0x1b) IS what this matches
  return s.replace(/\x1b\[[0-9;]*[A-Za-z]/g, '')
}

/** Static-mode log panel (doc 06 `TerminalPanel`). Live mode = xterm.js, Phase 5.
 *
 *  `height` is a maxHeight: the box is already as short as its content and only
 *  starts scrolling past this. 'fill' hands that decision to a flex parent
 *  instead, for the log dialog, which sizes ITSELF to the transcript and needs
 *  the panel to take whatever is left under the 80vh cap. min-h-0 is what lets
 *  flexbox shrink it that far (a flex child's default min-height is auto, which
 *  refuses to go below its content); scrolling is already on, so the panel goes
 *  on following the newest line rather than handing that job to an outer
 *  scroller that cannot autoscroll. */
export function TerminalPanel({ lines, height = 260 }:
  { lines: TermLine[]; height?: number | 'fill' }) {
  const fill = height === 'fill'
  const box = useRef<HTMLDivElement>(null)
  const stick = useRef(true)

  useEffect(() => {
    const el = box.current
    if (el && stick.current) el.scrollTop = el.scrollHeight
  }, [lines])

  return (
    <div
      ref={box}
      onScroll={(e) => {
        const el = e.currentTarget
        stick.current = el.scrollHeight - el.scrollTop - el.clientHeight < 24
      }}
      style={{ background: '#0a0e14', maxHeight: fill ? undefined : height }}
      className={`overflow-auto rounded-ctl border border-line-soft p-3 font-mono text-[12.5px] leading-[1.7]${fill ? ' min-h-0' : ''}`}
    >
      {lines.length === 0 ? (
        <div className="text-text-3">No output yet.</div>
      ) : (
        lines.map((l, i) => (
          <div key={i} className={STREAM_CLASS[l.stream] ?? 'text-text-2'}>
            {stripAnsi(l.message)}
          </div>
        ))
      )}
    </div>
  )
}
