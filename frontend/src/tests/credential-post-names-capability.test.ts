import { readFileSync, readdirSync, statSync } from 'node:fs'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'

// The bug this guards: two now-deleted dialogs posted a token to
// /hosts/{id}/credentials with no `capability` field, which the backend
// silently defaulted to "monitoring". Every capability's token landed in
// the monitoring slot, one after another, and the operator's screen kept
// saying "Rotated" the whole time. The backend now refuses an unlabelled
// write once a monitoring token already exists (see hosts.py,
// CredentialRotateIn.capability), but a frontend caller that never sends
// `capability` still can't tell the server which slot it meant, so this
// test catches the mistake at the source instead of at request time.
//
// An SSH-only rotate (`{ rotate_ssh: true }`, no token_id/token_secret)
// carries no token and needs no capability -- it can't land in any
// capability slot, so it is not an offender here.

function walk(dir: string): string[] {
  return readdirSync(dir).flatMap((e) => {
    const p = join(dir, e)
    return statSync(p).isDirectory() ? walk(p) : p.endsWith('.tsx') || p.endsWith('.ts') ? [p] : []
  })
}

// The call expression enclosing a given index, found by walking outward from
// the nearest unmatched '(' before it to its matching ')'.
function enclosingCall(text: string, at: number): string {
  let depth = 0
  let start = -1
  for (let i = at; i >= 0; i--) {
    if (text[i] === ')') depth++
    else if (text[i] === '(') {
      if (depth === 0) { start = i; break }
      depth--
    }
  }
  if (start === -1) return ''
  let d = 0
  for (let j = start; j < text.length; j++) {
    if (text[j] === '(') d++
    else if (text[j] === ')') { d--; if (d === 0) return text.slice(start, j + 1) }
  }
  return text.slice(start)
}

describe('every frontend credential POST names its capability', () => {
  it('no /credentials call carrying token_id/token_secret omits capability', () => {
    const src = join(__dirname, '..')
    const offenders: string[] = []
    for (const file of walk(src)) {
      const rel = file.slice(src.length + 1)
      if (rel.startsWith('tests/')) continue
      const text = readFileSync(file, 'utf8')
      let idx = text.indexOf('/credentials')
      while (idx !== -1) {
        const call = enclosingCall(text, idx)
        if (call.includes('token_id') && !call.includes('capability')) {
          offenders.push(`${rel}: ${call.replace(/\s+/g, ' ').trim()}`)
        }
        idx = text.indexOf('/credentials', idx + 1)
      }
    }
    expect(offenders, offenders.join('\n')).toEqual([])
  })
})
