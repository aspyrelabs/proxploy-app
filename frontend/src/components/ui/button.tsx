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
  'icon-xs': 'h-6 w-6 p-0',
} as const

export function Button({ variant = 'primary', size = 'md', className = '', ...props }:
  ButtonHTMLAttributes<HTMLButtonElement> & {
    variant?: keyof typeof variants
    size?: keyof typeof sizes
  }) {
  return (
    <button
      className={`inline-flex items-center justify-center gap-2 rounded-ctl cursor-pointer transition disabled:opacity-50 disabled:cursor-not-allowed ${sizes[size]} ${variants[variant]} ${className}`}
      {...props}
    />
  )
}
