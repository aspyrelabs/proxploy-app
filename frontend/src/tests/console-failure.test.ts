import { describe, expect, it } from 'vitest'

import { ApiError } from '../api/client'
import { consoleFailure } from '../api/consoles'
import { shellFailure } from '../routes/console-window'

describe('consoleFailure', () => {
  it('names the plan when the ticket was refused by an entitlement', () => {
    const e = new ApiError(403, { error: 'entitlement_required', feature: 'console.vm' })
    expect(consoleFailure(e).title).toBe('Console is not included in your plan')
  })

  it('says whose side failed on a 502 rather than echoing it bare', () => {
    const e = new ApiError(502, { error: 'unreachable', detail: 'cannot resolve pve1' })
    expect(consoleFailure(e).note).toBe('Proxmox could not do this: cannot resolve pve1')
  })

  it('passes a role refusal through in the backend\'s own words', () => {
    const e = new ApiError(403, { detail: 'Your role does not allow this.' })
    expect(consoleFailure(e).note).toBe('Your role does not allow this.')
  })

  // The exact 409 seen on a freshly adopted CT 111. The shell path used to
  // answer this with "Opening a node shell needs the API token to hold
  // Sys.Console", i.e. it sent the operator to fix an API token over a
  // container that was simply switched off.
  it('says a stopped guest is powered off, not that a privilege is missing', () => {
    const e = new ApiError(409, {
      type: 'about:blank', title: 'Conflict', status: 409,
      error: 'guest_not_running',
      detail: 'CT 111 is stopped; start it before opening a console.',
    })
    expect(consoleFailure(e).title).toBe('This guest is powered off')
    expect(consoleFailure(e).note).toBe('Start it, then open the console again.')
    // Both entry points answer it, and answer it identically.
    expect(shellFailure(e)).toEqual(consoleFailure(e))
    expect(shellFailure(e).note).not.toMatch(/Sys\.Console/)
  })

  it('does not tell you to power on a guest that is only paused', () => {
    const e = new ApiError(409, {
      error: 'guest_not_running',
      detail: 'CT 111 is paused; start it before opening a console.',
    })
    expect(consoleFailure(e).title).toBe('This guest is not running')
    expect(consoleFailure(e).note).toBe('Resume it, then open the console again.')
  })

  it('still blames Sys.Console for a 409 that is not a stopped guest', () => {
    const e = new ApiError(409, { detail: '403 Permission check failed' })
    expect(shellFailure(e).title).toBe('Proxmox refused to open a shell')
  })

  it('still says something when the error carries no detail at all', () => {
    expect(consoleFailure(new Error('boom')).note)
      .toBe('No reason was given. Reload the page to try again.')
  })
})
