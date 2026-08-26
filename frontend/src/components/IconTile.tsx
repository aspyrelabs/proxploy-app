import { useState } from 'react'

/** The dark/light pair stored on the app row by services/app_identity.py. */
export type IconColors = { dark: string; light: string }

/**
 * The app logo, or a monogram tile when there is no logo to draw.
 *
 * One component for the Store/Apps card and detail so an installed app always
 * shows the icon of the Store entry it was installed from and the two never
 * diverge. The fallback is expected, never an error — scripts are the source
 * of truth and the logo is decoration, so a missing one must not break the
 * card.
 *
 * The monogram is set in the mono face, which is a functional choice and not a
 * stylistic one: a proportional three-letter monogram changes width with its
 * letters, so `III` and `WWW` would sit differently inside a 32px box and a
 * column of tiles would visibly jitter. A fixed advance keeps every tile
 * optically identical, which is what lets three letters fit at 32px at all.
 */
export function IconTile({ name, iconUrl, size, initials, colors }: {
  name: string
  iconUrl: string | null
  /** 32 = icon grid, 40 = card, 56 = detail header. Closed set so the tile
   *  carries its own radius and glyph size; 32 uses the tighter radius because
   *  rounded-card eats a 32px box's corners. */
  size: 32 | 40 | 56
  initials?: string | null
  colors?: IconColors | null
}) {
  const [broken, setBroken] = useState(false)
  const box = size === 32
    ? 'h-8 w-8 rounded-tile text-[10px]'
    : size === 40
      ? 'h-10 w-10 rounded-tile text-[12px]'
      : 'h-14 w-14 rounded-card text-[16px]'
  if (iconUrl && !broken) {
    return (
      <img
        src={iconUrl} alt={name} loading="lazy" width={size} height={size}
        className={`${box} object-contain`}
        onError={() => setBroken(true)}
      />
    )
  }
  // Rows adopted before app_identity.py existed carry no colours; the ramp's
  // first hue stands in rather than reintroducing the Store gradient, which is
  // the badge of a Store these apps never came from.
  const c = colors ?? { dark: '#5B9DF9', light: '#2F6FE0' }
  return (
    <div
      className={`mono-tile flex select-none items-center justify-center
                  font-mono font-bold tracking-[-0.04em] ${box}`}
      style={{ '--mono-dark': c.dark, '--mono-light': c.light } as React.CSSProperties}
      aria-hidden
    >
      {(initials ?? name.slice(0, 3)).toUpperCase()}
    </div>
  )
}
