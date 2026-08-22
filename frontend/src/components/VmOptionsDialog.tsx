import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { api } from '../api/client'
import type { VmRow } from '../api/hooks'
import { errBody } from '../api/network'
import { notify } from '../lib/notify'
import { inputCls } from './LoginForm'
import { Button } from './ui/button'
import { Dialog } from './ui/dialog'
import { Icon } from './ui/icon'
import { InfoHint } from './ui/info-hint'
import { Loading } from './ui/loading'
import { Switch } from './ui/switch'

export type VmOptions = {
  /** ONLY the keys Proxmox actually has a line for. A key missing from here
   *  is at its Proxmox default, which is not the same thing as off. */
  values: Record<string, unknown>
  /** Keys Proxmox is holding until the next boot. A null value is a pending
   *  delete, meaning the setting is on its way back to the default. */
  pending: Record<string, unknown>
  restricted: string[]
  running: boolean
  storages: string[]
}

type SaveResult = {
  changed: string[]
  pending_reboot: boolean
  pending: Record<string, unknown>
  detail: string | null
}

/**
 * The settings that only take hold once the VM has been shut down and
 * started again. `agent`, `hotplug` and `tablet` are deliberately NOT here:
 * each of those is conditional (the agent's fstrim on clone applies at once,
 * hotplug applies at once unless CPU or memory is involved, and the tablet
 * applies at once when USB hotplug is on), so each carries its own sentence
 * instead of this blanket one.
 */
const NEXT_BOOT = new Set([
  'ostype', 'localtime', 'boot', 'acpi', 'kvm', 'freeze', 'startdate', 'smbios1',
])

/**
 * What Proxmox does when the key is absent from the config file entirely.
 *
 * This is the whole reason the form below tracks "unset" as its own state
 * rather than folding it into false. `acpi`, `kvm` and `tablet` are ON when
 * absent, so reading a missing key as false would show three switches off
 * that are really on, and saving would then write those wrong values into
 * the guest's config for good.
 *
 * `localtime` is not in this table on purpose: it has no fixed default,
 * Proxmox derives it from the OS type (on for Windows, off otherwise), so it
 * gets a three-way control of its own rather than a switch.
 */
const BOOL_DEFAULT: Record<string, boolean> = {
  onboot: false, protection: false, acpi: true, kvm: true, tablet: true, freeze: false,
}

const OS_TYPES: [string, string][] = [
  ['other', 'Other'],
  ['wxp', 'Windows XP'],
  ['w2k', 'Windows 2000'],
  ['w2k3', 'Windows Server 2003'],
  ['w2k8', 'Windows Server 2008'],
  ['wvista', 'Windows Vista'],
  ['win7', 'Windows 7'],
  ['win8', 'Windows 8 or Server 2012'],
  ['win10', 'Windows 10 or Server 2016'],
  ['win11', 'Windows 11 or Server 2022'],
  ['l24', 'Linux, 2.4 kernel'],
  ['l26', 'Linux, 2.6 kernel or newer'],
  ['solaris', 'Solaris'],
]

const HOTPLUG_FLAGS: [string, string][] = [
  ['network', 'Network cards'],
  ['disk', 'Disks'],
  ['cpu', 'CPU cores'],
  ['memory', 'Memory'],
  ['usb', 'USB devices'],
  ['cloudinit', 'Cloud-init drive'],
]
// Proxmox's own default for a config with no hotplug line at all. Another
// case where absent is not off: three of the six are already on.
const HOTPLUG_DEFAULT = 'network,disk,usb'

const SMBIOS_FIELDS: [string, string][] = [
  ['family', 'Family'],
  ['manufacturer', 'Manufacturer'],
  ['product', 'Product'],
  ['serial', 'Serial number'],
  ['sku', 'SKU'],
  ['uuid', 'UUID'],
  ['version', 'Version'],
]

const ROOT_ONLY = 'Proxmox only lets the root user change this, so Proxploy cannot.'

const RESTRICTED_COPY: Record<string, { label: string; why: string }> = {
  spice_enhancements: {
    label: 'SPICE enhancements',
    why: `Folder sharing and video streaming for SPICE consoles. ${ROOT_ONLY}`,
  },
  'amd-sev': {
    label: 'AMD SEV memory encryption',
    why: `${ROOT_ONLY} It also needs an AMD EPYC host CPU, which this host may not be.`,
  },
  'intel-tdx': {
    label: 'Intel TDX trusted domains',
    why: `${ROOT_ONLY} It also needs a 4th generation Intel Xeon host CPU, which this host may not be.`,
  },
}

