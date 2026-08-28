import { rules, useStrength } from '../lib/password-strength'
import { Icon } from './ui/icon'

const BAR = ['bg-red', 'bg-red', 'bg-amber', 'bg-amber', 'bg-green'] as const

export function PasswordStrength({ value, email }: { value: string; email?: string }) {
  const s = useStrength(value, email)
  return (
    <div className="mt-1.5" aria-live="polite">
      <div className="flex items-center gap-2">
        <div className="flex h-1 flex-1 gap-1" role="presentation">
          {[0, 1, 2, 3].map((i) => (
            <span key={i}
              className={`h-full flex-1 rounded-full ${
                s && s.score > i ? BAR[s.score] : 'bg-line'}`} />
          ))}
        </div>
        <span className={`w-28 text-right text-[11.5px] ${
          !s ? 'text-text-3' : s.score >= 4 ? 'text-green'
            : s.score >= 3 ? 'text-text-3' : 'text-red'}`}>
          {s?.label ?? ''}
        </span>
      </div>
      <ul className="mt-2 space-y-0.5">
        {rules(value).map((r) => (
          <li key={r.label}
            className={`flex items-start gap-1.5 text-[11.5px] ${
              r.met ? 'text-green' : 'text-text-3'}`}>
            <Icon name={r.met ? 'check' : 'close'} size={14} className="mt-[1px] shrink-0" />
            {r.label}
          </li>
        ))}
      </ul>
      {s && (s.warning || s.suggestion) && (
        <p className="mt-1.5 text-[11.5px] text-text-3">{s.warning || s.suggestion}</p>
      )}
    </div>
  )
}
