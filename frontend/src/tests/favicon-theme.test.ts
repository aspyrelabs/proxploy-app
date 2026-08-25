/**
 * The tab icon follows the app's theme toggle.
 *
 * Reported three times before it was fixed, because the first fix was to the
 * wrong half: index.html scopes the two icons to prefers-color-scheme, which
 * follows the OPERATING SYSTEM, so switching the app from dark to light left
 * the mark in the tab exactly where it was. Correct by the old design, and not
 * what anyone watching it believed they were looking at.
 */
import { beforeEach, describe, expect, it } from 'vitest'

import { applyFavicon, setStoredTheme } from '../lib/theme'

const hrefs = () =>
  [...document.querySelectorAll('link[rel~="icon"]')].map((l) => l.getAttribute('href'))

beforeEach(() => {
  document.head.innerHTML = ''
  localStorage.clear()
})

describe('favicon follows the app theme', () => {
  it('shows the near-white mark on the dark theme', () => {
    applyFavicon('dark')
    expect(hrefs()).toEqual(['/proxploy-favicon-dark.svg'])
  })

  it('shows the dark-inked mark on the light theme', () => {
    applyFavicon('light')
    expect(hrefs()).toEqual(['/proxploy-favicon-light.svg'])
  })

  it('leaves exactly one icon link, never a second to compete with', () => {
    // A second icon link is fetched alongside the first and wins in both
    // schemes wherever it sits, measured in a real Chromium. Two swaps in a
    // row must not accumulate.
    applyFavicon('dark')
    applyFavicon('light')
    applyFavicon('dark')
    expect(hrefs()).toEqual(['/proxploy-favicon-dark.svg'])
  })

  it('swaps when the toggle is used, which is the whole complaint', () => {
    setStoredTheme('dark')
    expect(hrefs()).toEqual(['/proxploy-favicon-dark.svg'])
    setStoredTheme('light')
    expect(hrefs()).toEqual(['/proxploy-favicon-light.svg'])
  })

  it('starts from whatever index.html declared, replacing it wholesale', () => {
    document.head.innerHTML =
      '<link rel="icon" href="/proxploy-favicon-dark.svg" media="(prefers-color-scheme: dark)">'
      + '<link rel="icon" href="/proxploy-favicon-light.svg" media="(prefers-color-scheme: light)">'
    applyFavicon('light')
    expect(hrefs()).toEqual(['/proxploy-favicon-light.svg'])
  })
})
