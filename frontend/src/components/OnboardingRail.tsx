export type StepStatus = 'done' | 'current' | 'todo' | 'skipped'

export type RailStep = {
  label: string
  status: StepStatus
  detail?: string
  reachable: boolean
}

// A step is a <button> even when unreachable: keeping the list one uniform
// control type is what lets a screen reader walk it, and `reachable` is what
// decides whether the click does anything.
const dot: Record<StepStatus, string> = {
  done: 'bg-green text-ink border-green',
  current: 'bg-transparent text-amber border-amber shadow-[0_0_0_4px_var(--color-amber-dim)]',
  todo: 'bg-transparent text-text-3 border-line',
  skipped: 'bg-transparent text-text-3 border-line border-dashed',
}

const label: Record<StepStatus, string> = {
  done: 'text-text-2',
  current: 'text-text font-semibold',
  todo: 'text-text-3',
  skipped: 'text-text-3',
}

export function OnboardingRail({ steps, view, onSelect }: {
  steps: RailStep[]; view: number; onSelect: (index: number) => void
}) {
  return (
    <ol className="flex gap-1 md:flex-col md:gap-0">
      {steps.map((s, i) => (
        <li key={s.label} className="relative min-w-0 flex-1 md:flex-none">
          {i < steps.length - 1 && (
            <span aria-hidden
              className={`absolute left-[7.5px] top-4 hidden h-[calc(100%-1rem)] w-px origin-top
                md:block ${s.status === 'done' ? 'bg-green pp-rail-fill' : 'bg-line'}`} />
          )}
          <button
            type="button"
            data-status={s.status}
            aria-current={i === view ? 'step' : undefined}
            disabled={!s.reachable}
            onClick={() => s.reachable && onSelect(i)}
            className={`flex w-full items-start gap-2.5 pb-4 text-left transition
              ${s.reachable ? 'cursor-pointer hover:opacity-80' : 'cursor-default'}`}
          >
            <span className={`grid size-4 shrink-0 place-items-center rounded-full border
              text-[9px] font-bold transition ${dot[s.status]}`}>
              {s.status === 'done' ? <span className="pp-tick">✓</span>
                : s.status === 'skipped' ? '–' : i + 1}
            </span>
            <span className="min-w-0">
              <span className={`block text-[11px] leading-tight ${label[s.status]}`}>{s.label}</span>
              {s.detail && (
                <span className="mt-0.5 block truncate text-[9.5px] text-text-3">{s.detail}</span>
              )}
            </span>
          </button>
        </li>
      ))}
    </ol>
  )
}
