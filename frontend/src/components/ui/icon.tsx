import type { ComponentPropsWithoutRef } from 'react'

/**
 * Renders one Material Symbols (Outlined) glyph by name (e.g. "settings").
 *
 * The font loads from the Google Fonts CDN: vite.config.ts's
 * materialSymbolsLink plugin injects the <link> with an `icon_names` list of
 * every name the app uses (no air-gapped case to self-host for).
 *
 * It is a ligature font, so the text content is the readable name itself,
 * not a decoded codepoint. Every call site already labels the icon (nav
 * text, button aria-label), so `aria-hidden` keeps it from announcing twice.
 *
 * A glyph has no intrinsic box: `size` applies one number to `font-size` AND
 * `width`/`height`, keeping a fixed square footprint. Default 18.
 */
type IconProps = {
  /** A Material Symbols (Outlined) name, e.g. "settings". Must also appear
   *  in the Google Fonts link's `icon_names` list (vite.config.ts) or it
   *  renders as the literal word instead of a glyph -- that list is
   *  generated from every <Icon name="..."> and icon: '...' literal in
   *  src/, so using a real name here is enough; see scripts/icon-names.mjs. */
  name: string
  /** Pixel size, applied to both font-size and the box the glyph sits in.
   *  Defaults to 18. */
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
