import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

const here = dirname(fileURLToPath(import.meta.url))

// Separate config on purpose: the harness must never enter the app's build.
// The app builds from frontend/index.html and never imports anything here, so
// this output is reachable only by opening the file directly.
export default defineConfig({
  root: here,
  base: './',                                   // file:// needs relative asset URLs
  plugins: [react(), tailwindcss()],
  resolve: { alias: { '@': join(here, '../../src') } },
  build: {
    outDir: join(here, 'dist'), emptyOutDir: true,
    // Three pages: cards (index.html), the detail popup (dialog.html), and the
    // cluster-usage row's network tile (network.html).
    rollupOptions: {
      input: {
        index: join(here, 'index.html'),
        dialog: join(here, 'dialog.html'),
        network: join(here, 'network.html'),
      },
    },
  },
})
