import { useCallback, useEffect, useRef, useState } from 'react'
import { flushSync } from 'react-dom'
import { Icon } from './ui/icon'
import { applyStoredTheme, setStoredTheme } from '../lib/theme'

/**
 * Vendored by hand from MagicUI's `animated-theme-toggler`
 * (https://magicui.design/r/animated-theme-toggler.json), fetched 2026-08-12.
 * The wipe is unchanged from upstream, including the percentage (not px)
 * clip-path coordinates, which work around a Chrome bug where absolute px
 * clip-path coordinates on ::view-transition-new(root) render unscaled on
 * fractional display scales for the first transition after load
 * (magicuidesign/magicui#989).
 *
 * Icon-only (no visible text), so `aria-label` and `title` are the WHOLE
 * accessible name, not decoration.
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
