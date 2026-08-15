import { describe, expect, it } from 'vitest'
import { ApiError, apiErrorDetail } from '../api/client'

describe('apiErrorDetail', () => {
  it('prefixes a 502 with which side failed, bare string detail', () => {
    const e = new ApiError(502, { detail: 'cannot resolve pve1.example.com' })
    expect(apiErrorDetail(e, 'fallback')).toBe(
      'Proxmox could not do this: cannot resolve pve1.example.com')
  })

  it('prefixes a 502 carrying the nested {error, detail} shape', () => {
    const e = new ApiError(502, { detail: { error: 'pve_error', detail: 'storage full' } })
    expect(apiErrorDetail(e, 'fallback')).toBe('Proxmox could not do this: storage full')
  })

  it('does not double-prefix text that already starts with Proxmox', () => {
    const e = new ApiError(502, { detail: 'Proxmox rejected the request' })
    expect(apiErrorDetail(e, 'fallback')).toBe('Proxmox rejected the request')
  })

  it('leaves 4xx text untouched', () => {
    const e = new ApiError(409, { detail: 'Type the name to confirm.' })
    expect(apiErrorDetail(e, 'fallback')).toBe('Type the name to confirm.')
  })

  it('uses the caller-supplied fallback when the body has no usable detail', () => {
    expect(apiErrorDetail(new ApiError(502, null), 'fallback')).toBe('fallback')
    expect(apiErrorDetail(new ApiError(502, { detail: 42 }), 'fallback')).toBe('fallback')
    expect(apiErrorDetail(new Error('not an ApiError'), 'fallback')).toBe('fallback')
  })
})
