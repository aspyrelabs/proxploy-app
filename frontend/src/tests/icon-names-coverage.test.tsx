/**
 * Closes the gap between what a real page renders and what the Google
 * Fonts CDN link (vite.config.ts's materialSymbolsLink plugin) actually
 * requests via `icon_names`.
 *
 * That link is built from scripts/icon-names.mjs's static scan of src/, not
 * hand-maintained -- so it cannot drift from what components render UNLESS
 * the extractor's own patterns miss a real usage shape. If that happens, a
 * component keeps rendering fine in this test suite (jsdom does not load
 * fonts at all) while the CDN link silently omits that icon's name, and a
 * real browser then shows the literal word instead of a glyph. This test
 * closes that gap by comparing two INDEPENDENTLY produced sets:
 *   - "rendered": every icon name real components actually put on the
 *     page, gathered by mounting them (the same way their own test files
 *     do) and reading each `.material-symbols-outlined` span's text
 *     content out of the DOM -- not by re-reading source. Since the Icon
 *     component now renders the ligature name as literal text (see
 *     components/ui/icon.tsx), the text content already IS the name; no
 *     separate data attribute is needed to recover it.
 *   - "extracted": scripts/icon-names.mjs's static scan of src/, the same
 *     function vite.config.ts uses to build the CDN link.
 * If a future change adds an icon that renders correctly (rendered grows)
 * but the extractor's patterns do not recognise (extracted does not), this
 * fails here instead of shipping a link missing that icon's name.
 */
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { extractIconNames } from '../../scripts/icon-names.mjs'
import { buildIconFontHref } from '../../scripts/icon-font-link.mjs'
import type { JobRow } from '../api/jobs'

const SRC_DIR = join(dirname(fileURLToPath(import.meta.url)), '..')

vi.mock('@tanstack/react-router', async (orig) => ({
  ...(await orig() as object),
  Link: ({ to, children, ...rest }: { to?: string; children?: unknown }) =>
    <a href={to} {...rest}>{children as never}</a>,
}))
vi.mock('../components/AccountMenu', () => ({ AccountMenu: () => null }))
vi.mock('../components/TierPill', () => ({ TierPill: () => null }))
vi.mock('../components/CommandPalette', () => ({ openCommandPalette: vi.fn() }))
vi.mock('sonner', () => ({ toast: { error: vi.fn(), success: vi.fn() } }))

// One job per severity NotificationCard can show, so BellPopover's cards
// (and their per-severity icon, plus the shared "View log"/"Dismiss"
// controls) all render at once.
const JOBS: JobRow[] = [
  { id: 1, kind: 'app.start', status: 'running', target_type: 'app', target_id: 1,
    params: null, result: null, error: null, progress_pct: 40, requested_by: null,
    schedule_id: null, started_at: '2026-08-12T08:00:00Z', finished_at: null,
    created_at: '2026-08-12T08:00:00Z' },
  { id: 2, kind: 'app.stop', status: 'succeeded', target_type: 'app', target_id: 2,
    params: null, result: null, error: null, progress_pct: 100, requested_by: null,
    schedule_id: null, started_at: '2026-08-12T07:00:00Z', finished_at: '2026-08-12T07:01:00Z',
    created_at: '2026-08-12T07:00:00Z' },
  { id: 3, kind: 'vm.backup', status: 'failed', target_type: 'vm', target_id: 3,
    params: null, result: null, error: 'disk full', progress_pct: null, requested_by: null,
    schedule_id: null, started_at: '2026-08-12T06:00:00Z', finished_at: '2026-08-12T06:05:00Z',
    created_at: '2026-08-12T06:00:00Z' },
  { id: 4, kind: 'vm.snapshot', status: 'canceled', target_type: 'vm', target_id: 4,
    params: null, result: null, error: null, progress_pct: null, requested_by: null,
    schedule_id: null, started_at: '2026-08-12T05:00:00Z', finished_at: '2026-08-12T05:01:00Z',
    created_at: '2026-08-12T05:00:00Z' },
]

