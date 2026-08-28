import { Icon } from '../ui/icon'
import type { Prompt } from '../../lib/install-prompts'
import { answerKey } from '../../lib/install-prompts'

/**
 * The questions the upstream install script asks, rendered as a form.
 *
 * Every label here is the sentence the script author wrote, passed through
 * unchanged. There is no schema and no help text upstream, so whatever
 * `read -p` shows a human is the only description of the value that exists,
 * and rewording it would be inventing documentation.
 *
 * A GATE is not a field. It is consent to run an installer the upstream
 * repository says it does not audit, so it gets the warning verbatim, starts
 * unticked, and blocks Install until it is ticked. Pre-ticking it would be
 * defaulting it to yes with extra steps.
 */
export function PromptFields({ prompts, answers, onChange }: {
  prompts: Prompt[]
  answers: Record<string, string>
  onChange: (next: Record<string, string>) => void
}) {
  if (prompts.length === 0) return null
  const set = (k: string, v: string) => onChange({ ...answers, [k]: v })

  return (
    <div className="flex flex-col gap-3">
      <div className="text-[12px] font-semibold text-text-2">
        This app's installer asks {prompts.length === 1 ? 'a question' : 'some questions'}
      </div>

      {prompts.map((p, i) => {
        const k = answerKey(p, i)
        return (
        <div key={k} className="flex flex-col gap-1.5">
          {p.gate ? (
            <div className="rounded-ctl border border-amber/40 bg-amber-dim p-3">
              <div className="flex items-start gap-2">
                <Icon name="warning" className="mt-[1px] shrink-0 text-[16px] text-amber" />
                <div className="flex flex-col gap-1">
                  {/* Verbatim, and from upstream. Ours would be a paraphrase of
                      somebody else's risk disclosure. */}
                  {p.warnings.map((w) => (
                    <p key={w} className="text-[12px] text-text">{w}</p>
                  ))}
                  <label className="mt-1 flex items-start gap-2 text-[12px] text-text-2">
                    <input type="checkbox" className="mt-[3px]"
                           checked={(answers[k] ?? '') === 'y'}
                           onChange={(e) => set(k, e.target.checked ? 'y' : '')} />
                    <span>{p.label}</span>
                  </label>
                </div>
              </div>
            </div>
          ) : p.kind === 'yesno' ? (
            <label className="flex items-start gap-2 text-[12px] text-text-2">
              <input type="checkbox" className="mt-[3px]"
                     checked={(answers[k] ?? p.default ?? 'n') === 'y'}
                     onChange={(e) => set(k, e.target.checked ? 'y' : 'n')} />
              <span>{p.label}</span>
            </label>
          ) : (
            <>
              <label htmlFor={`prompt-${k}`} className="text-[12px] text-text-2">
                {p.label}
              </label>
              {p.kind === 'choice' && p.choices ? (
                <select id={`prompt-${k}`}
                        className="rounded-ctl border border-line bg-panel-2 px-2 py-1.5 text-[13px]"
                        value={answers[k] ?? ''}
                        onChange={(e) => set(k, e.target.value)}>
                  <option value="">Choose…</option>
                  {p.choices.map((c) => <option key={c} value={c}>{c}</option>)}
                </select>
              ) : (
                <input id={`prompt-${k}`}
                       // Masked because the script author asked for it to be:
                       // either the prompt says so, or the script used
                       // `read -s` to keep it off a terminal.
                       type={p.sensitive ? 'password' : 'text'}
                       autoComplete={p.sensitive ? 'new-password' : 'off'}
                       className="rounded-ctl border border-line bg-panel-2 px-2 py-1.5 text-[13px]"
                       placeholder={p.default ?? ''}
                       value={answers[k] ?? ''}
                       onChange={(e) => set(k, e.target.value)} />
              )}
              {p.sensitive && (
                <span className="text-[11px] text-text-3">
                  Stored encrypted, and kept out of the job log
                </span>
              )}
            </>
          )}
        </div>
        )
      })}
    </div>
  )
}
