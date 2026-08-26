import type { IconColors } from '../components/IconTile'

/**
 * The monogram ramp, mirroring backend/proxploy/services/app_identity.py.
 *
 * Duplicated rather than fetched: eight colour pairs are not worth an endpoint,
 * a round trip and a loading state on a colour picker. Kept honest by
 * backend/tests/test_app_identity.py, which reads THIS file and fails if the
 * two lists ever disagree.
 *
 * Deliberately no green, red or amber. Those are spoken for by StatusPill
 * (green = running, red = stopped, amber = paused/pending) and by the Store
 * gradient, so a red monogram beside a green RUNNING pill would read as an
 * error state. One cool-to-magenta ramp also makes a grid of these read as one
 * system rather than as confetti.
 */
export const RAMP: readonly IconColors[] = [
  { dark: '#5B9DF9', light: '#2F6FE0' },  // blue
  { dark: '#38BDF8', light: '#0C7FC4' },  // sky
  { dark: '#34D3C6', light: '#0FA8A0' },  // cyan
  { dark: '#7C8CF8', light: '#4C5DD8' },  // indigo
  { dark: '#A78BFA', light: '#7C5CFB' },  // violet
  { dark: '#C084FC', light: '#9333EA' },  // plum
  { dark: '#E879F9', light: '#C026D3' },  // orchid
  { dark: '#F472B6', light: '#DB2777' },  // pink
]

/**
 * Three characters standing in for `name`, matching `monogram()` in
 * services/app_identity.py so the value the dialog proposes is the value the
 * server would have picked.
 */
export function monogram(name: string): string {
  const parts = name.split(/[-_. ]+/).filter(Boolean)
  if (parts.length >= 3) {
    return parts.slice(0, 3).map((p) => p[0]).join('').toUpperCase()
  }
  return name.replace(/[-_. ]+/g, '').slice(0, 3).toUpperCase() || 'APP'
}
