import { useEffect, useState } from 'react'

export function ThemeToggle() {
  const [theme, setTheme] = useState(() => localStorage.getItem('pp_theme') ?? 'dark')
  useEffect(() => {
    document.documentElement.dataset.theme = theme
    localStorage.setItem('pp_theme', theme)
  }, [theme])
  return (
    <button aria-label="Toggle theme" title="Toggle theme"
      onClick={() => setTheme(t => (t === 'dark' ? 'light' : 'dark'))}
      className="rounded-ctl border border-line bg-panel-2 px-2.5 py-1.5 text-[12px] text-text-2 hover:bg-elev">
      {theme === 'dark' ? '☀︎ Light' : '☾ Dark'}
    </button>
  )
}
