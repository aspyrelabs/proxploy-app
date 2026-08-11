import { useState } from 'react'
import * as DropdownMenu from '@radix-ui/react-dropdown-menu'
import { Link, useNavigate } from '@tanstack/react-router'
import { useQueryClient } from '@tanstack/react-query'
import { api } from '../api/client'
import { useMe } from '../api/hooks'

/** The avatar, and everything that belongs behind it.
 *
 *  It used to be a <span> with a letter in it: no menu, no profile, and
 *  POST /auth/logout was called from nowhere in the frontend, so there was no
 *  way to sign out of the app at all. */
export function AccountMenu() {
  const { data: me } = useMe()
  const [open, setOpen] = useState(false)
  const navigate = useNavigate()
  const qc = useQueryClient()
  async function signOut() {
    // Clear the cache before leaving: React Query would otherwise serve the
    // previous user's cached /auth/me, hosts and jobs to whoever signs in next
    // on this browser.
    try { await api('/auth/logout', { method: 'POST' }) } finally {
      qc.clear()
      setOpen(false)
      navigate({ to: '/login' as never })
    }
  }

  const letter = (me?.display_name ?? me?.email ?? '?').slice(0, 1).toUpperCase()

  return (
    <DropdownMenu.Root open={open} onOpenChange={setOpen}>
      <DropdownMenu.Trigger
        aria-label="Account"
        className="grid h-8 w-8 cursor-pointer place-items-center rounded-tile
                   bg-[linear-gradient(150deg,#5B9DF9,#7C5CFB)] font-display text-[12px]
                   font-semibold text-white transition hover:brightness-110"
      >
        {letter}
      </DropdownMenu.Trigger>

      <DropdownMenu.Portal>
        <DropdownMenu.Content
          align="end"
          sideOffset={8}
          className="z-50 w-56 overflow-hidden rounded-card border border-line bg-panel
                     shadow-[0_12px_32px_rgba(0,0,0,.35)]"
        >
          <DropdownMenu.Label className="border-b border-line-soft px-3 py-2.5">
            <p className="truncate text-[13px] text-text">{me?.display_name || 'Signed in'}</p>
            <p className="truncate text-[11.5px] text-text-3">{me?.email}</p>
            {me?.role && (
              <p className="mt-1 font-mono text-[10px] uppercase tracking-wide text-text-3">
                {me.role}
              </p>
            )}
          </DropdownMenu.Label>

          <DropdownMenu.Item asChild>
            <Link to={'/profile' as never}
              className="block cursor-pointer px-3 py-2 text-[13px] text-text-2 outline-none
                         data-[highlighted]:bg-panel-2 data-[highlighted]:text-text">
              Profile and security
            </Link>
          </DropdownMenu.Item>

          <DropdownMenu.Item asChild>
            <Link to={'/settings' as never}
              className="block cursor-pointer px-3 py-2 text-[13px] text-text-2 outline-none
                         data-[highlighted]:bg-panel-2 data-[highlighted]:text-text">
              Settings
            </Link>
          </DropdownMenu.Item>

          <DropdownMenu.Item
            onSelect={signOut}
            className="w-full cursor-pointer border-t border-line-soft px-3 py-2 text-left
                       text-[13px] text-red outline-none data-[highlighted]:bg-red-dim"
          >
            Sign out
          </DropdownMenu.Item>
        </DropdownMenu.Content>
      </DropdownMenu.Portal>
    </DropdownMenu.Root>
  )
}