vi.mock('../api/client', () => ({
  ApiError: class extends Error {},
  api: vi.fn((path: string) => {
    if (path === '/entitlements') return Promise.resolve({ tier: 'pro', features: { 'notify.inapp': true } })
    if (path === '/jobs?status=running') return Promise.resolve(JOBS.filter((j) => j.status === 'running'))
    if (path === '/jobs') return Promise.resolve(JOBS)
    return Promise.resolve([])
  }),
}))

import { Topbar } from '../components/Topbar'
import { ThemeToggle } from '../components/ThemeToggle'
import { SidebarNav } from '../components/SidebarNav'
import { CardLoadingOverlay } from '../components/ui/card-loading-overlay'

/** Every icon name a mounted tree of .material-symbols-outlined spans
 *  actually renders as text -- this is what a real page would ask the
 *  Google Fonts CDN link for, since components/ui/icon.tsx renders each
 *  icon's name as its own text content. */
function renderedIconNames(container: ParentNode): Set<string> {
  const names = new Set<string>()
  container.querySelectorAll('.material-symbols-outlined').forEach((el) => {
    if (el.textContent) names.add(el.textContent)
  })
  return names
}

describe('the Google Fonts link covers every rendered icon', () => {
  it('the extracted set (and therefore the generated link) contains every icon name real components render', async () => {
    const rendered = new Set<string>()

    // Topbar (mounts BellPopover, which mounts NotificationCard for each
    // severity, and its View log / Dismiss controls).
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    const topbar = render(<QueryClientProvider client={qc}><Topbar /></QueryClientProvider>)
    fireEvent.click(await topbar.findByRole('button', { name: 'Activity' }))
    await waitFor(() => expect(topbar.getAllByRole('alert').length).toBeGreaterThan(0))
    // Radix's Popover.Portal renders the cards into document.body, not
    // inside `topbar.container` -- baseElement (document.body by default)
    // is what actually holds everything a user's browser would paint.
    renderedIconNames(topbar.baseElement).forEach((n) => rendered.add(n))
    topbar.unmount()

    // ThemeToggle in both states.
    const toggle = render(<ThemeToggle />)
    renderedIconNames(toggle.container).forEach((n) => rendered.add(n))
    fireEvent.click(toggle.getByRole('button', { name: 'Toggle theme' }))
    renderedIconNames(toggle.container).forEach((n) => rendered.add(n))
    toggle.unmount()

    // SidebarNav expanded and collapsed (the collapse toggle itself swaps
    // between two different chevron icons).
    const sidebar = render(<SidebarNav />)
    renderedIconNames(sidebar.container).forEach((n) => rendered.add(n))
    fireEvent.click(sidebar.getByRole('button', { name: /collapse sidebar/i }))
    renderedIconNames(sidebar.container).forEach((n) => rendered.add(n))
    sidebar.unmount()

    // CardLoadingOverlay's veil, only present while active. Its spinner is
    // progress_activity, Material Symbols' purpose-built loading glyph.
    const overlay = render(<CardLoadingOverlay state={{ firstLoad: true }}><div /></CardLoadingOverlay>)
    renderedIconNames(overlay.container).forEach((n) => rendered.add(n))
    overlay.unmount()

    expect(rendered.size).toBeGreaterThan(0)
    expect(rendered).toContain('progress_activity')

    const extracted = extractIconNames(SRC_DIR)
    const missing = [...rendered].filter((name) => !extracted.has(name))
    expect(missing, `rendered but not extracted: ${missing.join(', ')}`).toEqual([])

    // The generated CDN link is built directly from `extracted`, so this is
    // a sanity check of that construction rather than an independent
    // guard, but it pins the actual shape a browser would request.
    const href = buildIconFontHref(extracted)
    for (const name of rendered) {
      expect(href, `"${name}" missing from generated icon_names`).toContain(name)
    }
  })
})
