#!/usr/bin/env node
// Builds the production Material Symbols font subset. Runs as the first
// step of `npm run build` (see package.json's "build" script) so a normal
// build always produces a fresh subset; it is never run in dev (see
// src/styles/load-icon-font.ts, which loads the full font from
// node_modules instead).
//
// The full outlined variable font ships every Material Symbols glyph
// (~3,600 icons, ~3.5MB). This app only ever uses the names
// scripts/icon-names.mjs finds referenced in src/, so the shipped font is
// subset down to just those, by codepoint (see
// src/lib/material-symbols-codepoints.mjs for why codepoint and not the
// font's ligature names -- short version: subsetting by ligature name
// forces harfbuzz to retain most of the shared GSUB tree behind ALL 3,600
// icons, measured at 3.3MB; by codepoint it needs none of that GSUB
// machinery at all, measured at 2.4KB for the same 23 icons).
import { mkdirSync, readFileSync, writeFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import subsetFont from 'subset-font'
import { extractIconNames } from './icon-names.mjs'
import { MATERIAL_SYMBOLS_CODEPOINTS } from '../src/lib/material-symbols-codepoints.mjs'

const here = dirname(fileURLToPath(import.meta.url))
const frontendRoot = join(here, '..')
const srcDir = join(frontendRoot, 'src')
const fontPath = join(frontendRoot, 'node_modules/material-symbols/material-symbols-outlined.woff2')
const outDir = join(srcDir, 'styles/generated')

const names = extractIconNames(srcDir)
if (names.size === 0) {
  throw new Error('build-icon-font: found zero Icon names in src/ -- refusing to ship an empty font subset')
}

// Every extracted name must resolve to a codepoint, or the resulting font
// would silently be missing a glyph a component actually renders -- fail
// the build loudly here instead, before that ships.
const unmapped = [...names].filter((name) => MATERIAL_SYMBOLS_CODEPOINTS[name] === undefined)
if (unmapped.length > 0) {
  throw new Error(
    `build-icon-font: no codepoint for: ${unmapped.join(', ')}. ` +
    `Add each to src/lib/material-symbols-codepoints.mjs (look them up at https://fonts.google.com/icons).`,
  )
}

const text = [...names].map((name) => String.fromCodePoint(MATERIAL_SYMBOLS_CODEPOINTS[name])).join('')
const originalFont = readFileSync(fontPath)
const subsetBuffer = await subsetFont(originalFont, text, {
  targetFormat: 'woff2',
  // This app never varies weight, fill, grade or optical size, so pin the
  // variable font to one static instance rather than shipping every axis's
  // interpolation data for icons that never move along any of them.
  // Values match the package's own CSS default (24px "outlined", regular
  // weight, ungraded, unfilled).
  variationAxes: { FILL: 0, wght: 400, GRAD: 0, opsz: 24 },
})

mkdirSync(outDir, { recursive: true })
writeFileSync(join(outDir, 'material-symbols-subset.woff2'), subsetBuffer)

// font-display: block, carried over from the package's own outlined.css
// (see the material symbols report): the glyph is invisible rather than
// flashed as anything else while this ~KB-scale font loads.
writeFileSync(join(outDir, 'icon-font-subset.css'), `@font-face {
  font-family: "Material Symbols Outlined";
  font-style: normal;
  font-weight: normal;
  font-display: block;
  src: url("./material-symbols-subset.woff2") format("woff2");
}
.material-symbols-outlined {
  font-family: "Material Symbols Outlined";
  font-weight: normal;
  font-style: normal;
  font-size: 24px;
  line-height: 1;
  letter-spacing: normal;
  text-transform: none;
  display: inline-block;
  white-space: nowrap;
  word-wrap: normal;
  direction: ltr;
  -webkit-font-smoothing: antialiased;
  -moz-osx-font-smoothing: grayscale;
  text-rendering: optimizeLegibility;
}
`)

const kb = (n) => `${(n / 1024).toFixed(2)}KB`
console.log(`build-icon-font: subset ${names.size} icon(s) -> ${kb(subsetBuffer.length)} (full font is ${kb(originalFont.length)})`)
