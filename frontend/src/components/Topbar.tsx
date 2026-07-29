import { ThemeToggle } from './ThemeToggle'
import { TierPill } from './TierPill'
import { useMe } from '../api/hooks'

export function Topbar() {
  const { data: me } = useMe()
  return (
    <header className="sticky top-0 z-10 flex items-center justify-end gap-3 border-b border-line-soft bg-[rgba(11,15,22,.82)] px-5 py-2.5 backdrop-blur-[10px]">
      <TierPill />
      <ThemeToggle />
      <span className="grid h-8 w-8 place-items-center rounded-tile bg-[linear-gradient(150deg,#5B9DF9,#7C5CFB)] font-display text-[12px] font-semibold text-white">
        {(me?.display_name ?? me?.email ?? '?').slice(0, 1).toUpperCase()}
      </span>
    </header>
  )
}
