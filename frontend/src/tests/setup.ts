import '@testing-library/jest-dom/vitest'

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
