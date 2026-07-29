// LockVeil.tsx — doc 06 §e rule 1: never hide gated features; veil them.
import type { ReactNode } from 'react'
import { Button } from './ui/button'
import { useNavigate } from '@tanstack/react-router'

export function LockVeil({ locked, title, subtitle, children }:
  { locked: boolean; title: string; subtitle: string; children: ReactNode }) {
  const navigate = useNavigate()
  if (!locked) return <>{children}</>
  return (
    <div className="relative overflow-hidden rounded-card">
      <div className="pointer-events-none blur-[1px]">{children}</div>
      <div className="absolute inset-0 grid place-items-center bg-[rgba(11,15,22,.72)] backdrop-blur-[3px]">
        <div className="text-center">
          <div className="mb-2 text-[22px] text-amber">🔒</div>
          <div className="font-display text-[15px] font-semibold">{title}</div>
          <p className="mb-3 mt-1 text-[12.5px] text-text-3">{subtitle}</p>
          <Button variant="go" onClick={() => navigate({ to: '/settings' })}>Unlock Pro</Button>
        </div>
      </div>
    </div>
  )
}
