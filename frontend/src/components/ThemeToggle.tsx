import { useCallback, useEffect, useRef, useState } from 'react'
import { flushSync } from 'react-dom'
import { Icon } from './ui/icon'
import { applyStoredTheme, setStoredTheme } from '../lib/theme'

/**
 * Vendored by hand from MagicUI's `animated-theme-toggler`
 * (https://magicui.design/r/animated-theme-toggler.json), fetched 2026-08-12.
 * The wipe itself -- a clip-path grown from the button's centre for the
 * duration of a View Transition -- is unchanged from upstream, including the
 * percentage-based (not px) coordinates, which work around a Chrome bug
 * where absolute px clip-path coordinates on ::view-transition-new(root)
 * render unscaled on fractional display scales for the first transition
 * after load (magicuidesign/magicui#989).
 *
 * Adapted for this codebase:
 *  - Drives `data-theme` on <html> via `applyStoredTheme`/`setStoredTheme`
 *    (lib/theme.ts) instead of toggling a `dark` class -- this app has no
 *    Tailwind `dark:` variant; every themed rule in tokens.css keys off
 *    `[data-theme="light"|"dark"]`. The write still happens synchronously
 *    inside the startViewTransition callback (via flushSync), same as
 *    upstream, so the API snapshots the new theme rather than the old one.
 *  - No next-themes: this is Vite, not Next. Theme state and persistence
 *    live entirely in lib/theme.ts; there is one owner of that state (a
 *    single useState here, no MutationObserver/uncontrolled fallback like
 *    upstream needs for its next-themes-less default mode).
 *  - Icons from the self-hosted Material Symbols font (via components/ui/
 *    icon.tsx) instead of lucide-react (which this project deliberately does
 *    not depend on), sized 18px to match the control this replaces.
 *  - No `cn` helper (this repo has no clsx/tailwind-merge) -- className is
 *    a plain string.
 *  - Icon-only, like upstream, at the user's request: the old ThemeToggle
 *    showed the word "Light"/"Dark" beside the icon and no longer does. That
 *    makes `aria-label` the WHOLE accessible name rather than a supplement to
 *    visible text, so it and `title` are load-bearing here, not decoration.
 *  - Added a prefers-reduced-motion escape hatch (upstream has none): skip
 *    the view transition and flip the theme directly, matching the
 *    `motion-reduce:` intent already used elsewhere (UsageBar, SidebarNav,
 *    AppCard).
 *  - Dropped upstream's `variant`/`fromCenter` shape system (square,
 *    triangle, diamond, hexagon, rectangle, star, viewport-centred origin)
 *    and its `duration` prop. This app has exactly one toggle and only
 *    wants the circular wipe expanding from the button, so that surface
 *    area would be dead weight here; the 400ms duration upstream defaults
 *    to is now a fixed constant instead of a configurable prop.
 *  - Folded into a single file rather than a generic ui/ primitive plus a
 *    thin wrapper: there is exactly one call site (Topbar) and no reuse
 *    need, so a separate `theme`/`onThemeChange`-controlled primitive
 *    would be indirection nobody asked for.
 *  - The `--magicui-theme-toggle-vt-duration` custom property and the
 *    `data-magicui-theme-vt` attribute upstream sets on <html> are renamed
 *    to this app's own `--pp-theme-vt-clip-from` / `data-theme-transition`
 *    (see styles/tokens.css) so nothing in this codebase reads "magicui", a
 *    name that no longer means anything once vendored.
 *  - Fixed a gap in what upstream actually ships: its code comment says
 *    `--magicui-theme-vt-clip-from` "pins the collapsed clip-path via CSS
 *    so Firefox does not paint the new theme unclipped between snapshot and
 *    the ready.then() JS animation", but the registry's CSS (both the
 *    published registry JSON and the compiled magicui.design stylesheet)
 *    sets that property from JS and never reads it anywhere -- there is no
 *    consuming rule, so upstream's own fix for the Firefox flash is dead
 *    code as shipped. This version adds the rule the comment describes:
 *    `::view-transition-new(root)`'s clip-path is pinned to
 *    `--pp-theme-vt-clip-from` (the wipe's start state) for as long as
 *    `data-theme-transition="active"`, so Firefox's first paint of that
 *    pseudo-element -- before the Web Animations API call in ready.then()
 *    produces a frame -- is the collapsed circle, not the full new theme.
 */

