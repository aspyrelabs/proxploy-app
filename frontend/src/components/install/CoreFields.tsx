const lbl = 'mb-1 block text-[11px] uppercase tracking-wide text-text-3'
const inputCls = 'w-full rounded-ctl border border-line bg-panel px-3 py-1.5 text-[13px]'

export type CoreFieldsValue = {
  cpu: string; ram: string; disk: string; os: string; version: string; hostname: string
  // null = untouched, so nothing is sent and the app script's own
  // var_unprivileged stands. Rendered indeterminate rather than unchecked,
  // because an unchecked box would read as a deliberate "privileged".
  unprivileged: boolean | null
}

/**
 * Field names are the whole risk: InstallDialog keys `overrides` off them,
 * install.test.tsx's `KNOWN` set pins them, and the backend prefixes them
 * with `var_`. Renaming one silently stops reaching build.func — no error,
 * just ignored, and the script falls back to its own default while the
 * operator believes they chose otherwise. Don't rename without updating
 * that pinned set.
 */
export function CoreFields({ value, onChange }: {
  value: CoreFieldsValue
  onChange: (patch: Partial<CoreFieldsValue>) => void
}) {
  return (
    <div className="mt-2 grid grid-cols-2 gap-2">
      <div>
        <label htmlFor="ct-cpu" className={lbl}>vCPU</label>
        <input id="ct-cpu" type="number" min={1} className={inputCls} value={value.cpu}
          onChange={(e) => onChange({ cpu: e.target.value })} />
      </div>
      <div>
        <label htmlFor="ct-ram" className={lbl}>RAM (MB)</label>
        <input id="ct-ram" type="number" min={1} className={inputCls} value={value.ram}
          onChange={(e) => onChange({ ram: e.target.value })} />
      </div>
      <div>
        <label htmlFor="ct-disk" className={lbl}>Disk (GB)</label>
        <input id="ct-disk" type="number" min={1} className={inputCls} value={value.disk}
          onChange={(e) => onChange({ disk: e.target.value })} />
      </div>
      <div>
        <label htmlFor="ct-os" className={lbl}>OS</label>
        <input id="ct-os" type="text" className={inputCls} value={value.os}
          onChange={(e) => onChange({ os: e.target.value })} />
      </div>
      <div>
        <label htmlFor="ct-version" className={lbl}>OS version</label>
        <input id="ct-version" type="text" className={inputCls} value={value.version}
          onChange={(e) => onChange({ version: e.target.value })} />
      </div>
      <div>
        <label htmlFor="ct-hostname" className={lbl}>Hostname</label>
        <input id="ct-hostname" type="text" className={inputCls} value={value.hostname}
          onChange={(e) => onChange({ hostname: e.target.value })} />
      </div>
      <label className="col-span-2 flex items-center gap-2 text-[12.5px] text-text-2">
        <input type="checkbox" checked={value.unprivileged ?? false}
          ref={(el) => { if (el) el.indeterminate = value.unprivileged == null }}
          onChange={(e) => onChange({ unprivileged: e.target.checked })} />
        Unprivileged container
        {value.unprivileged == null && (
          <span className="text-text-3">(uses the app script&rsquo;s own setting)</span>
        )}
      </label>
    </div>
  )
}
