import { readFileSync, readdirSync } from 'node:fs'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'

/**
 * A hand-written grid template must never use a bare `1fr` track.
 *
 * `1fr` means `minmax(auto, 1fr)`, and that `auto` minimum is the track's
 * min-content. When the track holds something with a fixed pixel size (every
 * uPlot canvas this app draws), the column can never shrink below whatever
 * width that thing happened to be drawn at. Measured, on the real markup:
 * cards frozen at 613/613/342 across viewports from 1500px down to 700px, the
 * canvases never redrawing, and the third column's right edge stranded at
 * 1579px while the container ended at 1100px.
 *
 * It shipped once, in the Apps detail panel, where it was worse than it looks:
 * that panel renders inside a `<td colSpan={8}>`, so a grid that refuses to
 * shrink widens the entire Apps table and pushes its Storage and Network
 * columns off the right edge of the screen.
 *
 * Tailwind's own `grid-cols-N` utilities are safe (they expand to
 * `repeat(N, minmax(0,1fr))`), so only arbitrary `grid-cols-[...]` values can
 * reintroduce this. jsdom has no layout engine and no canvas, so no rendering
 * test can catch it; reading the source is the only guard available.
 */
function sourceFiles(dir: string): string[] {
  return readdirSync(dir, { withFileTypes: true }).flatMap((e) => {
    const full = join(dir, e.name)
    if (e.isDirectory()) return e.name === 'tests' ? [] : sourceFiles(full)
    return /\.tsx?$/.test(e.name) ? [full] : []
  })
}

describe('arbitrary grid templates', () => {
  it('never use a bare 1fr track, which cannot shrink below its content', () => {
    // join(__dirname, '..'), the same root no-hardcoded-colors.test.ts walks.
    const src = join(__dirname, '..')
    const offenders: string[] = []
    for (const file of sourceFiles(src)) {
      const text = readFileSync(file, 'utf8')
      for (const m of text.matchAll(/grid-cols-\[([^\]]+)\]/g)) {
        const tracks = m[1].split('_')
        // `minmax(0,1fr)` arrives split across underscores, so a `1fr` piece
        // only counts as bare when it is a whole track on its own.
        if (tracks.some((t) => t === '1fr')) {
          offenders.push(`${file.slice(src.length + 1)}: grid-cols-[${m[1]}]`)
        }
      }
    }
    expect(offenders,
      'Use minmax(0,1fr) instead of a bare 1fr in a hand-written grid template.')
      .toEqual([])
  })
})
