import { describe, expect, it } from 'vitest'
import { pveWebUrl } from '../lib/utils'

describe('pveWebUrl', () => {
  it('adds the Proxmox port when the stored address has none', () => {
    expect(pveWebUrl('https://192.168.50.10')).toBe('https://192.168.50.10:8006')
  })

  it('keeps a port the operator typed', () => {
    expect(pveWebUrl('https://192.168.50.10:9999')).toBe('https://192.168.50.10:9999')
  })

  it('keeps an explicit 8006', () => {
    expect(pveWebUrl('https://pve.lab.local:8006')).toBe('https://pve.lab.local:8006')
  })

  it('keeps a hostname address', () => {
    expect(pveWebUrl('https://pve.lab.local')).toBe('https://pve.lab.local:8006')
  })

  it('returns anything unparseable untouched rather than breaking the link', () => {
    expect(pveWebUrl('not a url')).toBe('not a url')
  })
})
