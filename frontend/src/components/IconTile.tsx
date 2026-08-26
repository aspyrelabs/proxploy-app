import { useState } from 'react'
import { STORE_GRADIENT } from './UsageBar'

/**
 * The app logo, or an initials tile when there is no logo to draw.
 *
 * One component for the Store/Apps card and detail so an installed app always
 * shows the icon of the Store entry it was installed from and the two never
 * diverge. The fallback is expected, never an error — scripts are the source
 * of truth and the logo is decoration, so a missing one must not break the
 * card.
 */
export function IconTile({ name, iconUrl, size, initials, colors }: {
  name: string
  iconUrl: string | null
  /** 32 = icon grid, 40 = card, 56 = detail header. Closed set so the tile
   *  carries its own radius and glyph size; 32 uses the tighter radius because
   *  rounded-card eats a 32px box's corners. */
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
