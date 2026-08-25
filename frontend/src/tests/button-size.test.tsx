/**
 * A caller's sizing className has to beat the component's own.
 *
 * It did not, for a long time, and nothing said so: Button concatenated the
 * caller's string onto its own, which left the winner to the emitted CSS, and
 * the CSS picks by file order rather than by who asked last. `.px-3\.5` is
 * written after `.px-2`, so 37 call sites that passed `px-2 py-1 text-[11px]`
 * to shrink a control got the full-size one instead, down to the font size.
 */
import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { Button } from '../components/ui/button'

describe('Button sizing', () => {
  it('lets a caller override the padding and font its size would set', () => {
    render(<Button className="px-2 py-1 text-[11px]">Verify</Button>)
    const cls = screen.getByRole('button').className.split(/\s+/)
    // The caller's three survive...
    expect(cls).toEqual(expect.arrayContaining(['px-2', 'py-1', 'text-[11px]']))
    // ...and md's competing three are gone, rather than both being present and
    // the outcome being decided somewhere else entirely.
    expect(cls).not.toContain('px-3.5')
    expect(cls).not.toContain('py-2')
    expect(cls).not.toContain('text-[13px]')
  })

  it('still applies its own size when the caller asks for nothing', () => {
    render(<Button size="sm">Test restore</Button>)
    const cls = screen.getByRole('button').className.split(/\s+/)
    expect(cls).toEqual(expect.arrayContaining(['px-[11px]', 'py-[7px]', 'text-[11px]']))
  })

  it('keeps the caller layout classes that are not competing with a size', () => {
    render(<Button size="sm" className="ml-2 w-full">Restore</Button>)
    const cls = screen.getByRole('button').className.split(/\s+/)
    expect(cls).toEqual(expect.arrayContaining(['ml-2', 'w-full', 'px-[11px]']))
  })
})
