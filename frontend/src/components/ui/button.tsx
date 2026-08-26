import { forwardRef } from 'react'
import type { ButtonHTMLAttributes } from 'react'

import { cn } from '@/lib/utils'

/** Clickable name: resting text so it reads as content first; amber hover marks it clickable. */
export const linkCls = 'text-text transition hover:text-amber'

/** Secondary action (Dismiss, Advanced, Back): muted until pointed at. Base of the `icon` variant below. */
export const quietCls = 'text-text-3 transition hover:text-text'

/** Onward link: amber at rest is the whole affordance (no surrounding chrome says "clickable"). */
export const amberLinkCls = 'text-amber transition hover:underline'

/**
 * One option in a segmented control (chip, filter, range, nav). Selected is a
 * hue change (amber), hover a surface change — two signals that must not
 * collide. A function so call sites share the ternary instead of repeating it.
 */
export const segment = (on: boolean) =>
  on ? 'bg-amber-dim text-amber'
     : 'text-text-2 transition hover:bg-panel-2 hover:text-text'

const variants = {
  primary: 'bg-[linear-gradient(150deg,#F5B544,#E79126)] text-[#20160a] font-semibold shadow-[0_6px_18px_rgba(245,181,68,.25)] hover:brightness-105',
  ghost: 'bg-panel-2 text-text border border-line hover:bg-elev',
  danger: 'bg-red-dim text-red border border-red/30 hover:bg-red/20',
  // Start MAKES something run, so it is the one green control; built like `danger` so the pair reads as opposites.
  success: 'bg-green-dim text-green border border-green/30 hover:bg-green/20',
  go: 'bg-amber-dim text-amber border border-amber/30 hover:bg-amber/20',
  // Table-row actions (edit, delete, reorder): no background/border, tint only,
  // hover is the affordance. Delete is the majority and must not be a copied class string.
  icon: quietCls,
  'icon-danger': 'text-text-3 transition hover:text-red',
} as const

// 'md' reproduces exactly what the base class list used to hardcode, so existing call sites render byte-identical markup.
const sizes = {
  md: 'px-3.5 py-2 text-[13px]',
  // The small size, for the App Store card's Install button (a full-size control
  // dominates the 284px card). Whole pixels, because fractional font sizes blur.
  // Deliberately small on a touch screen; see the note in StoreCard.tsx.
  xs: 'px-[9px] py-1.5 text-[9px]',
  // xs + 20%, whole pixels. Own entry (not a bump to xs): xs is load-bearing
  // for the App Store card's pinned 240px height.
  sm: 'px-[11px] py-[7px] text-[11px]',
  'icon-xs': 'h-6 w-6 p-0',
} as const

type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: keyof typeof variants
  size?: keyof typeof sizes
}

// forwardRef so Radix `asChild` triggers (Tooltip, Popover, DropdownMenu) can attach a ref.
export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { variant = 'primary', size = 'md', className = '', ...props }, ref) {
  return (
    <button
      ref={ref}
      // cn (tailwind-merge), not a template string: concatenation let CSS file
      // order decide conflicts (`.px-3\.5` after `.px-2`), so a caller's
      // className lost; cn makes the caller win.
      className={cn(
        // whitespace-nowrap: a label is a phrase; breaking mid-phrase ("Set up"
        // -> "Set"/"up") reads as two buttons. A caller can still wrap via className.
        'inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-ctl cursor-pointer transition disabled:opacity-50 disabled:cursor-not-allowed',
        sizes[size], variants[variant], className)}
      {...props}
    />
  )
})
