#!/usr/bin/env node
// Proxploy browser driver. Drives the running dev app with Playwright's
// Chromium and reports what it found on stdout.
//
// Usage (from the repo root, with both dev servers already up):
//   node .claude/skills/run-proxploy/driver.mjs smoke
//   node .claude/skills/run-proxploy/driver.mjs shot /tmp/x.png [/onboarding]
//   node .claude/skills/run-proxploy/driver.mjs measure aside 'aside svg' [/path]
//   node .claude/skills/run-proxploy/driver.mjs text [/path]
//   node .claude/skills/run-proxploy/driver.mjs overflow <dir-or-url> <sel> [w,w]
//
// Deliberately imports Playwright by absolute path out of frontend/: this file
// sits in .claude/skills/, which has no node_modules of its own and is not part
// of any package. A bare `import 'playwright'` does not resolve from here.

import { createServer } from 'node:http'
import { createReadStream, statSync } from 'node:fs'
import { extname } from 'node:path'
import { basename, dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const { chromium } = await import('playwright')

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

/**
 * Fixed-height overflow check, across viewport widths, for an ARBITRARY url.
 *
 * `measure` above cannot do this job and should not be bent into it: it
 * prepends WEB to a path (so it only reaches the dev app, which is behind
 * login), it takes one bounding box per selector (so it cannot compare a row
 * of cards), and it runs at a single fixed viewport. This takes a full url
 * (file:// included), measures EVERY match, and reports the two properties a
 * fixed-height component has to satisfy:
 *
 *   scrollHeight > clientHeight   content overflows its own box, which is the
 *                                 failure that shipped as text-over-text
 *   offsetHeight all equal        the other half of what a fixed height buys
 *
 * The label comes from the nearest [data-state] ancestor, so output names the
 * state rather than an index.
 */
const MIME = {
  '.html': 'text/html', '.js': 'text/javascript', '.css': 'text/css',
  '.woff2': 'font/woff2', '.woff': 'font/woff', '.json': 'application/json',
  '.svg': 'image/svg+xml', '.png': 'image/png',
}

/**
 * Serve a directory on an EPHEMERAL port, and hand back its url.
 *
 * A built page cannot simply be opened over file://: its entry is an ES
 * module, and Chromium refuses module and stylesheet loads from a null origin
 * under CORS, so the page renders blank and every measurement silently comes
 * back empty. Port 0 lets the OS pick, which is also what keeps this away from
 * the dev servers on 5173 and 8000.
 */
function serveDir(dir) {
  const server = createServer((req, res) => {
    const rel = decodeURIComponent(req.url.split('?')[0])
    const file = resolve(dir, '.' + (rel === '/' ? '/index.html' : rel))
    if (!file.startsWith(dir)) { res.writeHead(403).end(); return }
    try {
      statSync(file)
    } catch {
      res.writeHead(404).end(); return
    }
    res.writeHead(200, { 'content-type': MIME[extname(file)] ?? 'application/octet-stream' })
    createReadStream(file).pipe(res)
  })
  return new Promise(ok => {
    server.listen(0, '127.0.0.1', () =>
      ok({ url: `http://127.0.0.1:${server.address().port}/`, close: () => server.close() }))
  })
}

async function overflow() {
  const flags = args.filter(a => a.startsWith('--'))
  const positional = args.filter(a => !a.startsWith('--'))
  const [target, selector = '.rounded-card', sizes = '1280,1920,2560,3840,375'] = positional
  const strict = flags.includes('--fail-on-overflow')
  // Percent of viewport height a match may occupy, for a capped panel. Only
  // checked when asked for, since a card has no such cap.
  const maxVh = Number(flags.find(f => f.startsWith('--max-vh='))?.split('=')[1] ?? 0)
  if (!target) {
    console.error('usage: overflow <path-or-url> [selector] [WxH,W,...] [--fail-on-overflow] [--max-vh=N]')
    process.exit(2)
  }
  // A file target serves its own directory and navigates to that file, so a
  // multi-page harness can point at one of its pages.
  let url = target
  let served = null
  if (!target.startsWith('http')) {
    const abs = resolve(target)
    const isFile = statSync(abs).isFile()
    served = await serveDir(isFile ? dirname(abs) : abs)
    url = served.url + (isFile ? basename(abs) : '')
  }
  const browser = await chromium.launch()
  try {
    const out = {}
    // "1280" keeps the default height; "1280x800" sets both, which is what a
    // vh-based cap has to be checked against.
    for (const size of sizes.split(',')) {
      const [w, h = 900] = size.split('x').map(Number)
      const page = await browser.newPage({ viewport: { width: w, height: h } })
      await page.goto(url, { waitUntil: 'networkidle' })
      // Webfonts change line boxes; measuring before they land measures the
      // fallback font instead of the real one.
      await page.evaluate(() => document.fonts.ready)
      out[size] = await page.evaluate(sel => {
        const cards = [...document.querySelectorAll(sel)]
        const lane = document.querySelector('main')
        return {
          viewport: { width: innerWidth, height: innerHeight },
          lane: lane ? Math.round(lane.getBoundingClientRect().width) : null,
          columns: new Set(cards.map(c => Math.round(c.getBoundingClientRect().x))).size,
          cards: cards.map(el => ({
            state: el.closest('[data-state]')?.getAttribute('data-state') ?? '?',
            offsetHeight: el.offsetHeight,
            clientHeight: el.clientHeight,
            scrollHeight: el.scrollHeight,
            // scrollHeight > clientHeight is the failure. It is not a headroom
            // gauge though: a flex-1 spacer child grows to fill, so the two
            // stay equal right up until content overflows and then jump. The
            // spacer's OWN height is the number that shrinks toward zero, so
            // that is what is reported as slack, and it is what to watch.
            overflow: Math.max(0, el.scrollHeight - el.clientHeight),
            slack: el.querySelector(':scope > .flex-1')?.offsetHeight ?? null,
            // Position, so a capped panel can be checked for actually being
            // centred and for staying inside the viewport. An element that
            // overhangs the top reports a negative top, which is exactly the
            // symptom the height cap exists to prevent.
            top: Math.round(el.getBoundingClientRect().top),
            width: Math.round(el.getBoundingClientRect().width),
          })),
        }
      }, selector)
      await page.close()
    }
    console.log(JSON.stringify(out, null, 2))

    if (strict) {
      /**
       * THE GATE. Three conditions, each a real defect rather than a
       * threshold someone picked:
       *
       *  1. overflow > 0. Content did not fit its own fixed box. This is
       *     binary: either the browser had to hide something or it did not,
       *     so it needs no tolerance and gets none. It is exactly the 224px
       *     card bug, which overflowed by 9px.
       *  2. unequal offsetHeight among matches at one width. A fixed height
       *     exists to make a row line up; two different numbers mean it
       *     stopped doing that. Also exact: these elements share one class.
       *  3. a capped panel taller than its cap, when --max-vh says there is
       *     one. 1px of tolerance here and ONLY here, because 70vh of an odd
       *     viewport height is fractional and the browser rounds it.
       *
       * Deliberately NOT a slack threshold. Slack is reported so a human can
       * watch it shrink, but failing at "less than 6px spare" would trip on
       * an innocent copy change and teach everyone to ignore the gate.
       */
      const failures = []
      for (const [size, v] of Object.entries(out)) {
        for (const c of v.cards) {
          if (c.overflow > 0) failures.push(`${size}: ${c.state} overflows by ${c.overflow}px`)
        }
        const heights = new Set(v.cards.map(c => c.offsetHeight))
        if (v.cards.length > 1 && heights.size > 1) {
          failures.push(`${size}: heights differ across the row: ${[...heights].join(', ')}`)
        }
        if (maxVh > 0) {
          const cap = v.viewport.height * (maxVh / 100)
          for (const c of v.cards) {
            if (c.offsetHeight > cap + 1) {
              failures.push(`${size}: ${c.state} is ${c.offsetHeight}px, over the ${maxVh}vh cap of ${Math.round(cap)}px`)
            }
          }
        }
        if (v.cards.length === 0) failures.push(`${size}: selector matched nothing`)
      }
      if (failures.length) {
        console.error('\nFAIL: ' + failures.length + ' geometry problem(s)')
        for (const f of failures) console.error('  - ' + f)
        process.exitCode = 1
      } else {
        console.error('\nok: no overflow, heights equal' + (maxVh ? `, within the ${maxVh}vh cap` : ''))
      }
    }
  } finally {
    await browser.close()
    served?.close()
  }
}

const commands = { smoke, shot, measure, text, overflow }

if (!commands[cmd]) {
  console.error(`usage: driver.mjs <${Object.keys(commands).join('|')}> [args]`)
  process.exit(2)
}
await commands[cmd]()
