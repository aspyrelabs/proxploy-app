/**
 * Lives in lib/ (not routes/settings.tsx) because CommandPalette imports it
 * too, and importing the route would close a cycle: settings.tsx → shell.tsx
 * → AppShell → CommandPalette.
 */

export type SettingsSection = {
  id: string
  label: string
  /** Extra terms the palette matches on, beyond the label and group name. */
  keywords: string[]
}

/**
 * Grouped by WHO a setting belongs to. Trusted devices sits with Sessions
 * rather than Two-factor because revoking a session and forgetting the browser
 * that would walk straight back in are the same job. `keywords` keeps cards
 * folded under a section name findable, since they lose their own name from
 * the rail's text.
 */
export const SETTINGS_SECTIONS: { group: string; items: SettingsSection[] }[] = [
  { group: 'General', items: [
    { id: 'hosts', label: 'Hosts',
      keywords: ['node', 'proxmox', 'enrol', 'enroll', 'add host', 'node shell'] },
    { id: 'maintenance', label: 'Maintenance',
      keywords: ['cron', 'timer', 'scheduled job', 'schedules', 'recurring',
                 'maintenance', 'catalog refresh', 'metrics'] },
    { id: 'teams', label: 'Teams',
      keywords: ['rbac', 'role', 'permission', 'member'] },
    { id: 'users', label: 'Users',
      keywords: ['account', 'invite', 'reset password', 'admin'] },
    { id: 'api-keys', label: 'API keys',
      keywords: ['token', 'api token', 'integration', 'revoke key'] },
  ] },
  // Split into its own group because Channels is WHERE anything goes and
  // Events is WHAT gets sent; Events is useful with no channel configured,
  // which the old single card could not express.
  { group: 'Notifications', items: [
    { id: 'channels', label: 'Channels',
      keywords: ['ntfy', 'gotify', 'telegram', 'email', 'smtp', 'slack',
                 'discord', 'webhook', 'notify', 'channel', 'apprise'] },
    { id: 'events', label: 'Events',
      keywords: ['notification', 'notify', 'toast', 'alert', 'job failed',
                 'backup failed', 'mute', 'turn off', 'housekeeping'] },
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

const RENAMED_SECTIONS: Record<string, string> = { schedules: 'maintenance' }

export function resolveSettingsSection(id: unknown): string | undefined {
  if (typeof id !== 'string') return undefined
  const current = RENAMED_SECTIONS[id] ?? id
  return SETTINGS_SECTION_IDS.has(current) ? current : undefined
}

export const DEFAULT_SETTINGS_SECTION = 'hosts'

/**
 * Sections matching a typed query, tagged with their group so the palette can
 * render "Profile · Your account". Plain substring, no ranking, and an empty
 * query matches nothing so the palette's "type to search" state stays empty.
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
