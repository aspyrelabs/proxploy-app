import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

import { FEATURE_KEYS } from '../api/feature-keys'

function registryFlagKeys(): string[] {
  const path = resolve(process.cwd(), '../backend/proxploy/entitlements/registry.py')
  const src = readFileSync(path, 'utf8')
  const start = src.indexOf('FLAG_KEYS: tuple[str, ...] = (')
  if (start < 0) throw new Error(`FLAG_KEYS not found in ${path}`)
  const end = src.indexOf('\n)', start)
  if (end < 0) throw new Error(`FLAG_KEYS tuple is unterminated in ${path}`)
  const body = src.slice(start, end).replace(/#[^\n]*/g, '')
  return [...body.matchAll(/"([a-z][a-z0-9_]*\.[a-z0-9_]+)"/g)].map((m) => m[1])
}

describe('frontend gate keys against the backend registry', () => {
  it('finds the registry and parses a plausible key set', () => {
    expect(registryFlagKeys().length).toBeGreaterThan(50)
  })

  it('gates only on keys that exist in FLAG_KEYS', () => {
    const known = new Set(registryFlagKeys())
    const dead = FEATURE_KEYS.filter((k) => !known.has(k))
    expect(dead, `gate keys absent from registry.py (renamed or misspelt): ${dead.join(', ')}`)
      .toEqual([])
  })

  it('has no duplicate entries', () => {
    expect(FEATURE_KEYS.length).toBe(new Set(FEATURE_KEYS).size)
  })
})
