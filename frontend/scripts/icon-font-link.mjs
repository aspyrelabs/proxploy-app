// Builds the Google Fonts CDN href that serves exactly the Material Symbols
// (Outlined) icons this app uses, via the `icon_names` parameter -- so the
// browser downloads a font subset scoped to real usage without this app
// having to subset anything itself at build time.
//
// The axis range (opsz,wght,FILL,GRAD@20..48,100..700,0..1,-50..200) is the
// full variable-font range Google's own "get embed code" flow emits for
// Material Symbols Outlined; this app never varies any of those axes at
// runtime, but requesting a narrower range buys nothing (Google still signs
// and serves a font keyed to the exact query string, and a narrower range is
// one more thing to keep in sync by hand for no measured benefit).
const FAMILY_PARAM = 'Material+Symbols+Outlined:opsz,wght,FILL,GRAD@20..48,100..700,0..1,-50..200'

/** @param {Iterable<string>} names */
export function buildIconFontHref(names) {
  const sorted = [...new Set(names)].sort()
  if (sorted.length === 0) {
    throw new Error(
      'buildIconFontHref: no icon names given -- refusing to request a link with no icon_names ' +
      '(Google would serve the full ~3,600-glyph font instead of a subset).',
    )
  }
  return `https://fonts.googleapis.com/css2?family=${FAMILY_PARAM}&icon_names=${sorted.join(',')}`
}
