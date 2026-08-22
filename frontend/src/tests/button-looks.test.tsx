/**
 * The shared clickable looks, and the rule that nothing hand-rolls them.
 *
 * Three rounds of consolidation land here. The borderless `icon` variants
 * replaced ten identical `<button className="text-text-3 hover:text-…">` in
 * the firewall tables; the exported class strings replaced twenty-three
 * hand-tinted text buttons and links; `segment()` and `tabTrigger` replaced
 * four different ways of looking selected.
 *
 * The failure mode in every case is silent. Someone gives `icon` a background
 * "so it looks clickable" and four boxes come back into every firewall rule
 * row; a new row-name button is hand-tinted because the constant was not
 * discoverable; a palette edit walks selected and hover back onto the same
 * surface. None of it shows up in any other test.
 */
import { readdirSync, readFileSync } from 'node:fs'
import { join } from 'node:path'
import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { Button, amberLinkCls, linkCls, quietCls, segment } from '../components/ui/button'
import { tabTrigger } from '../components/ui/tabs'

const SRC = join(__dirname, '..')

/** Every .tsx under src/, minus the tests themselves. */
const sources = () =>
  readdirSync(SRC, { recursive: true, encoding: 'utf8' })
    .filter((f) => /\.tsx$/.test(f) && !f.startsWith('tests'))

const classesOf = (label: string) =>
  screen.getByRole('button', { name: label }).className

describe('the icon button variants', () => {
  it('draw no box, because table rows hold several of them', () => {
    render(
      <>
        <Button variant="icon" size="icon-xs" aria-label="Edit" />
        <Button variant="icon-danger" size="icon-xs" aria-label="Delete" />
      </>,
    )

    for (const label of ['Edit', 'Delete']) {
      const cls = classesOf(label)
      // `border` on its own is the base class list's `border-transparent`
      // equivalent; what must not appear is a painted edge or a fill.
      expect(cls, `${label} should have no background`).not.toMatch(/\bbg-/)
      expect(cls, `${label} should have no border`).not.toMatch(/\bborder(-|\b)/)
    }
  })

  it('keep the square hit target the raw buttons never had', () => {
    render(<Button variant="icon" size="icon-xs" aria-label="Edit" />)
    // The originals were a bare 16px icon. icon-xs is 24px, which is what
    // makes them a real target rather than an icon that happens to click.
    expect(classesOf('Edit')).toContain('h-6 w-6')
  })

  it('separate the destructive tint from the neutral one', () => {
    render(
      <>
        <Button variant="icon" aria-label="Edit" />
        <Button variant="icon-danger" aria-label="Delete" />
      </>,
    )
    expect(classesOf('Edit')).toContain('hover:text-text')
    expect(classesOf('Delete')).toContain('hover:text-red')
  })

  it('are not re-implemented by hand anywhere', () => {
    // The exact pair of class strings the ten converted buttons carried. A
    // new one means a call site that should have used the variant.
    const bespoke = /className="text-text-3 hover:text-(text|red)"/

    const offenders = sources()
      .filter((f) => bespoke.test(readFileSync(join(SRC, f), 'utf8')))

    expect(offenders).toEqual([])
  })
})

describe('the text button class strings', () => {
  it('are three distinct decisions, not three spellings of one', () => {
    expect(new Set([linkCls, quietCls, amberLinkCls]).size).toBe(3)
  })

  it('all ease, because half the call sites used to snap', () => {
    for (const cls of [linkCls, quietCls, amberLinkCls]) {
      expect(cls).toContain('transition')
    }
  })

  it('give the icon variant and the quiet text tint one definition', () => {
    // Not `toEqual` on two literals: this asserts they are the SAME value, so
    // the variant cannot drift away from the constant it is built from.
    render(<Button variant="icon" aria-label="Edit" />)
    expect(classesOf('Edit')).toContain(quietCls)
  })

  it('are not re-implemented by hand anywhere', () => {
    // Whitespace-flexible: two of the originals wrapped their class list
    // across a newline, so an anchored single-line pattern would miss them.
    const bespoke = [
      /text-text\s+(transition\s+)?hover:text-amber/,   // linkCls
      // Negative lookahead, not \b: `hover:text-text-2` is a FOURTH, quieter
      // decision that MetricChart's inactive range and info-hint's help
      // cursor make on purpose, and \b would match it as a near-miss.
      /text-text-3\s+(transition\s+)?hover:text-text(?![-\w])/, // quietCls
      /text-amber\s+(transition\s+)?hover:underline/,   // amberLinkCls
    ]

    const offenders = sources()
      // button.tsx is where all three are defined, so it is the one file
      // that is supposed to contain them.
      .filter((f) => f !== join('components', 'ui', 'button.tsx'))
      .filter((f) => {
        const src = readFileSync(join(SRC, f), 'utf8')
        return bespoke.some((re) => re.test(src))
      })

    expect(offenders).toEqual([])
  })
})

describe('the selected state of a segmented control', () => {
  it('never collides with the hover state', () => {
    // This is the bug that started the consolidation. FirewallObjects drew
    // its selected row `bg-panel-2` and its hovered row `bg-panel-2`, so
    // pointing at an unselected group made it look selected. Any future
    // palette edit that walks the two back onto the same surface fails here.
    const onFills = segment(true).match(/bg-[\w-]+/g) ?? []
    expect(onFills.length, 'selected should paint a fill').toBeGreaterThan(0)

    for (const fill of onFills) {
      expect(segment(false), `${fill} is used for both selected and hover`)
        .not.toContain(fill)
    }
  })

  it('says selected with hue and hover with surface', () => {
    // Two different signals, so neither has to carry the other's meaning.
    expect(segment(true)).toContain('text-amber')
    expect(segment(false)).toMatch(/hover:bg-/)
    expect(segment(false)).not.toContain('text-amber')
  })
})

describe('the tab strip', () => {
  it('is active under both libraries that drive one', () => {
    // Radix stamps data-state on its trigger; TanStack Link stamps .active.
    // firewall/storage use the first, hosts the second, and one string has
    // to satisfy both or a route silently loses its underline.
    expect(tabTrigger).toContain('data-[state=active]:border-amber')
    expect(tabTrigger).toContain('[&.active]:border-amber')
  })

  it('is defined once', () => {
    const offenders = sources()
      .filter((f) => /data-\[state=active\]:border-amber|\[&\.active\]:border-amber/
        .test(readFileSync(join(SRC, f), 'utf8')))

    // ui/tabs.ts is a .ts and so is not in sources(); every .tsx that draws
    // tabs should be importing from it rather than spelling it out.
    expect(offenders).toEqual([])
  })
})
