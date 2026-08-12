/**
 * Closes the gap between dev and a production build for icons.
 *
 * Dev loads the FULL Material Symbols font (src/styles/load-icon-font.ts),
 * so any icon name renders correctly there even if the build-time extractor
 * (scripts/icon-names.mjs) would miss it. A build instead ships a font
 * subset containing only the names the extractor found -- if it missed one
 * that a component actually renders, that icon works on every developer's
 * machine and then silently vanishes (falls back to .notdef tofu, since the
 * codepoint it needs isn't in the subset) the moment someone runs a real
 * build.
 *
 * This test closes that gap by comparing two INDEPENDENTLY produced sets:
 *   - "rendered": every icon name that real components actually put on the
 *     page, gathered by mounting them (the same way their own test files
 *     do) and reading each Icon's `data-icon` attribute out of the DOM, not
 *     by re-reading source.
 *   - "extracted": scripts/icon-names.mjs's static scan of src/, the same
 *     function scripts/build-icon-font.mjs uses to decide what the subset
 *     font contains.
 * If a future change adds an icon that renders correctly (rendered grows)
 * but the extractor's patterns do not recognise (extracted does not), this
 * fails here instead of shipping a missing glyph.
 */
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { extractIconNames } from '../../scripts/icon-names.mjs'
import type { JobRow } from '../api/jobs'

const SRC_DIR = join(dirname(fileURLToPath(import.meta.url)), '..')

vi.mock('@tanstack/react-router', async (orig) => ({
  ...(await orig() as object),
  Link: ({ to, children, ...rest }: { to?: string; children?: unknown }) =>
    <a href={to} {...rest}>{children as never}</a>,
}))
vi.mock('../components/HealthFooter', () => ({ HealthFooter: () => null }))
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
 *  carries, read via each one's `data-icon` attribute (see
 *  components/ui/icon.tsx) -- this is what a real page would actually ask
 *  the font's codepoint subset for, dev or prod. */
function renderedIconNames(container: ParentNode): Set<string> {
  const names = new Set<string>()
  container.querySelectorAll('.material-symbols-outlined').forEach((el) => {
    const name = el.getAttribute('data-icon')
    if (name) names.add(name)
  })
  return names
}

describe('icon subset covers every rendered icon (dev/prod parity)', () => {
  it('the extracted set contains every icon name real components render', async () => {
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

    // CardLoadingOverlay's veil, only present while active.
    const overlay = render(<CardLoadingOverlay state={{ firstLoad: true }}><div /></CardLoadingOverlay>)
    renderedIconNames(overlay.container).forEach((n) => rendered.add(n))
    overlay.unmount()

    expect(rendered.size).toBeGreaterThan(0)

    const extracted = extractIconNames(SRC_DIR)
    const missing = [...rendered].filter((name) => !extracted.has(name))
    expect(missing, `rendered but not extracted: ${missing.join(', ')}`).toEqual([])
  })
})
