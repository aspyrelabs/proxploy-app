// api/firewall.ts, firewall server state for every scope.
// Spec: docs/superpowers/specs/2026-08-21-firewall-design.md
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, ApiError } from './client'

/** Where a firewall lives. The four kinds map to four PVE path shapes, and
 *  basePath below is the only place that mapping exists. */
export type Scope =
  | { kind: 'cluster'; hostId: number }
  | { kind: 'node'; hostId: number; node: string }
  | { kind: 'group'; hostId: number; group: string }
  | { kind: 'guest'; guestType: 'app' | 'vm'; guestId: number }

/** Aliases, IP sets and references live at cluster and guest scope only. A node
 *  has none of its own, and a security group holds nothing but rules. */
export type ObjectScope = Extract<Scope, { kind: 'cluster' } | { kind: 'guest' }>

/** Proxmox writes a firewall log per node and per guest. There is no
 *  cluster-wide log. */
export type LogScope = Extract<Scope, { kind: 'node' } | { kind: 'guest' }>

/** A guest's firewall hangs off the router that owns the guest, not off
 *  /firewall: scope_app and scope_vm resolve a row's team from the URL path,
 *  so a guest id in a query string would carry no team scope at all. */
export function basePath(s: Scope): string {
  switch (s.kind) {
    case 'cluster': return `/firewall/cluster/${s.hostId}`
    case 'node': return `/firewall/node/${s.hostId}/${s.node}`
    case 'group': return `/firewall/cluster/${s.hostId}/groups/${encodeURIComponent(s.group)}`
    case 'guest': return `/${s.guestType === 'app' ? 'apps' : 'vms'}/${s.guestId}/firewall`
  }
}

/** Stable cache key for a scope. Object identity changes every render, so the
 *  key has to be the path, which is already a faithful identity for it. */
function key(s: Scope, ...rest: string[]) {
  return ['firewall', basePath(s), ...rest]
}

/** PVE's own field names. `enable` is an INTEGER, not a boolean: PVE's schema
 *  says "<integer> (0 - N)". `icmp-type` keeps its hyphen the whole way, since
 *  that is the only spelling PVE accepts. */
export type Rule = {
  pos: number
  type: 'in' | 'out' | 'forward' | 'group'
  action: string
  enable?: number
  macro?: string | null
  iface?: string | null
  source?: string | null
  dest?: string | null
  sport?: string | null
  dport?: string | null
  proto?: string | null
  log?: string | null
  'icmp-type'?: string | null
  comment?: string | null
  digest?: string
}

export type RulePatch = Partial<Omit<Rule, 'pos'>> & { digest?: string }
export type RulesRead = { scope: string; rules: Rule[]; digest: string | null }

export type Options = Record<string, string | number | undefined>
export type OptionsRead = {
  scope: string; options: Options; defaults: Options; digest: string | null
}

export type Ref = { type: 'alias' | 'ipset'; name: string; ref: string; comment?: string }
export type Macro = { macro: string; descr: string }
export type Group = { group: string; comment?: string; digest?: string }
export type Alias = { name: string; cidr: string; comment?: string; digest?: string }
export type IpSet = { name: string; comment?: string; digest?: string }
export type IpSetMember = { cidr: string; comment?: string; nomatch?: number; digest?: string }
export type LogLine = { n: number; t: string }

export function useRules(scope: Scope, enabled = true) {
  return useQuery({
    queryKey: key(scope, 'rules'),
    enabled,
    queryFn: () => api<RulesRead>(`${basePath(scope)}/rules`),
  })
}

/** Every mutation invalidates the whole scope rather than one list: a rule
 *  write shifts every later rule's `pos` AND mints a new digest, so the
 *  options read is stale too. */
function useScopeMutation<TVars>(scope: Scope,
                                 run: (v: TVars) => Promise<unknown>) {
  const qc = useQueryClient()
  return useMutation<unknown, ApiError, TVars>({
    mutationFn: run,
    onSettled: () => { qc.invalidateQueries({ queryKey: key(scope) }) },
  })
}

export function useCreateRule(scope: Scope) {
  return useScopeMutation<RulePatch>(scope, (rule) =>
    api(`${basePath(scope)}/rules`, { method: 'POST', body: JSON.stringify(rule) }))
}

export function useUpdateRule(scope: Scope) {
  return useScopeMutation<{ pos: number; patch: RulePatch }>(scope, (v) =>
    api(`${basePath(scope)}/rules/${v.pos}`,
      { method: 'PUT', body: JSON.stringify(v.patch) }))
}

