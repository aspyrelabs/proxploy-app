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

  // The real shape FastAPI's RequestValidationError handler emits
  // (backend/proxploy/main.py::_no_echo_validation_errors): `detail` is an
  // array of {loc, msg, type, ...}, not a string, so the old code's
  // `typeof detail === 'string'` check fell straight through to the
  // fallback and blamed the network for a 422 the server explained in full.
  it('reads a FastAPI validation error out of the detail array', () => {
    const e = new ApiError(422, { detail: [{
      type: 'value_error', loc: ['body', 'email'],
      msg: 'value is not a valid email address: The part after the @-sign is '
         + 'a special-use or reserved name that cannot be used with email.',
      ctx: { reason: 'special-use or reserved name' },
    }] })
    expect(apiErrorDetail(e, 'fallback')).toBe(
      'value is not a valid email address: The part after the @-sign is a '
      + 'special-use or reserved name that cannot be used with email.')
  })

  it('joins more than one validation error into one usable message', () => {
    const e = new ApiError(422, { detail: [
      { type: 'missing', loc: ['body', 'email'], msg: 'Field required' },
      { type: 'string_too_short', loc: ['body', 'password'], msg: 'String should have at least 8 characters' },
    ] })
    expect(apiErrorDetail(e, 'fallback')).toBe('Field required; String should have at least 8 characters')
  })

  // RFC 9457 problem+json, main.py's problem_handler: {type, title, status,
  // detail}, detail a plain string. Already covered by the plain-string
  // branch, asserted again here under the real field names so a future
  // change to that handler's shape is caught here too.
  it('reads the RFC 9457 problem+json string detail', () => {
    const e = new ApiError(409, {
      type: 'about:blank', title: 'Conflict', status: 409,
      detail: 'node2.lab.local has no lifecycle API token configured; '
             + 'add one in Settings -> Hosts before this operation can run.',
    })
    expect(apiErrorDetail(e, 'fallback')).toBe(
      'node2.lab.local has no lifecycle API token configured; '
      + 'add one in Settings -> Hosts before this operation can run.')
  })

  it('falls back only for a validation array with no usable msg', () => {
    const e = new ApiError(422, { detail: [{ loc: ['body', 'email'] }] })
    expect(apiErrorDetail(e, 'fallback')).toBe('fallback')
  })
})
