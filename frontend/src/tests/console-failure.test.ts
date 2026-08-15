import { describe, expect, it } from 'vitest'

import { ApiError } from '../api/client'
import { consoleFailure } from '../api/consoles'

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

  it('still says something when the error carries no detail at all', () => {
    expect(consoleFailure(new Error('boom')).note)
      .toBe('No reason was given. Reload the page to try again.')
  })
})