const DURATION_MS = 400

function circleClipPaths(cx: number, cy: number, maxRadius: number, vw: number, vh: number): [string, string] {
  const toX = (x: number) => `${(x / vw) * 100}%`
  const toY = (y: number) => `${(y / vh) * 100}%`
  const toRadius = (r: number) => `${(r / (Math.hypot(vw, vh) / Math.SQRT2)) * 100}%`
  const at = `${toX(cx)} ${toY(cy)}`
  return [`circle(0% at ${at})`, `circle(${toRadius(maxRadius)} at ${at})`]
}

export function ThemeToggle() {
  const [theme, setTheme] = useState(applyStoredTheme)
  const buttonRef = useRef<HTMLButtonElement>(null)
  const isTransitioningRef = useRef(false)
  const activeAnimRef = useRef<Animation | null>(null)

  const cancelAnim = useCallback(() => {
    activeAnimRef.current?.cancel()
    activeAnimRef.current = null
  }, [])

  useEffect(() => cancelAnim, [cancelAnim])

  const toggleTheme = useCallback(() => {
    const button = buttonRef.current
    if (!button || isTransitioningRef.current) return

    const next = theme === 'dark' ? 'light' : 'dark'
    // Must run synchronously inside the startViewTransition callback below
    // (via flushSync): if the write is deferred, the View Transitions API
    // snapshots the old theme as "new" too and the wipe reveals nothing.
    const applyTheme = () => {
      setStoredTheme(next)
      setTheme(next)
    }

    const prefersReducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches
    if (prefersReducedMotion || typeof document.startViewTransition !== 'function') {
      applyTheme()
      return
    }

    const { top, left, width, height } = button.getBoundingClientRect()
    const x = left + width / 2
    const y = top + height / 2
    const maxRadius = Math.hypot(
      Math.max(x, window.innerWidth - x),
      Math.max(y, window.innerHeight - y),
    )
    const clipPath = circleClipPaths(x, y, maxRadius, window.innerWidth, window.innerHeight)

    const root = document.documentElement
    root.dataset.themeTransition = 'active'
    // Pins ::view-transition-new(root)'s starting clip-path via CSS (see
    // tokens.css) so Firefox's first paint of that pseudo-element is
    // already collapsed, before the animate() call below produces a frame.
    root.style.setProperty('--pp-theme-vt-clip-from', clipPath[0])
    const cleanup = () => {
      isTransitioningRef.current = false
      delete root.dataset.themeTransition
      root.style.removeProperty('--pp-theme-vt-clip-from')
      cancelAnim()
    }

    isTransitioningRef.current = true
    const transition = document.startViewTransition(() => flushSync(applyTheme))
    transition.finished.finally(cleanup).catch(() => {})

    transition.ready.then(() => {
      const anim = root.animate(
        { clipPath },
        { duration: DURATION_MS, easing: 'ease-in-out', fill: 'forwards', pseudoElement: '::view-transition-new(root)' },
      )
      activeAnimRef.current = anim
    }).catch(() => {})
  }, [theme, cancelAnim])

  return (
    <button ref={buttonRef} aria-label="Toggle theme" title="Toggle theme"
      onClick={toggleTheme}
      className="grid h-8 w-8 place-items-center rounded-tile bg-panel-2 text-text-2 hover:bg-elev">
      <Icon name={theme === 'dark' ? 'light_mode' : 'dark_mode'} />
    </button>
  )
}