type Props = Record<string, string>
type BootDev = { dev: string; on: boolean }

type Form = {
  name: string
  onboot: boolean | undefined
  protection: boolean | undefined
  acpi: boolean | undefined
  kvm: boolean | undefined
  tablet: boolean | undefined
  freeze: boolean | undefined
  /** '' means unset, and unset really means "whatever the OS type implies". */
  localtime: string
  ostype: string
  vmstatestorage: string
  startdate: string
  /** The canonical comma list, or undefined for unset. */
  hotplug: string | undefined
  boot: BootDev[]
  startup: Props
  agent: Props
  smbios1: Props
}

/** A Proxmox property string, `a=1,b=2`, as an object. Bare tokens with no
 *  `=` are dropped: the one shape that uses them here is `agent: 1`, which
 *  parseAgent handles before this is reached. */
function parseProps(raw: unknown): Props {
  const out: Props = {}
  if (raw == null) return out
  for (const part of String(raw).split(',')) {
    const eq = part.indexOf('=')
    if (eq > 0) out[part.slice(0, eq)] = part.slice(eq + 1)
  }
  return out
}

function parseAgent(raw: unknown): Props {
  if (raw == null) return {}
  const s = String(raw)
  // Proxmox writes the short form `agent: 1` when only the on/off part was
  // ever set, and the full property string once any sub-setting is added.
  if (s === '0' || s === '1') return { enabled: s }
  return parseProps(s)
}

function parseBool(raw: unknown): boolean | undefined {
  return raw === undefined || raw === null ? undefined : String(raw) === '1'
}

function hotplugOn(raw: string): Set<string> {
  if (raw === '0' || raw === '') return new Set()
  return new Set(raw.split(','))
}

function hotplugString(on: Set<string>): string {
  const list = HOTPLUG_FLAGS.map(([f]) => f).filter((f) => on.has(f))
  // Proxmox spells "nothing is hot-pluggable" as the single character 0, not
  // as an empty value.
  return list.length ? list.join(',') : '0'
}

function bootOrder(devs: BootDev[]): string {
  return devs.filter((d) => d.on).map((d) => d.dev).join(';')
}

/** The sub-keys worth sending for `agent`. Applied to BOTH the loaded config
 *  and the edited one, so a VM that already reads `agent: 0` does not open
 *  looking as if something had been changed. */
function agentBody(a: Props): Props {
  const out: Props = {}
  if (a.enabled !== '1') return out
  out.enabled = '1'
  for (const k of ['type', 'freeze-fs', 'fstrim_cloned_disks']) {
    if (a[k] && a[k] !== '0') out[k] = a[k]
  }
  return out
}

function pick(p: Props, keys: string[]): Props {
  const out: Props = {}
  for (const k of keys) if (p[k] && p[k].trim() !== '') out[k] = p[k].trim()
  return out
}

const startupBody = (p: Props) => pick(p, ['order', 'up', 'down'])
const smbiosBody = (p: Props) => pick(p, SMBIOS_FIELDS.map(([f]) => f))

function toForm(values: Record<string, unknown>): Form {
  const str = (k: string) => (values[k] == null ? '' : String(values[k]))
  const rawHotplug = values.hotplug == null ? undefined : String(values.hotplug)
  const startdate = str('startdate')
  return {
    name: str('name'),
    onboot: parseBool(values.onboot),
    protection: parseBool(values.protection),
    acpi: parseBool(values.acpi),
    kvm: parseBool(values.kvm),
    tablet: parseBool(values.tablet),
    freeze: parseBool(values.freeze),
    localtime: values.localtime == null ? '' : String(values.localtime) === '1' ? '1' : '0',
    ostype: str('ostype'),
    vmstatestorage: str('vmstatestorage'),
    // Proxmox spells "start the clock at the real current time" as the word
    // now, which is also what an empty box means here.
    startdate: startdate === 'now' ? '' : startdate,
    hotplug: rawHotplug === undefined ? undefined : hotplugString(hotplugOn(rawHotplug)),
    boot: (parseProps(values.boot).order ?? '').split(';').filter(Boolean)
      .map((dev) => ({ dev, on: true })),
    startup: parseProps(values.startup),
    agent: parseAgent(values.agent),
    smbios1: parseProps(values.smbios1),
  }
}

