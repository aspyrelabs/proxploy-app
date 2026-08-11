#!/usr/bin/env node
// Proxploy browser driver. Drives the running dev app with Playwright's
// Chromium and reports what it found on stdout.
//
// Usage (from the repo root, with both dev servers already up):
//   node .claude/skills/run-proxploy/driver.mjs smoke
//   node .claude/skills/run-proxploy/driver.mjs shot /tmp/x.png [/onboarding]
//   node .claude/skills/run-proxploy/driver.mjs measure aside 'aside svg' [/path]
//   node .claude/skills/run-proxploy/driver.mjs text [/path]
//
// Deliberately imports Playwright by absolute path out of frontend/: this file
// sits in .claude/skills/, which has no node_modules of its own and is not part
// of any package. A bare `import 'playwright'` does not resolve from here.

import { createRequire } from 'node:module'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const HERE = dirname(fileURLToPath(import.meta.url))
const REPO = resolve(HERE, '../../..')
const require = createRequire(`${REPO}/frontend/package.json`)
const { chromium } = require('playwright')

// localhost, NOT 127.0.0.1: Vite 8 binds IPv6 here, so the v4 loopback is
// refused outright. The backend answers on either.
const WEB = process.env.PROXPLOY_WEB ?? 'http://localhost:5173'
const API = process.env.PROXPLOY_API ?? 'http://127.0.0.1:8000'

const [cmd, ...args] = process.argv.slice(2)

async function withPage(fn) {
  const browser = await chromium.launch()
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } })
  const errors = []
  page.on('console', m => { if (m.type() === 'error') errors.push(m.text()) })
  page.on('pageerror', e => errors.push(`pageerror: ${e.message}`))
  try {
    return await fn(page, errors)
  } finally {
    await browser.close()
  }
}

const goto = (page, path = '/') =>
  page.goto(WEB + path, { waitUntil: 'networkidle' })

async function smoke() {
  // Public and unauthenticated, unlike /meta/version which 401s. This is the
  // probe to use when checking the backend is actually serving.
  const ob = await fetch(`${API}/api/v1/meta/onboarding`).then(r => r.json())
  console.log('backend  :', JSON.stringify(ob))

  await withPage(async (page, errors) => {
    await goto(page, '/')
    console.log('landed on:', page.url())
    console.log('title    :', await page.title())
    console.log('errors   :', errors.length ? errors : 'none')
  })
}

async function shot() {
  const [out = '/tmp/proxploy.png', path = '/'] = args
  await withPage(async (page, errors) => {
    await goto(page, path)
    await page.screenshot({ path: out })
    console.log('saved    :', out, '(from', page.url() + ')')
    console.log('errors   :', errors.length ? errors : 'none')
  })
}

// Geometry, so layout claims are measured rather than eyeballed. Overlap bugs
// (a logo overhanging a divider) are obvious in numbers and arguable in a
// screenshot.
async function measure() {
  const selectors = args.filter(a => !a.startsWith('/'))
  const path = args.find(a => a.startsWith('/')) ?? '/'
  await withPage(async page => {
    await goto(page, path)
    const out = await page.evaluate(sels => sels.map(sel => {
      const el = document.querySelector(sel)
      if (!el) return { sel, found: false }
      const { x, y, width, height, right, bottom } = el.getBoundingClientRect()
      return { sel, found: true, x, y, width, height, right, bottom }
    }), selectors)
    console.log(JSON.stringify(out, null, 2))
  })
}

async function text() {
  const [path = '/'] = args
  await withPage(async page => {
    await goto(page, path)
    console.log((await page.locator('body').innerText()).trim())
  })
}

const commands = { smoke, shot, measure, text }

if (!commands[cmd]) {
  console.error(`usage: driver.mjs <${Object.keys(commands).join('|')}> [args]`)
  process.exit(2)
}
await commands[cmd]()
