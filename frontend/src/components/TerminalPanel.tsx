import { useEffect, useRef } from 'react'

export type TermLine = { stream: string; message: string }

// Doc 06 §c: terminal panels stay #0a0e14 in BOTH themes — consoles are dark,
// full stop. Do not swap these for theme tokens.
const STREAM_CLASS: Record<string, string> = {
  stdout: 'text-text-2',
  stderr: 'text-red',
  progress: 'text-blue',
  status: 'text-amber',
}

/** Static-mode log panel (doc 06 `TerminalPanel`). Live mode = xterm.js, Phase 5. */
export function TerminalPanel({ lines, height = 260 }:
  { lines: TermLine[]; height?: number }) {
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
      style={{ background: '#0a0e14', maxHeight: height }}
      className="overflow-auto rounded-ctl border border-line-soft p-3 font-mono text-[12.5px] leading-[1.7]"
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
