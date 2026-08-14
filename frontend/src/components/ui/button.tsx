import { forwardRef } from 'react'
import type { ButtonHTMLAttributes } from 'react'

const variants = {
  primary: 'bg-[linear-gradient(150deg,#F5B544,#E79126)] text-[#20160a] font-semibold shadow-[0_6px_18px_rgba(245,181,68,.25)] hover:brightness-105',
  ghost: 'bg-panel-2 text-text border border-line hover:bg-elev',
  danger: 'bg-red-dim text-red border border-red/30 hover:bg-red/20',
  go: 'bg-amber-dim text-amber border border-amber/30 hover:bg-amber/20',
} as const

// Sizes were folded into the base class list until an icon-only control needed
// a square. 'md' reproduces exactly what the base used to hardcode, so every
// existing call site renders byte-identical markup.
const sizes = {
  md: 'px-3.5 py-2 text-[13px]',
  // The small size, used only by the App Store card's Install button, where a
  // full-size control dominates a 284px fixed-height card. Whole pixels
  // rather than fractions, because a fractional font size renders blurry.
  //
  // Against md, this is:
  //   px  14px -> 9px  (-35.7%)
  //   py   8px -> 6px  (-25.0%)
  //   text 13px -> 9px (-30.8%)
  //
  // Rendered height is roughly 25px, against md's roughly 35px. That is still
  // well under the ~44px usually recommended for a touch target, so this
  // stays a deliberately small control on a touch screen; see the note at the
  // call site in components/StoreCard.tsx.
  xs: 'px-[9px] py-1.5 text-[9px]',
  // xs plus 20%, rounded to whole pixels for the same blurry-text reason:
  //   px  9px -> 11px   py 6px -> 7px   text 9px -> 11px
  // Its own entry rather than a bump to xs, because xs is load bearing for
  // the App Store card, whose 240px height the geometry harness pins.
  sm: 'px-[11px] py-[7px] text-[11px]',
  'icon-xs': 'h-6 w-6 p-0',
} as const

type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: keyof typeof variants
  size?: keyof typeof sizes
}

// forwardRef so Radix's `asChild` triggers (Tooltip, Popover, DropdownMenu)
// can attach to a Button. Without it the ref lands nowhere and the trigger
// cannot position or wire aria against the element it is describing.
export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { variant = 'primary', size = 'md', className = '', ...props }, ref) {
  return (
    <button
      ref={ref}
      className={`inline-flex items-center justify-center gap-2 rounded-ctl cursor-pointer transition disabled:opacity-50 disabled:cursor-not-allowed ${sizes[size]} ${variants[variant]} ${className}`}
      {...props}
    />
  )
})
