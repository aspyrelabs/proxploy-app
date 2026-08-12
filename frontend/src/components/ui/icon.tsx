import type { ComponentPropsWithoutRef } from 'react'
import { MATERIAL_SYMBOLS_CODEPOINTS } from '../../lib/material-symbols-codepoints.mjs'

/**
 * Renders one Material Symbols (Outlined) glyph, by name (e.g. "settings").
 *
 * Material Symbols ships each glyph two ways: as a ligature (type the word
 * "settings" as text, the font substitutes an icon) and as a Private Use
 * Area codepoint (map straight to the glyph via cmap, no substitution). This
 * component uses the codepoint form, not the ligature: subsetting by
 * ligature name forces harfbuzz to retain most of the font's shared GSUB
 * substitution tree even for a couple dozen icons (measured 3.3MB, barely
 * under the 3.9MB full font); subsetting by codepoint needs none of that
 * (measured 2.4KB for the same 23 icons). See the material symbols report.
 *
 * The DOM still ends up with a text node either way (a lone Private Use
 * Area character rather than the readable word), and a screen reader has no
 * defined pronunciation for a PUA character -- so this is still hidden from
 * the accessibility tree by default, same as the ligature form would need.
 * This component is the one place that rule is enforced, so no call site
 * can forget it. `data-icon` carries the readable name for anything that
 * needs to inspect it (devtools, tests) without decoding the character.
 *
 * Sizing: Heroicons (SVGs) were sized with Tailwind width/height classes
 * (`h-[18px] w-[18px]`). A font glyph has no intrinsic box to size that way
 * -- it renders at `font-size` like any other character. `size` replaces
 * the old class pairs with a single number, applied to `font-size` AND to
 * `width`/`height`, so the glyph keeps the exact square footprint (and thus
 * layout: grid columns, translate offsets, hit targets) the SVG used to
 * occupy. The default (18) matches the most common Heroicons size in this
 * codebase; call sites that used a different size (16, 14, 20) pass it
 * explicitly.
 */
type IconProps = {
  /** A Material Symbols (Outlined) name, e.g. "settings" -- must have an
   *  entry in lib/material-symbols-codepoints.ts. */
  name: string
  /** Pixel size, applied to both font-size and the box the glyph sits in.
   *  Defaults to 18, the size Heroicons used everywhere except the four
   *  call sites that pass a size explicitly. */
  size?: number
  className?: string
} & Omit<ComponentPropsWithoutRef<'span'>, 'className' | 'children'>

export function Icon({ name, size = 18, className = '', ...rest }: IconProps) {
  const codepoint = MATERIAL_SYMBOLS_CODEPOINTS[name]
  if (codepoint === undefined) {
    throw new Error(
      `Icon: "${name}" has no entry in lib/material-symbols-codepoints.ts. ` +
      `Look up its codepoint at https://fonts.google.com/icons and add it there.`,
    )
  }
  return (
    <span
      aria-hidden="true"
      data-icon={name}
      className={`material-symbols-outlined inline-block shrink-0 select-none align-middle leading-none ${className}`}
      style={{ fontSize: size, width: size, height: size }}
      {...rest}
    >
      {String.fromCodePoint(codepoint)}
    </span>
  )
}
