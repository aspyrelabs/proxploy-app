import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ThemeToggle } from '../components/ThemeToggle'

const STORAGE_KEY = 'pp_theme'

beforeEach(() => {
  localStorage.clear()
  document.documentElement.dataset.theme = 'dark'
})

afterEach(() => {
  cleanup()
  localStorage.clear()
  delete document.documentElement.dataset.theme
})

describe('ThemeToggle', () => {
  it('flips data-theme on <html> when clicked, and back again on a second click', () => {
    render(<ThemeToggle />)
    const button = screen.getByRole('button', { name: 'Toggle theme' })

    fireEvent.click(button)
    expect(document.documentElement.dataset.theme).toBe('light')

    fireEvent.click(button)
    expect(document.documentElement.dataset.theme).toBe('dark')
  })

  it('persists the choice to localStorage under pp_theme', () => {
    render(<ThemeToggle />)
    fireEvent.click(screen.getByRole('button', { name: 'Toggle theme' }))
    expect(localStorage.getItem(STORAGE_KEY)).toBe('light')
  })

  it('keeps the visible Light/Dark label and the Toggle theme accessible name across a toggle', () => {
    render(<ThemeToggle />)
    const button = screen.getByRole('button', { name: 'Toggle theme' })
    expect(button).toHaveTextContent('Light')

    fireEvent.click(button)

    // Still reachable by the same accessible name after the state flip.
    const sameButton = screen.getByRole('button', { name: 'Toggle theme' })
    expect(sameButton).toBe(button)
    expect(sameButton).toHaveTextContent('Dark')
  })

  it('still flips the theme when document.startViewTransition is unavailable (jsdom default)', () => {
    expect(document.startViewTransition).toBeUndefined()

    render(<ThemeToggle />)
    fireEvent.click(screen.getByRole('button', { name: 'Toggle theme' }))

    expect(document.documentElement.dataset.theme).toBe('light')
    expect(localStorage.getItem(STORAGE_KEY)).toBe('light')
  })

  it('respects prefers-reduced-motion: flips the theme directly without starting a view transition', () => {
    const matchMediaSpy = vi.spyOn(window, 'matchMedia').mockImplementation((query: string) => ({
      matches: query === '(prefers-reduced-motion: reduce)',
      media: query,
      onchange: null,
      addListener: () => {},
      removeListener: () => {},
      addEventListener: () => {},
      removeEventListener: () => {},
      dispatchEvent: () => false,
    }) as unknown as MediaQueryList)

    // A spy standing in for the browser API, used only to assert it is never
    // called under reduced motion -- not to simulate the animation itself.
    const startViewTransitionSpy = vi.fn()
    const doc = document as unknown as { startViewTransition?: typeof startViewTransitionSpy }
    doc.startViewTransition = startViewTransitionSpy

    try {
      render(<ThemeToggle />)
      fireEvent.click(screen.getByRole('button', { name: 'Toggle theme' }))

      // The new behaviour under test: the component actually consults
      // prefers-reduced-motion before deciding whether to animate.
      expect(matchMediaSpy).toHaveBeenCalledWith('(prefers-reduced-motion: reduce)')
      expect(startViewTransitionSpy).not.toHaveBeenCalled()
      expect(document.documentElement.dataset.theme).toBe('light')
      expect(localStorage.getItem(STORAGE_KEY)).toBe('light')
    } finally {
      delete doc.startViewTransition
      matchMediaSpy.mockRestore()
    }
  })
})
