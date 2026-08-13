/// <reference types="vitest/config" />
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import { materialSymbolsLink } from './scripts/vite-plugin-material-symbols-link.mjs'

const here = dirname(fileURLToPath(import.meta.url))

export default defineConfig({
  plugins: [react(), tailwindcss(), materialSymbolsLink(join(here, 'src'))],
  // The "@/" alias shadcn/ui's own components import through, mirrored from
  // tsconfig.app.json's paths so the bundler, Vitest and the compiler all
  // resolve it the same way. Purely additive: every import this app already
  // had is relative and none of them were touched.
  resolve: { alias: { '@': join(here, 'src') } },
  server: { proxy: { '/api': 'http://127.0.0.1:8000' } },
  // e2e/ is Playwright's; it imports @playwright/test, which Vitest cannot
  // collect. Without this exclude the two runners' default globs overlap and
  // `npm test` reports a failed file even when every test passes.
  test: {
    environment: 'jsdom', globals: true, setupFiles: ['./src/tests/setup.ts'],
    exclude: ['node_modules/**', 'e2e/**'],
  },
})
