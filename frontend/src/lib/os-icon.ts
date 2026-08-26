/**
 * PVE `ostype` → icon, or null when unknown.
 *
 * The backend stores PVE's raw value (not a collapsed "linux"/"windows"), so
 * the specific OS can't be recovered once collapsed — that's why the mapping
 * lives at the display layer.
 *
 * Values are a closed set PVE defines. Matching the leading letter would
 * quietly claim `solaris` is Windows the day PVE adds an OS starting with w,
 * so both families are listed out and unknown values return null rather than
 * guess.
 *
 * Paths are absolute because Vite serves `public/` from the site root.
 */
const LINUX = new Set(['l24', 'l26'])
const WINDOWS = new Set(['wxp', 'w2k', 'w2k3', 'w2k8', 'wvista',
                         'win7', 'win8', 'win10', 'win11'])

export function osIconUrl(osType: string | null | undefined): string | null {
  if (!osType) return null
  const t = osType.trim().toLowerCase()
  if (LINUX.has(t)) return '/linux.svg'
  if (WINDOWS.has(t)) return '/windows.svg'
  return null
}

/** Display name for the OS family. `IconTile` uses the guest's own name as
 *  the <img> alt text, so this is where the family itself is named. */
export function osLabel(osType: string | null | undefined): string | null {
  const url = osIconUrl(osType)
  if (url === '/linux.svg') return 'Linux'
  if (url === '/windows.svg') return 'Windows'
  return null
}
