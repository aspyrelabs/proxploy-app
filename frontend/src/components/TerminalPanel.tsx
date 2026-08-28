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
  // NOT red. stderr is where community-scripts writes its hints, its spinners
  // and its own success marks: a dashy update that finished correctly painted
  // 200 lines of `find: no such file` red, because the script removes
  // node_modules while find is still walking it, and the operator reasonably
  // read that as a failed update. Dimmer, because it is secondary output, not
  // because it is bad news.
  stderr: 'text-text-3',
  progress: 'text-blue',
  status: 'text-amber',
}

/** Strips ANSI color/cursor escape sequences before a line is rendered.
 *
 *  community-scripts installs print raw ANSI and the API forwards those bytes
 *  as-is (a real terminal would render them as color); the browser does not
 *  interpret ESC, so left alone the bracket codes show as literal text. This
 *  is the one place all log consumers render a line through, so the strip
 *  lives here.
 *
 *  The ESC is REQUIRED, not optional: those logs also contain plain bracketed
 *  text like `[INFO] installing packages` with no ESC in front, and a leading
 *  `\x1b?` would eat the `[` of that real content. */
function stripAnsi(s: string): string {
  // eslint-disable-next-line no-control-regex -- the ESC (0x1b) IS what this matches
  return s.replace(/\x1b\[[0-9;]*[A-Za-z]/g, '')
}

/** Static-mode log panel (doc 06 `TerminalPanel`); live mode is xterm.js.
 *
 *  `height` is a maxHeight: the box is already as short as its content and
 *  only starts scrolling past this. 'fill' hands sizing to a flex parent (the
 *  log dialog, which sizes itself to the transcript under the 80vh cap);
 *  min-h-0 is what lets flexbox shrink it, since a flex child's default
 *  min-height refuses to go below its content. */
// The verdict line is the one that earns a colour, and it earns it from the
// outcome rather than from the channel it arrived on.
const FAILED = /^(failed|canceled|interrupted)\b/i

function classFor(line: TermLine): string {
  if (line.stream === 'status') {
    if (FAILED.test(line.message)) return 'text-red'
    return /^succeeded\b/i.test(line.message) ? 'text-green' : 'text-amber'
  }
  return STREAM_CLASS[line.stream] ?? 'text-text-2'
}

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
          <div key={i} className={classFor(l)}>
            {stripAnsi(l.message)}
          </div>
        ))
      )}
    </div>
  )
}
