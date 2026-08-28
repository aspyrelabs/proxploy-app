import { UAParser } from 'ua-parser-js'

const OS_NAMES: Record<string, string> = {
  'Mac OS': 'macOS',
  'Chromium OS': 'ChromeOS',
}

/** "Chrome 141 on macOS", or the raw string when it is not a browser at all
 *  (curl, a script, our own CLI). Never the 120-character original: that is
 *  what the cell's tooltip is for. */
export function describeDevice(ua: string | null | undefined): string {
  if (!ua) return 'unknown'
  const { browser, os, device } = UAParser(ua)
  if (!browser.name && !os.name) return ua
  const app = [browser.name, browser.major].filter(Boolean).join(' ')
  const system = os.name ? (OS_NAMES[os.name] ?? os.name) : null
  const label = app && system ? `${app} on ${system}` : app || system || ua
  return device.model && device.model !== 'Macintosh'
    ? `${label} (${device.model})` : label
}
