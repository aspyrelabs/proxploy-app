// Unicode Private Use Area codepoint for each Material Symbols (Outlined)
// glyph this app uses, keyed by the same lowercase snake_case name used at
// every <Icon name="..."> call site and in NAV's icon: '...' fields.
//
// Why codepoints instead of the font's ligature names ("type the word
// 'settings', the font substitutes an icon"): Material Symbols implements
// ligature substitution as one shared, deeply contextual GSUB decision tree
// spanning all ~3,600 icons. Subsetting by requesting even a couple dozen
// *names* (scripts/icon-names.mjs's approach, tried first) forces harfbuzz's
// GSUB closure to retain most of that shared tree -- measured at 3.3MB for
// this app's 23 icons, barely under the 3.9MB full font. Subsetting by
// *codepoint* instead needs no GSUB closure at all (a codepoint maps to its
// glyph directly via cmap), which is why every font in the material-symbols
// package also assigns each icon a PUA codepoint alongside its ligature name.
// Measured for the same 23 icons: 2.4KB. See the material symbols report for
// both figures.
//
// Sourced from google/material-design-icons's own generated codepoints file
// (variablefont/MaterialSymbolsOutlined[FILL,GRAD,opsz,wght].codepoints,
// which lists "name hexcode" one per line) and verified against the
// material-symbols package actually installed (0.45.10) by subsetting each
// codepoint individually and confirming it resolves to a real, distinct
// glyph rather than silently falling through to nothing.
//
// This table is necessarily hand-maintained -- a codepoint cannot be
// derived from its name -- but its failure mode is a loud build-time error
// (scripts/build-icon-font.mjs throws if an extracted name has no entry
// here), not a silently missing icon: unlike the *set of icons in use*
// (which scripts/icon-names.mjs extracts from source so it can never drift),
// there is no way to extract "what codepoint does Google assign to a name"
// from this codebase's own source.
export const MATERIAL_SYMBOLS_CODEPOINTS = {
  archive: 0xe149,
  cancel: 0xe888,
  check_circle: 0xf0be,
  close: 0xe5cd,
  computer: 0xe31e,
  dark_mode: 0xe51c,
  database: 0xf20e,
  dns: 0xe875,
  fact_check: 0xf0c5,
  grid_view: 0xe9b0,
  info: 0xe88e,
  keyboard_double_arrow_left: 0xeac3,
  keyboard_double_arrow_right: 0xeac9,
  light_mode: 0xe518,
  notes: 0xe26c,
  notifications: 0xe7f5,
  notifications_active: 0xe7f7,
  public: 0xe80b,
  refresh: 0xe5d5,
  search: 0xef7a,
  settings: 0xe8b8,
  storefront: 0xea12,
  warning: 0xf083,
}
