import { useId, useState } from 'react'
import * as Tabs from '@radix-ui/react-tabs'
import { createRoute, useParams } from '@tanstack/react-router'
import { useQuery } from '@tanstack/react-query'
import { api } from '../api/client'
import type { AppRow, NodeRow, VmRow } from '../api/hooks'
import { useEntitlements, useMe } from '../api/hooks'
import type { Rule, Scope } from '../api/firewall'
import { AliasTable, IpSetPanel, SecurityGroupList } from '../components/FirewallObjects'
import { FirewallLog } from '../components/FirewallLog'
import { FirewallOptionsPanel } from '../components/FirewallOptionsPanel'
import { FirewallRuleForm } from '../components/FirewallRuleForm'
import { FirewallRuleTable } from '../components/FirewallRuleTable'
import { Dialog } from '../components/ui/dialog'
import { QueryState } from '../components/QueryState'
// shellRoute comes from ./shell, never ../router: importing router.tsx here
// would force its eager createRouter() to run mid-cycle when this file is the
// import entry point (e.g. a test importing this route file directly), as
// routes/shell.tsx explains.
import { shellRoute } from './shell'
import { tabList, tabTrigger } from '../components/ui/tabs'

const selectClass = 'rounded-ctl border border-line-soft bg-elev px-2 py-1.5 text-[13px]'

// Same order the backend uses (proxploy/api/deps.py: ROLE_ORDER). Kept in
// this exact shape, not derived from it, because the frontend has no way to
// import a Python module -- this is the one place that order is repeated,
// and canEditFirewall's own tests pin it.
const ROLE_RANK: Record<string, number> = { viewer: 0, operator: 1, admin: 2, owner: 3 }

/** Mirrors the backend's firewall authorization matrix
 *  (proxploy/api/firewall.py, apps.py, vms.py): a guest firewall follows
 *  guest networking and opens to operator, everything else (cluster, node,
 *  security group) is an admin action. */
export function canEditFirewall(role: string, kind: Scope['kind']): boolean {
  const need = kind === 'guest' ? 'operator' : 'admin'
  return (ROLE_RANK[role] ?? -1) >= ROLE_RANK[need]
}

/** Permission gate for one tab, following app-gates.ts's rule: only an
 *  answer that has ARRIVED and says no withholds anything. A pending
 *  useMe/useEntitlements reads as permissive so the first fetch does not
 *  grey out every control on every page load; the backend still refuses
 *  a write it should refuse. */
function useFirewallCanEdit(kind: Scope['kind'], flag: string): boolean {
  const me = useMe()
  const ent = useEntitlements()
  const roleOk = me.data == null || canEditFirewall(me.data.role, kind)
  const entOk = ent.data == null || ent.has(flag)
  return roleOk && entOk
}

function useClusterNodes() {
  // Same queryKey routes/hosts.tsx's useNodes uses, so this page shares that
  // cache rather than doubling the poll.
  return useQuery({
    queryKey: ['cluster', 'nodes'],
    queryFn: () => api<NodeRow[]>('/cluster/nodes'),
    refetchInterval: 30_000,
  })
}

type FirewallEntry = { key: string; label: string; hostId: number }

/** One entry per cluster, not one per enrolled host: two NodeRow rows can be
 *  two API endpoints into the SAME physical cluster (see
 *  routes/hosts.tsx's groupByCluster), and one cluster has one firewall
 *  config file. Two editors for it would let an operator overwrite their own
 *  change. A node with no cluster is standalone and gets its own entry,
 *  keyed by its host name. */
function buildFirewallEntries(nodes: NodeRow[]): FirewallEntry[] {
  const clusters = new Map<string, NodeRow[]>()
  const standalone: NodeRow[] = []
  for (const n of nodes) {
    if (!n.cluster) { standalone.push(n); continue }
    const rows = clusters.get(n.cluster)
    if (rows) rows.push(n)
    else clusters.set(n.cluster, [n])
  }
  const entries: FirewallEntry[] = [...clusters.entries()]
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([name, rows]) => ({ key: `cluster:${name}`, label: name, hostId: rows[0].host_id }))
  for (const n of [...standalone].sort((a, b) => a.name.localeCompare(b.name))) {
    entries.push({ key: `host:${n.name}`, label: n.name, hostId: n.host_id })
  }
  return entries
}

/** Rules tab: the table plus the dialog that creates or edits one rule. */
function RulesTab({ scope, hostId, canEdit }: { scope: Scope; hostId: number; canEdit: boolean }) {
  const [editing, setEditing] = useState<Rule | 'new' | null>(null)
  return (
    <>
      <FirewallRuleTable scope={scope} canEdit={canEdit}
        onEdit={(r) => setEditing(r)} onAdd={() => setEditing('new')} />
      {editing != null && (
        <Dialog title={editing === 'new' ? 'Add rule' : `Edit rule ${editing.pos}`}
          width={520} onClose={() => setEditing(null)}>
          <FirewallRuleForm scope={scope} hostId={hostId}
            rule={editing === 'new' ? null : editing} onClose={() => setEditing(null)} />
        </Dialog>
      )}
    </>
  )
}