export function useMoveRule(scope: Scope) {
  return useScopeMutation<{ pos: number; moveto: number; digest?: string | null }>(
    scope, (v) => api(`${basePath(scope)}/rules/${v.pos}/move`,
      { method: 'PUT', body: JSON.stringify({ moveto: v.moveto, digest: v.digest }) }))
}

export function useDeleteRule(scope: Scope) {
  return useScopeMutation<{ pos: number; digest?: string | null }>(scope, (v) =>
    api(`${basePath(scope)}/rules/${v.pos}${v.digest ? `?digest=${v.digest}` : ''}`,
      { method: 'DELETE' }))
}

export function useOptions(scope: Scope, enabled = true) {
  return useQuery({
    queryKey: key(scope, 'options'),
    enabled,
    queryFn: () => api<OptionsRead>(`${basePath(scope)}/options`),
  })
}

export function useUpdateOptions(scope: Scope) {
  return useScopeMutation<Options>(scope, (patch) =>
    api(`${basePath(scope)}/options`, { method: 'PUT', body: JSON.stringify(patch) }))
}

/** Aliases and IP sets live at cluster scope only, PVE keeps none on a node
 *  or a security group, so refs for a node or group rule (`+ipsetname`, an
 *  alias name) resolve against the cluster's, not against anything of the
 *  node's or group's own. */
function refScope(s: Scope): Scope {
  return s.kind === 'node' || s.kind === 'group' ? { kind: 'cluster', hostId: s.hostId } : s
}

export function useRefs(scope: Scope) {
  const s = refScope(scope)
  return useQuery({
    queryKey: key(s, 'refs'),
    queryFn: () => api<{ refs: Ref[] }>(`${basePath(s)}/refs`),
  })
}

export function useMacros(hostId: number) {
  return useQuery({
    // Macros are a fixed, cluster-wide, read-only list of about 90 entries and
    // they do not change while a page is open, so this is fetched once and
    // never refetched on focus.
    queryKey: ['firewall', 'macros', hostId],
    staleTime: Infinity,
    queryFn: () => api<{ macros: Macro[] }>(`/firewall/cluster/${hostId}/macros`),
  })
}

export function useGroups(hostId: number) {
  return useQuery({
    queryKey: ['firewall', 'groups', hostId],
    queryFn: () => api<{ groups: Group[] }>(`/firewall/cluster/${hostId}/groups`),
  })
}

export function useCreateGroup(hostId: number) {
  const qc = useQueryClient()
  return useMutation<unknown, ApiError, { group: string; comment?: string }>({
    mutationFn: (v) => api(`/firewall/cluster/${hostId}/groups`,
      { method: 'POST', body: JSON.stringify(v) }),
    onSettled: () => { qc.invalidateQueries({ queryKey: ['firewall', 'groups', hostId] }) },
  })
}

export function useDeleteGroup(hostId: number) {
  const qc = useQueryClient()
  return useMutation<unknown, ApiError, { group: string }>({
    mutationFn: (v) => api(
      `/firewall/cluster/${hostId}/groups/${encodeURIComponent(v.group)}`,
      { method: 'DELETE' }),
    onSettled: () => { qc.invalidateQueries({ queryKey: ['firewall', 'groups', hostId] }) },
  })
}

export function useAliases(scope: ObjectScope) {
  return useQuery({
    queryKey: key(scope, 'aliases'),
    queryFn: () => api<{ aliases: Alias[] }>(`${basePath(scope)}/aliases`),
  })
}

export function useCreateAlias(scope: ObjectScope) {
  return useScopeMutation<Alias>(scope, (a) =>
    api(`${basePath(scope)}/aliases`, { method: 'POST', body: JSON.stringify(a) }))
}

export function useUpdateAlias(scope: ObjectScope) {
  return useScopeMutation<{ name: string; patch: Partial<Alias> & { rename?: string } }>(
    scope, (v) => api(`${basePath(scope)}/aliases/${encodeURIComponent(v.name)}`,
      { method: 'PUT', body: JSON.stringify(v.patch) }))
}

export function useDeleteAlias(scope: ObjectScope) {
  return useScopeMutation<{ name: string }>(scope, (v) =>
    api(`${basePath(scope)}/aliases/${encodeURIComponent(v.name)}`, { method: 'DELETE' }))
}

export function useIpSets(scope: ObjectScope) {
  return useQuery({
    queryKey: key(scope, 'ipsets'),
    queryFn: () => api<{ ipsets: IpSet[] }>(`${basePath(scope)}/ipsets`),
  })
}