/**
 * The sparse body for PUT /vms/{id}/options: a key absent means leave it
 * alone, a key with a value sets it, and a key set to null DELETES it so the
 * setting goes back to whatever Proxmox does by default.
 *
 * Everything is diffed against the config as it was loaded, so a control
 * nobody touched contributes nothing, and a control put back to its Proxmox
 * default sends null rather than the default value. Writing a default back
 * would bake it into the guest's config file for good, which is a real
 * change dressed up as a no-op.
 */
function buildBody(base: Form, form: Form): Record<string, unknown> {
  const body: Record<string, unknown> = {}

  for (const k of Object.keys(BOOL_DEFAULT)) {
    const b = base[k as keyof Form] as boolean | undefined
    const c = form[k as keyof Form] as boolean | undefined
    if (b === c) continue
    body[k] = c === undefined ? null : c ? 1 : 0
  }

  for (const k of ['name', 'ostype', 'vmstatestorage', 'startdate'] as const) {
    if (base[k] === form[k]) continue
    body[k] = form[k] === '' ? null : form[k]
  }

  if (base.localtime !== form.localtime) {
    body.localtime = form.localtime === '' ? null : Number(form.localtime)
  }

  if (base.hotplug !== form.hotplug) {
    body.hotplug = form.hotplug === undefined ? null : form.hotplug
  }

  // Never null: deleting `boot` restores Proxmox's "try anything" order,
  // which is a different intention from an operator who switched every
  // device off on purpose.
  if (bootOrder(base.boot) !== bootOrder(form.boot)) {
    body.boot = { order: bootOrder(form.boot) }
  }

  const props: [keyof Form, (p: Props) => Props][] = [
    ['startup', startupBody], ['agent', agentBody], ['smbios1', smbiosBody],
  ]
  for (const [k, build] of props) {
    const b = build(base[k] as Props)
    const c = build(form[k] as Props)
    if (JSON.stringify(b) === JSON.stringify(c)) continue
    body[k as string] = Object.keys(c).length ? c : null
  }

  return body
}

function pendingText(v: unknown): string {
  if (v === null) return 'back to the Proxmox default'
  if (typeof v === 'object') {
    return Object.entries(v as Record<string, unknown>)
      .map(([k, x]) => `${k}=${String(x)}`).join(', ')
  }
  return String(v)
}

/** The change gutter, the one piece of visual language this dialog invents.
 *
 *  A save here is a diff against `/etc/pve/qemu-server/<vmid>.conf`: some lines
 *  get written, one may get removed, the rest of the file is untouched. So a
 *  row you have altered is marked in the gutter and its label goes amber, and
 *  the footer counts them. It encodes exactly what the Save button will do,
 *  which is why it earns the ink; nothing else in the dialog is decorated. */
const ROW = 'group relative grid grid-cols-[minmax(0,1fr)_auto] items-start gap-4 '
          + 'border-l-2 py-3 ps-3 pe-1'

/** "next boot" as nine characters, not a sentence.
 *
 *  Eight of these settings only land on a full shutdown and start, and saying
 *  so under every one of them was most of what made this dialog unreadable.
 *  The chip carries the fact; the tooltip carries the sentence, including the
 *  part people get wrong, which is that a reset or a reboot from inside the
 *  guest does NOT count. */
function Effect({ optionKey, running, pending }: {
  optionKey: string
  running: boolean
  pending: Record<string, unknown>
}) {
  const held = optionKey in pending
  if (!held && (!running || !NEXT_BOOT.has(optionKey))) return null
  // pendingText, not String(): a held value for a property-string setting
  // such as agent or smbios1 is an object, and String() renders it as
  // [object Object] in the one place the operator needs to read it.
  const value = held ? pendingText(pending[optionKey]) : null
  // The data- attributes are the semantic half of this chip: which settings
  // are deferred is a fact about the VM, not a style, and it is what the tests
  // assert on rather than reading colours.
  return (
    <span
      data-next-boot={held ? undefined : optionKey}
      data-pending={held ? optionKey : undefined}
      title={held
        ? `Waiting for the next boot: ${value}`
        : 'Takes effect at the next boot, meaning a full shutdown and start. '
          + 'A reset, or a reboot from inside the guest, will not pick it up.'}
      className={`mt-1 inline-flex w-fit items-center gap-1 rounded-full px-1.5 py-0.5
                  font-mono text-[10px] uppercase tracking-wide
                  ${held ? 'bg-amber-dim text-amber' : 'text-text-3'}`}>
      {held ? `Waiting for the next boot: ${value}` : 'next boot'}
      <span className="sr-only">
        Takes effect at the next boot, meaning a full shutdown and start.
      </span>
    </span>
  )
}

