import { useEffect, useState } from 'react'
import type { ZxcvbnResult } from '@zxcvbn-ts/core'

export const MIN_LENGTH = 12

const CLASSES = [
  { label: 'A lower case letter, a to z', test: /[a-z]/ },
  { label: 'An upper case letter, A to Z', test: /[A-Z]/ },
  { label: 'A digit, 0 to 9', test: /\d/ },
  { label: 'A symbol, such as ! ? @ # $ % & * - _', test: /[^A-Za-z0-9]/ },
]

export type Rule = { label: string; met: boolean }

export function rules(pw: string): Rule[] {
  return [
    { label: `At least ${MIN_LENGTH} characters`, met: pw.length >= MIN_LENGTH },
    ...CLASSES.map(c => ({ label: c.label, met: c.test.test(pw) })),
  ]
}

export function refusal(pw: string): string | null {
  if (pw.length < MIN_LENGTH) return `Use at least ${MIN_LENGTH} characters.`
  const missing = CLASSES.filter(c => !c.test.test(pw)).map(c => c.label.split(',')[0].toLowerCase())
  if (missing.length) {
    return 'Add ' + (missing.length === 1 ? missing[0]
      : missing.slice(0, -1).join(', ') + ' and ' + missing[missing.length - 1]) + '.'
  }
  return null
}

let checker: Promise<(pw: string, inputs: string[]) => ZxcvbnResult> | null = null

function load() {
  checker ??= Promise.all([
    import('@zxcvbn-ts/core'),
    import('@zxcvbn-ts/language-common'),
    import('@zxcvbn-ts/language-en'),
  ]).then(([core, common, en]) => {
    const zx = new core.ZxcvbnFactory({
      dictionary: { ...common.dictionary, ...en.dictionary, userInputs: [] },
      graphs: common.adjacencyGraphs,
      translations: en.translations,
    })
    return (pw: string, inputs: string[]) => zx.check(pw, inputs)
  })
  return checker
}

export type Strength = {
  score: 0 | 1 | 2 | 3 | 4
  label: string
  warning: string | null
  suggestion: string | null
}

const LABELS = ['Too guessable', 'Very guessable', 'Guessable', 'Good', 'Strong'] as const

export function useStrength(pw: string, email?: string): Strength | null {
  const [result, setResult] = useState<Strength | null>(null)
  useEffect(() => {
    if (pw === '') { setResult(null); return }
    let live = true
    const timer = setTimeout(() => {
      load().then(check => {
        if (!live) return
        const inputs = ['proxploy', 'proxmox', ...(email ? [email, email.split('@')[0]] : [])]
        const r = check(pw, inputs)
        setResult({
          score: r.score,
          label: LABELS[r.score],
          warning: r.feedback.warning || null,
          suggestion: r.feedback.suggestions[0] || null,
        })
      })
    }, 150)
    return () => { live = false; clearTimeout(timer) }
  }, [pw, email])
  return result
}