/** The cluster (or standalone host) firewall: /firewall. */
export function FirewallClusterPage() {
  const nodesQuery = useClusterNodes()
  const switcherId = useId()
  const [selectedKey, setSelectedKey] = useState<string | null>(null)

  return (
    <div>
      <h1 className="font-display text-[18px] font-semibold">Firewall</h1>
      <QueryState query={nodesQuery}
        emptyTitle="No nodes yet"
        emptyNote="A firewall needs a node to belong to. Add a host first.">
        {(nodes) => {
          const entries = buildFirewallEntries(nodes)
          const selected = entries.find((e) => e.key === selectedKey) ?? entries[0]
          return (
            <FirewallClusterEntry entries={entries} selected={selected}
              switcherId={switcherId} onSelect={setSelectedKey} />
          )
        }}
      </QueryState>
    </div>
  )
}

function FirewallClusterEntry({ entries, selected, switcherId, onSelect }: {
  entries: FirewallEntry[]
  selected: FirewallEntry
  switcherId: string
  onSelect: (key: string) => void
}) {
  const hostId = selected.hostId
  const clusterScope: Scope = { kind: 'cluster', hostId }
  const [tab, setTab] = useState('rules')
  const [group, setGroup] = useState<string | null>(null)
  const canEditRules = useFirewallCanEdit('cluster', 'firewall.rules')
  const canEditGroups = useFirewallCanEdit('cluster', 'firewall.objects')
  const canEditObjects = useFirewallCanEdit('cluster', 'firewall.objects')
  const canEditOptions = useFirewallCanEdit('cluster', 'firewall.options')

  return (
    <div>
      <div className="mb-4 flex items-center gap-2">
        <label className="text-[11px] uppercase tracking-wide text-text-3" htmlFor={switcherId}>
          Firewall for
        </label>
        <select id={switcherId} className={selectClass} value={selected.key}
          onChange={(e) => onSelect(e.target.value)}>
          {entries.map((e) => <option key={e.key} value={e.key}>{e.label}</option>)}
        </select>
      </div>

      <Tabs.Root value={tab} onValueChange={setTab}>
        <Tabs.List className={tabList}>
          <Tabs.Trigger value="rules" className={tabTrigger}>Rules</Tabs.Trigger>
          <Tabs.Trigger value="groups" className={tabTrigger}>Security groups</Tabs.Trigger>
          <Tabs.Trigger value="aliases" className={tabTrigger}>Aliases</Tabs.Trigger>
          <Tabs.Trigger value="ipsets" className={tabTrigger}>IP sets</Tabs.Trigger>
          <Tabs.Trigger value="options" className={tabTrigger}>Options</Tabs.Trigger>
        </Tabs.List>

        <Tabs.Content value="rules">
          <RulesTab scope={clusterScope} hostId={hostId} canEdit={canEditRules} />
        </Tabs.Content>

        <Tabs.Content value="groups">
          <SecurityGroupList hostId={hostId} canEdit={canEditGroups}
            selected={group} onSelect={setGroup} />
          {group != null && (
            <div className="mt-4 border-t border-line-soft pt-4">
              <RulesTab scope={{ kind: 'group', hostId, group }} hostId={hostId}
                canEdit={canEditRules} />
            </div>
          )}
        </Tabs.Content>

        <Tabs.Content value="aliases">
          <AliasTable scope={clusterScope} canEdit={canEditObjects} />
        </Tabs.Content>

        <Tabs.Content value="ipsets">
          <IpSetPanel scope={clusterScope} canEdit={canEditObjects} />
        </Tabs.Content>

        <Tabs.Content value="options">
          <FirewallOptionsPanel scope={clusterScope} canEdit={canEditOptions} />
        </Tabs.Content>
      </Tabs.Root>
    </div>
  )
}

/** A single node's firewall: /firewall/node/$hostId/$node. A node has no
 *  aliases or IP sets of its own (PVE keeps those at cluster scope only). */
