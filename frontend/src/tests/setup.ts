import '@testing-library/jest-dom/vitest'
import { configure } from '@testing-library/react'

configure({ asyncUtilTimeout: 5000 })

// jsdom doesn't implement matchMedia; uPlot calls it at import time (Sparkline).
// ponytail: minimal stub, extend with real listener semantics if a test needs them.
window.matchMedia ??= () => ({
  matches: false,
  media: '',
  onchange: null,
  addListener: () => {},
  removeListener: () => {},
  addEventListener: () => {},
  removeEventListener: () => {},
  dispatchEvent: () => false,
}) as unknown as MediaQueryList

// jsdom doesn't implement ResizeObserver; cmdk constructs one on mount to keep
// its list sized (CommandPalette). Same shape as the matchMedia stub above:
// enough to let the component mount, no real observation semantics.
globalThis.ResizeObserver ??= class {
  observe() {}
  unobserve() {}
  disconnect() {}
} as unknown as typeof ResizeObserver