/** One setting: what it is on the left, the control on the right.
 *
 *  Every row in the dialog is this shape, so the controls line up in a single
 *  column an eye can run down. `hint` is the long explanation and lives behind
 *  the (i) rather than on the page; `warn` is for the two settings whose
 *  consequence has to be unmissable, and is the only prose that stays inline. */
/** A heading inside one section's pane. Advanced carries seven unrelated
 *  rows, from hot-plug to SMBIOS identity, and a flat column of them says
 *  nothing about which belong together. The markup is what the "Set by
 *  Proxmox only" group was already using inline; naming it keeps the three
 *  groups identical by construction rather than by copy. */
function SubHeading({ children }: { children: React.ReactNode }) {
  return (
    <p className="mb-1 ps-3 pt-3 text-[11px] uppercase tracking-wide text-text-3">
      {children}
    </p>
  )
}

function OptionRow({ label, htmlFor, hint, warn, changed, effect, control, children }: {
  label: string
  htmlFor?: string
  hint?: string
  warn?: React.ReactNode
  changed?: boolean
  effect?: React.ReactNode
  /** The control itself, when it fits beside the label. */
  control?: React.ReactNode
  /** A control too wide for the right column, laid out under the label. */
  children?: React.ReactNode
}) {
  return (
    <div className={`${ROW} ${changed ? 'border-amber bg-amber-dim/20' : 'border-transparent'}`}>
      <div className="min-w-0">
        <div className="flex items-center gap-1.5">
          <label htmlFor={htmlFor}
            className={`text-[13px] ${changed ? 'text-amber' : 'text-text'}`}>
            {label}
          </label>
          {hint && <InfoHint text={hint} />}
        </div>
        {warn && <p className="mt-1 text-[11.5px] text-text-3">{warn}</p>}
        {effect}
        {children && <div className="mt-2">{children}</div>}
      </div>
      {control && <div className="shrink-0 pt-0.5">{control}</div>}
    </div>
  )
}


/** The rail, and which settings live behind each entry. The map is also what
 *  lets a section show how many unsaved changes it is hiding. */
const SECTIONS: { id: string; label: string }[] = [
  { id: 'general', label: 'General' },
  { id: 'os', label: 'Guest OS' },
  { id: 'boot', label: 'Boot' },
  { id: 'advanced', label: 'Advanced' },
]

const SECTION_KEYS: Record<string, string[]> = {
  general: ['name', 'onboot', 'startup', 'protection'],
  os: ['ostype', 'agent', 'localtime'],
  boot: ['boot', 'vmstatestorage'],
  advanced: ['hotplug', 'tablet', 'acpi', 'kvm', 'freeze', 'startdate', 'smbios1'],
}

const STARTUP_FIELDS: [string, string][] = [
  ['order', 'Order'], ['up', 'Start delay'], ['down', 'Shutdown wait'],
]

const smallLabel = 'mb-1 block text-[11px] uppercase tracking-wide text-text-3'

/**
 * Every setting on a VM's Options page, in one dialog.
 *
 * Loads the config first (GET), because half of what this form has to show
 * is which keys Proxmox actually holds a line for. Nothing is guessed from
 * the VM row.
 */
export function VmOptionsDialog({ vm, onClose }: { vm: VmRow; onClose: () => void }) {
  const q = useQuery({
    queryKey: ['vms', vm.id, 'options'],
    queryFn: () => api<VmOptions>(`/vms/${vm.id}/options`),
  })

  return (
    <Dialog title={<>Options for <span className="font-mono">{vm.name}</span></>}
            width={620} scrollBody onClose={onClose}>
      {q.isLoading && <div className="mt-4"><Loading label="Reading the VM's settings" size={18} /></div>}
      {q.isError && (
        <p className="mt-4 text-[12.5px] text-red">
          Could not read this VM's settings from Proxmox. Close this and try again.
        </p>
      )}
      {q.data && <OptionsForm vm={vm} data={q.data} onClose={onClose} />}
    </Dialog>
  )
}