export function FirewallNodePage() {
  const { hostId: hostIdParam, node } = useParams({ strict: false }) as
    { hostId: string; node: string }
  const hostId = Number(hostIdParam)
  const scope: Scope = { kind: 'node', hostId, node }
  const canEditRules = useFirewallCanEdit('node', 'firewall.rules')
  const canEditOptions = useFirewallCanEdit('node', 'firewall.options')

  return (
    <div>
      <h1 className="font-display text-[18px] font-semibold">
        Firewall <span className="text-text-3">· {node}</span>
      </h1>
      <Tabs.Root defaultValue="rules">
        <Tabs.List className={tabList}>
          <Tabs.Trigger value="rules" className={tabTrigger}>Rules</Tabs.Trigger>
          <Tabs.Trigger value="options" className={tabTrigger}>Options</Tabs.Trigger>
          <Tabs.Trigger value="log" className={tabTrigger}>Log</Tabs.Trigger>
        </Tabs.List>

        <Tabs.Content value="rules">
          <RulesTab scope={scope} hostId={hostId} canEdit={canEditRules} />
        </Tabs.Content>
        <Tabs.Content value="options">
          <FirewallOptionsPanel scope={scope} canEdit={canEditOptions} />
        </Tabs.Content>
        <Tabs.Content value="log">
          <FirewallLog scope={scope} />
        </Tabs.Content>
      </Tabs.Root>
    </div>
  )
}

/** Looks up a guest's name and host, from whichever list (apps or VMs) is
 *  already the app-wide query cache under the same key AppsPage/VmsPage use,
 *  so a link from those pages costs no extra fetch and a direct deep link
 *  still resolves on its own. */
function useGuestIdentity(guestType: 'app' | 'vm', guestId: number) {
  const appsQuery = useQuery({
    queryKey: ['apps', {}],
    queryFn: () => api<AppRow[]>('/apps'),
    enabled: guestType === 'app',
    refetchInterval: 30_000,
  })
  const vmsQuery = useQuery({
    queryKey: ['vms', {}],
    queryFn: () => api<VmRow[]>('/vms'),
    enabled: guestType === 'vm',
    refetchInterval: 30_000,
  })
  if (guestType === 'app') {
    const app = appsQuery.data?.find((a) => a.id === guestId)
    return { name: app?.name ?? null, hostId: app?.host_id ?? null }
  }
  const vm = vmsQuery.data?.find((v) => v.id === guestId)
  return { name: vm?.name ?? null, hostId: vm?.host_id ?? null }
}

/** A guest's firewall: /firewall/guest/$guestType/$guestId. */
export function FirewallGuestPage() {
  const { guestType, guestId: guestIdParam } = useParams({ strict: false }) as
    { guestType: 'app' | 'vm'; guestId: string }
  const guestId = Number(guestIdParam)
  const { name, hostId } = useGuestIdentity(guestType, guestId)
  const scope: Scope = { kind: 'guest', guestType, guestId }
  const canEditRules = useFirewallCanEdit('guest', 'firewall.rules')
  const canEditObjects = useFirewallCanEdit('guest', 'firewall.objects')
  const canEditOptions = useFirewallCanEdit('guest', 'firewall.options')

  return (
    <div>
      <h1 className="font-display text-[18px] font-semibold">
        Firewall <span className="text-text-3">· {name ?? `guest ${guestId}`}</span>
      </h1>
      <Tabs.Root defaultValue="rules">
        <Tabs.List className={tabList}>
          <Tabs.Trigger value="rules" className={tabTrigger}>Rules</Tabs.Trigger>
          <Tabs.Trigger value="aliases" className={tabTrigger}>Aliases</Tabs.Trigger>
          <Tabs.Trigger value="ipsets" className={tabTrigger}>IP sets</Tabs.Trigger>
          <Tabs.Trigger value="options" className={tabTrigger}>Options</Tabs.Trigger>
          <Tabs.Trigger value="log" className={tabTrigger}>Log</Tabs.Trigger>
        </Tabs.List>

        <Tabs.Content value="rules">
          {/* The rule table needs no hostId (a guest's rules live at
              /apps|vms/{id}/firewall, no host in the path); only the form's
              macro and security-group pickers need to know which cluster to
              ask, so editing waits for the guest's host to resolve rather
              than opening a dialog that cannot fetch either. */}
          <RulesTab scope={scope} hostId={hostId ?? 0} canEdit={canEditRules && hostId != null} />
        </Tabs.Content>
        <Tabs.Content value="aliases">
          <AliasTable scope={scope} canEdit={canEditObjects} />
        </Tabs.Content>
        <Tabs.Content value="ipsets">
          <IpSetPanel scope={scope} canEdit={canEditObjects} />
        </Tabs.Content>
        <Tabs.Content value="options">
          <FirewallOptionsPanel scope={scope} canEdit={canEditOptions} />
        </Tabs.Content>
        <Tabs.Content value="log">
          <FirewallLog scope={scope} />
        </Tabs.Content>
      </Tabs.Root>
    </div>
  )
}

export const firewallRoute = createRoute({
  getParentRoute: () => shellRoute,
  path: '/firewall',
  component: FirewallClusterPage,
})

export const firewallNodeRoute = createRoute({
  getParentRoute: () => shellRoute,
  path: '/firewall/node/$hostId/$node',
  component: FirewallNodePage,
})

export const firewallGuestRoute = createRoute({
  getParentRoute: () => shellRoute,
  path: '/firewall/guest/$guestType/$guestId',
  component: FirewallGuestPage,
})
