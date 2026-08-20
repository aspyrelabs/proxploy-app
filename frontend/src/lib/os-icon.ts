/**
 * PVE `ostype` to the icon that stands for it, or null when we cannot tell.
 *
 * The backend stores PVE's raw value rather than a collapsed "linux"/"windows"
 * label, deliberately: `win11` and `w2k19` are different facts and the API has
 * no way to recover the specific one once it has been thrown away. Reducing it
 * to a picture is a display decision, so it lives here.
 *
 * The values are a closed set that PVE defines:
 *   Linux    l24, l26
 *   Windows  wxp, w2k, w2k3, w2k8, wvista, win7, win8, win10, win11
 *   Neither  solaris, other
 * Matching on the leading letter would be shorter and would also quietly claim
 * `solaris` is Windows the day PVE adds an OS starting with w, so the two
 * families are listed out. An unknown value returns null rather than guessing,
 * which drops the tile back to its initials fallback.
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

/** What to call the icon out loud. `IconTile` renders the url as an <img> and
 *  uses the guest's own name as its alt text, so this is for anywhere the
 *  family itself needs saying rather than the guest. */
export function osLabel(osType: string | null | undefined): string | null {
  const url = osIconUrl(osType)
  if (url === '/linux.svg') return 'Linux'
  if (url === '/windows.svg') return 'Windows'
  return null
}
