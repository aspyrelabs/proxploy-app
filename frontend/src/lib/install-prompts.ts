/**
 * The questions an upstream install script asks, as the API serves them.
 *
 * In lib/ rather than beside the component that renders them, so api/catalog.ts
 * can type its response without importing from components/ (the same reason
 * lib/settings-sections.ts exists).
 */
export type Prompt = {
  variable: string
  label: string
  kind: 'yesno' | 'choice' | 'text'
  sensitive: boolean
  gate: boolean
  warnings: string[]
  choices: string[] | null
  default: string | null
}

/**
 * Prompts the operator still has to answer before Install can run.
 *
 * A gate always counts until it is ticked: it is consent, and an unticked box
 * is a refusal. Anything else counts only when it is blank AND has nothing to
 * fall back on, since a yes/no or a stated default is filled in server side.
 */
export function answerKey(prompt: Prompt, index: number): string {
  return `${prompt.variable}#${index}`
}

export function unanswered(prompts: Prompt[], answers: Record<string, string>): string[] {
  return prompts
    .map((p, i) => [p, answerKey(p, i)] as const)
    .filter(([p, key]) => {
      const given = (answers[key] ?? '').trim()
      if (p.gate) return given.toLowerCase() !== 'y'
      if (given !== '') return false
      return p.kind !== 'yesno' && p.default == null
    })
    .map(([, key]) => key)
}