function OptionsForm({ vm, data, onClose }: {
  vm: VmRow; data: VmOptions; onClose: () => void
}) {
  const qc = useQueryClient()
  // `base` is the config as Proxmox last confirmed it, and the only thing the
  // form is ever diffed against. It moves forward on a successful save so the
  // dialog can stay open showing what is pending without offering to send the
  // same change twice.
  const [base, setBase] = useState<Form>(() => toForm(data.values))
  const [form, setForm] = useState<Form>(() => toForm(data.values))
  const [pending, setPending] = useState<Record<string, unknown>>(data.pending ?? {})
  const [error, setError] = useState('')
  const [section, setSection] = useState('general')

  const set = <K extends keyof Form>(k: K, v: Form[K]) => setForm((f) => ({ ...f, [k]: v }))
  // A switch put back to what Proxmox does anyway becomes unset, which is what
  // makes buildBody send a delete instead of writing the default down.
  const setBool = (k: keyof Form, v: boolean) =>
    set(k, (v === BOOL_DEFAULT[k as string] ? undefined : v) as Form[keyof Form])
  const boolOf = (k: keyof Form) => (form[k] as boolean | undefined) ?? BOOL_DEFAULT[k as string]
  const setProp = (k: 'startup' | 'agent' | 'smbios1', sub: string, v: string) =>
    setForm((f) => ({ ...f, [k]: { ...(f[k] as Props), [sub]: v } }))

  const body = buildBody(base, form)
  const dirty = Object.keys(body).length > 0
  const running = data.running
  const restricted = data.restricted ?? []

  const save = useMutation<SaveResult, unknown, Record<string, unknown>>({
    mutationFn: (b) => api<SaveResult>(`/vms/${vm.id}/options`, {
      method: 'PUT', body: JSON.stringify(b),
    }),
    onSettled: () => {
      qc.invalidateQueries({ queryKey: ['vms'] })
      qc.invalidateQueries({ queryKey: ['vms', vm.id, 'options'] })
    },
  })

  const submit = () => {
    if (!dirty) return
    setError('')
    save.mutate(body, {
      onSuccess: (r) => {
        setBase(form)
        setPending(r.pending ?? {})
        notify.success(r.pending_reboot
          ? 'Saved. Some of it waits for the next boot.'
          : 'Saved.')
      },
      onError: (e) => {
        // Proxmox's own refusal, verbatim: it is the only part of this
        // failure that says what to do about it.
        const b = errBody(e)
        const msg = String(b?.detail ?? 'Could not save these options, try again.')
        setError(msg)
        notify.error(msg)
      },
    })
  }

  const agentOn = form.agent.enabled === '1'
  const hot = hotplugOn(form.hotplug ?? HOTPLUG_DEFAULT)
  const setHot = (flag: string, on: boolean) => {
    const next = new Set(hot)
    if (on) next.add(flag); else next.delete(flag)
    const s = hotplugString(next)
    set('hotplug', s === HOTPLUG_DEFAULT ? undefined : s)
  }
  const moveBoot = (i: number, by: number) => {
    const next = [...form.boot]
    const j = i + by
    if (j < 0 || j >= next.length) return
    ;[next[i], next[j]] = [next[j], next[i]]
    set('boot', next)
  }

  const changed = (k: string) => k in body
  const sectionChanges = (id: string) =>
    SECTION_KEYS[id].filter(changed).length
  const nextBootChanges = Object.keys(body).filter((k) => NEXT_BOOT.has(k)).length
  const total = Object.keys(body).length

  return (
    <div className="mt-3">
      {/* Two panes, not one scroll. Nineteen settings in a single column is
          what made the first version unreadable: there was no way to find one
          without reading all of them. The rail also carries a change count per
          section, so unsaved work cannot hide in a section you are not
          looking at. */}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-[minmax(0,9rem)_minmax(0,1fr)]">
        <nav aria-label="Option sections"
          className="flex gap-1 overflow-x-auto sm:flex-col sm:overflow-visible">
          {SECTIONS.map((s) => {
            const n = sectionChanges(s.id)
            const on = s.id === section
            return (
              <button key={s.id} type="button" onClick={() => setSection(s.id)}
                aria-current={on ? 'true' : undefined}
                className={`flex shrink-0 items-center justify-between gap-2 rounded-ctl
                            px-3 py-1.5 text-left text-[13px] transition
                            ${on ? 'bg-panel-2 text-text' : 'text-text-2 hover:text-text'}`}>
                {s.label}
                {n > 0 && (
                  <span className="rounded-full bg-amber-dim px-1.5 font-mono
                                   text-[10px] text-amber">{n}</span>
                )}
              </button>
            )
          })}
        </nav>

        <div className="min-w-0 divide-y divide-line-soft">
          {section === 'general' && (
            <>
              <OptionRow label="Name" htmlFor="vmopt-name" changed={changed('name')}
                hint="What this VM is called in Proxmox. Clear it to take the name off again."
                effect={<Effect optionKey="name" running={running} pending={pending} />}>
                <input id="vmopt-name" className={inputCls} value={form.name}
                  onChange={(e) => set('name', e.target.value)} />
              </OptionRow>

              <OptionRow label="Start at boot" htmlFor="vmopt-onboot" changed={changed('onboot')}
                hint="Starts this VM automatically whenever the host itself boots."
                effect={<Effect optionKey="onboot" running={running} pending={pending} />}
                control={<Switch id="vmopt-onboot" checked={boolOf('onboot')}
                  onCheckedChange={(v) => setBool('onboot', v)} />} />

              <OptionRow label="Start and shutdown order" changed={changed('startup')}
                hint="Guests start in order, lowest first, and shut down in reverse. The delays are how long the host waits after starting this one, and how long it waits for it to shut down before pulling the plug. Clear all three for no set order."
                effect={<Effect optionKey="startup" running={running} pending={pending} />}>
                <div className="grid grid-cols-3 gap-2">
                  {STARTUP_FIELDS.map(([f, l]) => (
                    <div key={f}>
                      <label htmlFor={`vmopt-startup-${f}`} className={smallLabel}>{l}</label>
                      <input id={`vmopt-startup-${f}`} className={inputCls} type="number" min={0}
                        value={form.startup[f] ?? ''}
                        onChange={(e) => setProp('startup', f, e.target.value)} />
                    </div>
                  ))}
                </div>
              </OptionRow>

              <OptionRow label="Protection" htmlFor="vmopt-protection" changed={changed('protection')}
                warn="Blocks deleting this VM and its disks. Turn it off before you can remove either."
                effect={<Effect optionKey="protection" running={running} pending={pending} />}
                control={<Switch id="vmopt-protection" checked={boolOf('protection')}
                  onCheckedChange={(v) => setBool('protection', v)} />} />
            </>
          )}

          {section === 'os' && (
            <>
              <OptionRow label="OS type" htmlFor="vmopt-ostype" changed={changed('ostype')}
                hint="Tells Proxmox which defaults suit the guest, such as the clock and the virtual hardware it picks."
                effect={<Effect optionKey="ostype" running={running} pending={pending} />}>
                <select id="vmopt-ostype" className={inputCls} value={form.ostype}
                  onChange={(e) => set('ostype', e.target.value)}>
                  <option value="">Not set, Proxmox treats it as Other</option>
                  {OS_TYPES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
                </select>
              </OptionRow>

              <OptionRow label="QEMU guest agent" htmlFor="vmopt-agent" changed={changed('agent')}
                hint="Lets Proxmox talk to the guest for a clean shutdown, real disk usage and its IP addresses. The agent has to be installed inside the guest as well."
                effect={<Effect optionKey="agent" running={running} pending={pending} />}
                control={<Switch id="vmopt-agent" checked={agentOn}
                  onCheckedChange={(v) => set('agent', { ...form.agent, enabled: v ? '1' : '0' })} />}>
                {agentOn && (
                  <div className="grid grid-cols-2 gap-2">
                    <div>
                      <label htmlFor="vmopt-agent-type" className={smallLabel}>Interface</label>
                      <select id="vmopt-agent-type" className={inputCls}
                        value={form.agent.type ?? ''}
                        onChange={(e) => setProp('agent', 'type', e.target.value)}>
                        <option value="">Default (virtio)</option>
                        <option value="virtio">virtio</option>
                        <option value="isa">isa</option>
                      </select>
                    </div>
                    <div className="flex items-end gap-2 pb-1">
                      <Switch id="vmopt-agent-fstrim"
                        checked={form.agent.fstrim_cloned_disks === '1'}
                        onCheckedChange={(v) =>
                          setProp('agent', 'fstrim_cloned_disks', v ? '1' : '')} />
                      <label htmlFor="vmopt-agent-fstrim" className="text-[12.5px] text-text-2">
                        Trim disks after a clone or migration
                      </label>
                    </div>
                  </div>
                )}
              </OptionRow>

              <OptionRow label="Real time clock" htmlFor="vmopt-localtime"
                changed={changed('localtime')}
                hint="What the guest's hardware clock reads. Windows expects local time, most others expect UTC. Left to the OS type, Proxmox picks for you."
                effect={<Effect optionKey="localtime" running={running} pending={pending} />}>
                <select id="vmopt-localtime" className={inputCls} value={form.localtime}
                  onChange={(e) => set('localtime', e.target.value)}>
                  <option value="">Let the OS type decide</option>
                  <option value="1">Local time</option>
                  <option value="0">UTC</option>
                </select>
              </OptionRow>
            </>
          )}

          {section === 'boot' && (
            <>
              <OptionRow label="Boot order" changed={changed('boot')}
                hint="Proxmox tries these in order. Only devices already in the boot order are listed, because Proxmox does not report the rest here."
                // Switching every device off is a VM that will not boot, and
                // Proxmox will accept it without complaint. Say so here rather
                // than let it be discovered at the next start.
                warn={form.boot.length > 0 && form.boot.every((d) => !d.on)
                  ? <span className="text-red">
                      Nothing is left to boot from, so this VM will not boot.
                    </span>
                  : undefined}
                effect={<Effect optionKey="boot" running={running} pending={pending} />}>
                {form.boot.length === 0 ? (
                  <p className="text-[12.5px] text-text-3">
                    Proxmox has no boot order set for this VM, so it tries everything.
                  </p>
                ) : (
                  <ul className="space-y-1">
                    {form.boot.map((d, i) => (
                      <li key={d.dev}
                        className="flex items-center gap-2 rounded-ctl border border-line-soft
                                   bg-panel-2 px-2 py-1">
                        <span className="w-5 text-center font-mono text-[11px] text-text-3">
                          {i + 1}
                        </span>
                        <span className={`flex-1 font-mono text-[12.5px]
                          ${d.on ? 'text-text' : 'text-text-3 line-through'}`}>{d.dev}</span>
                        <Switch aria-label={`Boot from ${d.dev}`} checked={d.on}
                          onCheckedChange={(v) => set('boot',
                            form.boot.map((b, j) => (j === i ? { ...b, on: v } : b)))} />
                        <Button variant="ghost" size="sm" aria-label={`Move ${d.dev} up`}
                          disabled={i === 0} onClick={() => moveBoot(i, -1)}>
                          <Icon name="arrow_upward" size={14} />
                        </Button>
                        <Button variant="ghost" size="sm" aria-label={`Move ${d.dev} down`}
                          disabled={i === form.boot.length - 1} onClick={() => moveBoot(i, 1)}>
                          <Icon name="arrow_downward" size={14} />
                        </Button>
                      </li>
                    ))}
                  </ul>
                )}
              </OptionRow>

              <OptionRow label="Saved state storage" htmlFor="vmopt-vmstatestorage"
                changed={changed('vmstatestorage')}
                hint="Where a snapshot puts the VM's memory when you include RAM. Automatic lets Proxmox choose."
                effect={<Effect optionKey="vmstatestorage" running={running} pending={pending} />}>
                <select id="vmopt-vmstatestorage" className={inputCls}
                  value={form.vmstatestorage}
                  onChange={(e) => set('vmstatestorage', e.target.value)}>
                  <option value="">Automatic</option>
                  {(data.storages ?? []).map((s) => <option key={s} value={s}>{s}</option>)}
                </select>
              </OptionRow>
            </>
          )}

          {section === 'advanced' && (
            <>
              <div>
              <SubHeading>Hardware</SubHeading>
              <OptionRow label="Hotplug" changed={changed('hotplug')}
                hint="Which kinds of hardware can be added or removed while the VM is running. Changing CPU or memory hotplug only lands at the next boot."
                effect={<Effect optionKey="hotplug" running={running} pending={pending} />}>
                <div className="flex flex-col gap-2">
                  {HOTPLUG_FLAGS.map(([f, l]) => (
                    <label key={f} htmlFor={`vmopt-hotplug-${f}`}
                      className="flex items-center gap-2 text-[12.5px] text-text-2">
                      <Switch id={`vmopt-hotplug-${f}`} checked={hot.has(f)}
                        onCheckedChange={(v) => setHot(f, v)} />
                      {l}
                    </label>
                  ))}
                </div>
              </OptionRow>

              <OptionRow label="Use a tablet for the pointer" htmlFor="vmopt-tablet"
                changed={changed('tablet')}
                hint="Makes the mouse line up properly in the console. Turning it off can save a little CPU on a VM nobody watches."
                effect={<Effect optionKey="tablet" running={running} pending={pending} />}
                control={<Switch id="vmopt-tablet" checked={boolOf('tablet')}
                  onCheckedChange={(v) => setBool('tablet', v)} />} />

              <OptionRow label="ACPI support" htmlFor="vmopt-acpi" changed={changed('acpi')}
                hint="Lets the host ask the guest to shut down politely. Almost every guest needs this on."
                effect={<Effect optionKey="acpi" running={running} pending={pending} />}
                control={<Switch id="vmopt-acpi" checked={boolOf('acpi')}
                  onCheckedChange={(v) => setBool('acpi', v)} />} />

              <OptionRow label="Hardware virtualisation" htmlFor="vmopt-kvm"
                changed={changed('kvm')}
                warn="Turning this off runs the VM fully emulated in software, which is very slow."
                effect={<Effect optionKey="kvm" running={running} pending={pending} />}
                control={<Switch id="vmopt-kvm" checked={boolOf('kvm')}
                  onCheckedChange={(v) => setBool('kvm', v)} />} />

              </div>

              <div>
              <SubHeading>Startup and identity</SubHeading>
              <OptionRow label="Freeze the CPU at startup" htmlFor="vmopt-freeze"
                changed={changed('freeze')}
                hint="The VM starts paused, waiting for you to resume it from the console. For debugging a boot problem."
                effect={<Effect optionKey="freeze" running={running} pending={pending} />}
                control={<Switch id="vmopt-freeze" checked={boolOf('freeze')}
                  onCheckedChange={(v) => setBool('freeze', v)} />} />

              <OptionRow label="Clock start date" htmlFor="vmopt-startdate"
                changed={changed('startdate')}
                hint="What the VM's clock reads when it starts, for example 2020-01-01. Empty means the real current time."
                effect={<Effect optionKey="startdate" running={running} pending={pending} />}>
                <input id="vmopt-startdate" className={inputCls} value={form.startdate}
                  placeholder="now" onChange={(e) => set('startdate', e.target.value)} />
              </OptionRow>

              <OptionRow label="SMBIOS identity" changed={changed('smbios1')}
                hint="The made-up hardware identity the guest reads. Some licensed software keys off it. Clear every box to go back to the Proxmox default."
                effect={<Effect optionKey="smbios1" running={running} pending={pending} />}>
                <div className="grid grid-cols-2 gap-2">
                  {SMBIOS_FIELDS.map(([f, l]) => (
                    <div key={f}>
                      <label htmlFor={`vmopt-smbios-${f}`} className={smallLabel}>{l}</label>
                      <input id={`vmopt-smbios-${f}`} className={inputCls}
                        value={form.smbios1[f] ?? ''}
                        onChange={(e) => setProp('smbios1', f, e.target.value)} />
                    </div>
                  ))}
                </div>
              </OptionRow>

              </div>

              {/* Locked, not hidden. These three exist in Proxmox and an operator
                  who knows that would otherwise wonder where they went; saying
                  why costs one line and answers the question before it is asked. */}
              {restricted.length > 0 && (
                <div>
                  <SubHeading>Set by Proxmox only</SubHeading>
                  {restricted.map((k) => {
                    const copy = RESTRICTED_COPY[k] ?? { label: k, why: ROOT_ONLY }
                    return (
                      <OptionRow key={k} label={copy.label} warn={copy.why}
                        control={<Switch disabled aria-label={copy.label}
                          checked={data.values[k] != null && String(data.values[k]) !== '0'} />} />
                    )
                  })}
                </div>
              )}
            </>
          )}
        </div>
      </div>

      {error && <p className="mt-3 text-[12.5px] text-red">{error}</p>}

      {/* The footer states the diff. "Save" on its own does not say how much is
          about to change, and with the rows scrolled out of view that is the
          only place left to say it. */}
      <div className="mt-4 flex items-center gap-3 border-t border-line-soft pt-3">
        <p className="me-auto text-[12.5px] text-text-3">
          {total === 0 ? 'No changes yet.' : (
            <>
              <span className="text-amber">{total} {total === 1 ? 'change' : 'changes'}</span>
              {nextBootChanges > 0 && `, ${nextBootChanges} at the next boot`}
            </>
          )}
        </p>
        {save.isPending && <Loading label="Saving" size={18} />}
        <Button variant="ghost" onClick={onClose}>Close</Button>
        <Button disabled={!dirty || save.isPending} onClick={submit}>Save changes</Button>
      </div>
    </div>
  )
}
