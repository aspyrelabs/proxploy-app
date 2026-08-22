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
 * The account half is split where the subject changes, not per card.
 * `profile` is who you are and how you prove it: your email and display name,
 * your password, your second factor. `sessions` is what is currently allowed
 * in on that basis: live sessions, and the browsers trusted to skip the second
 * factor. Trusted devices sits with Sessions rather than with Two-factor
 * because revoking a session and forgetting the browser that would walk
 * straight back in are the same job, done together.
 *
 * `keywords` is what keeps that grouping from costing findability. Cards
 * folded under a section name lose their own name from the rail's text, so
 * without these an operator searching "trusted devices" or "change password"
 * would find nothing at all.
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
      keywords: ['account', 'email', 'display name', 'role', 'password',
                 'change password', 'two-factor', 'two factor', '2fa', 'mfa',
                 'totp', 'authenticator', 'recovery codes'] },
    { id: 'sessions', label: 'Sessions',
      keywords: ['session', 'sign out', 'signed in', 'log out', 'revoke',
                 'trusted device', 'trusted devices', 'remember this browser'] },
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