export function useCreateIpSet(scope: ObjectScope) {
  return useScopeMutation<IpSet>(scope, (s) =>
    api(`${basePath(scope)}/ipsets`, { method: 'POST', body: JSON.stringify(s) }))
}

/** `force` is always the caller's decision. PVE refuses to delete a populated
 *  set without it, and sending it by default would discard members the
 *  operator may never have opened. */
export function useDeleteIpSet(scope: ObjectScope) {
  return useScopeMutation<{ name: string; force: boolean }>(scope, (v) =>
    api(`${basePath(scope)}/ipsets/${encodeURIComponent(v.name)}?force=${v.force}`,
      { method: 'DELETE' }))
}

export function useIpSetMembers(scope: ObjectScope, name: string | null) {
  return useQuery({
    queryKey: key(scope, 'ipsets', name ?? ''),
    enabled: name != null,
    queryFn: () => api<{ members: IpSetMember[] }>(
      `${basePath(scope)}/ipsets/${encodeURIComponent(name!)}/members`),
  })
}

export function useAddIpSetMember(scope: ObjectScope) {
  return useScopeMutation<{ name: string; member: IpSetMember }>(scope, (v) =>
    api(`${basePath(scope)}/ipsets/${encodeURIComponent(v.name)}/members`,
      { method: 'POST', body: JSON.stringify(v.member) }))
}

/** encodeURIComponent on the CIDR, not template interpolation: the slash is a
 *  path separator on the way in as well as on the way out, and an unescaped
 *  one routes the call to a path that does not exist. */
export function useDeleteIpSetMember(scope: ObjectScope) {
  return useScopeMutation<{ name: string; cidr: string }>(scope, (v) =>
    api(`${basePath(scope)}/ipsets/${encodeURIComponent(v.name)}/members/`
        + encodeURIComponent(v.cidr), { method: 'DELETE' }))
}

export function useFirewallLog(scope: LogScope, start = 0, limit = 500) {
  return useQuery({
    queryKey: key(scope, 'log', String(start), String(limit)),
    refetchInterval: 10_000,
    queryFn: () => api<{ lines: LogLine[]; start: number; limit: number }>(
      `${basePath(scope)}/log?start=${start}&limit=${limit}`),
  })
}

/**
 * What turning this firewall on will actually do, in one sentence, or null
 * when there is nothing worth warning about.
 *
 * The whole reason this exists: an ABSENT policy is not "no policy", it is
 * PVE's default, and PVE defaults `policy_in` to DROP. An operator reading an
 * empty options object as "nothing configured, so nothing blocked" is the
 * exact misreading that got the per-NIC toggle removed in the first place.
 * The backend sends `defaults` alongside `options` so this can say what will
 * happen rather than what was typed.
 *
 * Proxploy warns and never blocks here, matching what Proxmox itself allows.
 *
 * `savedEnabled` is the firewall's state as PVE actually has it stored, not
 * whatever the operator is mid-typing: it decides the tense (present, "is
 * being dropped", for a firewall already on, versus conditional, "will be
 * dropped", for one that is not) so the sentence never claims a live outage
 * is hypothetical, or a hypothetical one as already happening.
 */
export function effectiveWarning(options: Options, defaults: Options,
                                 rules: Rule[], savedEnabled: boolean): string | null {
  const policyIn = String(options.policy_in ?? defaults.policy_in ?? '')
  if (policyIn !== 'DROP' && policyIn !== 'REJECT') return null
  const allows = rules.filter(
    r => r.type === 'in' && r.action === 'ACCEPT' && (r.enable ?? 0) !== 0).length
  const verb = policyIn === 'DROP' ? 'dropped' : 'rejected'
  // Tense follows what is SAVED, not what is pending. A firewall already on is
  // describing a guest's traffic right now, and calling that "will be" reads as
  // a hypothesis about something that has already happened.
  if (savedEnabled) {
    return allows === 0
      ? `Incoming traffic is being ${verb} by default, and no rule here allows `
        + `any through. Nothing can reach it until you add one.`
      : `Incoming traffic is being ${verb} by default. `
        + `${allows} rule${allows === 1 ? '' : 's'} here ${allows === 1 ? 'is' : 'are'} `
        + `letting traffic through.`
  }
  return allows === 0
    ? `If you turn this on, incoming traffic will be ${verb} by default, and no `
      + `rule here allows any through. Nothing will be able to reach it until you add one.`
    : `If you turn this on, incoming traffic will be ${verb} by default. `
      + `${allows} rule${allows === 1 ? '' : 's'} here will still let traffic through.`
}
