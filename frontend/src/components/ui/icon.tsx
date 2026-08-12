import type { ComponentPropsWithoutRef } from 'react'

/**
 * Renders one Material Symbols (Outlined) glyph, by name (e.g. "settings").
 *
 * The font loads from the Google Fonts CDN (see vite.config.ts's
 * materialSymbolsLink plugin, which injects the <link> into index.html with
 * an `icon_names` parameter listing every name this app actually uses).
 * Proxploy's app store already downloads container templates over the
 * internet, so the box has connectivity by definition -- there is no
 * air-gapped case to build a self-hosted, build-time-subset font for.
 *
 * Material Symbols is a ligature font: typing the word "settings" as plain
 * text is what makes the font substitute the glyph, so this component's
 * text content is the readable name itself, not a decoded codepoint. A
 * screen reader has no reason to stay silent about a real word, so
 * `aria-hidden` is still load-bearing here, just for a more ordinary
 * reason than before: every call site places a label next to the icon (a
 * nav item's text, a button's aria-label), and that label is already the
 * accessible name -- an icon that also announced itself would read twice.
 * This component is the one place that rule is enforced, so no call site
 * can forget it.
 *
 * Sizing: a font glyph has no intrinsic box the way an SVG did, it renders
 * at `font-size` like any other character. `size` applies one number to
 * `font-size` AND to `width`/`height`, so the glyph keeps a fixed square
 * footprint regardless of what the surrounding layout expects (grid
 * columns, translate offsets, hit targets). Default 18, matching the most
 * common call-site size; four call sites pass a different one explicitly.
 */
type IconProps = {
  /** A Material Symbols (Outlined) name, e.g. "settings". Must also appear
   *  in the Google Fonts link's `icon_names` list (vite.config.ts) or it
   *  renders as the literal word instead of a glyph -- that list is
   *  generated from every <Icon name="..."> and icon: '...' literal in
   *  src/, so using a real name here is enough; see scripts/icon-names.mjs. */
  name: string
  /** Pixel size, applied to both font-size and the box the glyph sits in.
   *  Defaults to 18, the size Heroicons used everywhere except the four
   *  call sites that pass a size explicitly. */
  size?: number
  className?: string
} & Omit<ComponentPropsWithoutRef<'span'>, 'className' | 'children'>

export function Icon({ name, size = 18, className = '', ...rest }: IconProps) {
  return (
    <span
      aria-hidden="true"
      className={`material-symbols-outlined inline-block shrink-0 select-none align-middle leading-none ${className}`}
      style={{ fontSize: size, width: size, height: size }}
      {...rest}
    >
      {name}
    </span>
  )
}
