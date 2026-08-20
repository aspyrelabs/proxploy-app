import { useState } from 'react'
import { STORE_GRADIENT } from './UsageBar'

/**
 * The app logo, or the initials tile when there is no logo to draw.
 *
 * ONE component for four call sites (Store card and detail, Apps card and
 * detail) because they are one contract: an installed app must show the icon
 * of the Store entry it was installed from, and the only way to guarantee a
 * card and the thing installed from it never diverge is for both to render
 * through the same code. It was three near-copies before, and the Apps side
 * had no <img> at all, which is the bug this closes.
 *
 * The fallback is reached three ways and all three are expected, never an
 * error: no URL at all (upstream has no logo for this slug, or the app's
 * catalog entry is gone), the icon cache has not mirrored the file yet so the
 * URL points at a CDN that may be blocked or air-gapped, or the <img> simply
 * fails. Scripts are the source of truth and the logo is decoration, so a
 * missing one must never break the card.
 *
 * `initials` and `colors` come from the app row when there is one; the Store
 * has neither, so it gets the first two letters of the name on the shared
 * gradient, which is exactly what it drew before.
 */
export function IconTile({ name, iconUrl, size, initials, colors }: {
  name: string
  iconUrl: string | null
  /** 32 in the icon grid, 40 on a card, 56 on a detail header. A closed set
   *  rather than a free number, so the tile can carry the matching radius and
   *  glyph size with it instead of every caller restating them. 32 takes the
   *  smaller rounded-tile radius: rounded-card on a 32px box eats most of the
   *  artwork's corners. */
  size: 32 | 40 | 56
  initials?: string | null
  colors?: { c1: string; c2: string } | null
}) {
  const [broken, setBroken] = useState(false)
  const box = size === 32
    ? 'h-8 w-8 rounded-tile text-[11px]'
    : size === 40
      ? 'h-10 w-10 rounded-tile text-[14px]'
      : 'h-14 w-14 rounded-card text-[18px]'
  if (iconUrl && !broken) {
    return (
      <img
        src={iconUrl} alt={name} loading="lazy" width={size} height={size}
        className={`${box} object-contain`}
        onError={() => setBroken(true)}
      />
    )
  }
  return (
    <div
      className={`flex items-center justify-center font-display font-semibold text-white ${box}`}
      style={{
        background: colors
          ? `linear-gradient(135deg, ${colors.c1}, ${colors.c2})`
          : STORE_GRADIENT,
      }}
    >
      {(initials ?? name.slice(0, 2)).toUpperCase()}
    </div>
  )
}
