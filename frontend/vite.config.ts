/// <reference types="vitest/config" />
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: { proxy: { '/api': 'http://127.0.0.1:8000' } },
  // e2e/ is Playwright's; it imports @playwright/test, which Vitest cannot
  // collect. Without this exclude the two runners' default globs overlap and
  // `npm test` reports a failed file even when every test passes.
  test: {
    environment: 'jsdom', globals: true, setupFiles: ['./src/tests/setup.ts'],
    exclude: ['node_modules/**', 'e2e/**'],
  },
})
