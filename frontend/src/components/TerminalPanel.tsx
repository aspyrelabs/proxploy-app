import { useEffect, useRef } from 'react'

export type TermLine = { stream: string; message: string }

// Doc 06 §c: terminal panels stay #0a0e14 in BOTH themes, consoles are dark,
// full stop. Do not swap these for theme tokens.
const STREAM_CLASS: Record<string, string> = {
  stdout: 'text-text-2',
  stderr: 'text-red',
  progress: 'text-blue',
  status: 'text-amber',
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
            {l.message}
          </div>
        ))
      )}
    </div>
  )
}
