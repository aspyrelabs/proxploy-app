import { useEffect, useState } from 'react'
import { MoonIcon, SunIcon } from '@heroicons/react/24/outline'
import { applyStoredTheme, setStoredTheme } from '../lib/theme'

export function ThemeToggle() {
  const [theme, setTheme] = useState(applyStoredTheme)
  useEffect(() => {
    setStoredTheme(theme)
  }, [theme])
  return (
    <button aria-label="Toggle theme" title="Toggle theme"
      onClick={() => setTheme(t => (t === 'dark' ? 'light' : 'dark'))}
      className="inline-flex items-center gap-1.5 rounded-ctl border border-line bg-panel-2 px-2.5 py-1.5 text-[12px] text-text-2 hover:bg-elev">
      {theme === 'dark'
        ? <><SunIcon aria-hidden className="h-4 w-4" /> Light</>
        : <><MoonIcon aria-hidden className="h-4 w-4" /> Dark</>}
    </button>
  )
}
