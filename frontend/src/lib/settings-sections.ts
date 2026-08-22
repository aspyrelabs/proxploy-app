/**
 * The Settings page's sections: the rail, the ?section= contract, and what the
 * command palette can jump to.
 *
 * In lib/ rather than in routes/settings.tsx because CommandPalette needs it
 * too, and importing the route would close a cycle: settings.tsx imports
 * shellRoute from routes/shell.tsx, which renders AppShell, which mounts
 * CommandPalette. Same hazard routes/cluster.tsx and routes/shell.tsx already
 * carry warnings about.
 */

export type SettingsSection = {
  id: string
  label: string
  /** Extra terms the palette matches on, beyond the label and group name. */
  keywords: string[]
}

/**
 * Grouped by WHO a setting belongs to, which is the split the cards already
 * make in the code and never made on screen: six configure the installation,
 * two configure you, two describe the Proxploy application itself.
 *
 * `profile` is deliberately one section holding three cards. Two-factor,
 * Sessions and Trusted devices are one subject -- how you get in and what is
 * still allowed to -- and splitting them across three rail entries would mean
 * revoking a session in one place and the device that skips its second factor
 * in another, with nothing on screen connecting them.
 *
 * Which is exactly why `keywords` is not decoration on that row. Merging three
 * cards under one name takes "sessions" and "trusted devices" out of the
 * rail's own text, so without these an operator searching for either finds
 * nothing at all -- the palette would have made the merge cost findability.
 */
export const SETTINGS_SECTIONS: { group: string; items: SettingsSection[] }[] = [
  { group: 'General', items: [
    { id: 'hosts', label: 'Hosts',
      keywords: ['node', 'proxmox', 'enrol', 'enroll', 'add host', 'node shell'] },
    { id: 'notifications', label: 'Notifications',
      keywords: ['channel', 'ntfy', 'telegram', 'email', 'notify'] },
    { id: 'schedules', label: 'Schedules',
      keywords: ['cron', 'timer', 'scheduled job', 'recurring'] },
    { id: 'teams', label: 'Teams',
      keywords: ['rbac', 'role', 'permission', 'member'] },
    { id: 'users', label: 'Users',
      keywords: ['account', 'invite', 'reset password', 'admin'] },
    { id: 'api-keys', label: 'API keys',
      keywords: ['token', 'api token', 'integration', 'revoke key'] },
  ] },
  { group: 'Your account', items: [
    { id: 'profile', label: 'Profile',
      keywords: ['two-factor', 'two factor', '2fa', 'mfa', 'totp', 'authenticator',
                 'recovery codes', 'sessions', 'sign out', 'trusted devices'] },
    { id: 'console', label: 'Console',
      keywords: ['terminal', 'shell', 'font size', 'colour', 'color', 'theme'] },
  ] },
  { group: 'Application', items: [
    { id: 'plan', label: 'Plan',
      keywords: ['licence', 'license', 'tier', 'entitlement', 'upgrade'] },
    { id: 'updates', label: 'Updates',
      keywords: ['version', 'upgrade', 'release', 'changelog'] },
  ] },
]

export const SETTINGS_SECTION_IDS = new Set(
  SETTINGS_SECTIONS.flatMap(g => g.items.map(i => i.id)))

export const DEFAULT_SETTINGS_SECTION = 'hosts'

/**
 * Sections matching a typed query, each with the group it came from so the
 * palette can say "Profile · Your account" rather than a bare "Profile".
 *
 * Plain case-insensitive substring, no ranking: ten sections is a list an
 * operator reads in full, and a relevance score over ten rows would be
 * machinery dressed up as an answer. An empty query matches nothing rather
 * than everything, so the palette's own "type to search" state still reads
 * as the empty state it is.
 */
export function matchSettingsSections(query: string): (SettingsSection & { group: string })[] {
  const q = query.trim().toLowerCase()
  if (!q) return []
  return SETTINGS_SECTIONS.flatMap(g => g.items
    .filter(i => i.label.toLowerCase().includes(q)
      || g.group.toLowerCase().includes(q)
      || i.keywords.some(k => k.includes(q)))
    .map(i => ({ ...i, group: g.group })))
}
