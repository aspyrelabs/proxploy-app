import { useState } from 'react'
import { api } from '../api/client'
import { Button } from './ui/button'
import { ButtonGroup, ButtonGroupSeparator } from './ui/button-group'
import { Icon } from './ui/icon'

/** Capabilities and the two extra roles are read from the caller on every
 *  click, not copied in once: HostForm's own checkboxes decide them live, so
 *  the script reflects whatever is ticked when Generate is pressed, not what
 *  was ticked when this panel first appeared. */
export function HostScriptPanel({ capabilities }: { capabilities: string[] }) {
  const [script, setScript] = useState<string | null>(null)
  const [error, setError] = useState('')
  // Shut until asked. Most operators arrive with a token already made, and an
  // always-open generator put a script block between them and the fields they
  // came to fill in.
  const [open, setOpen] = useState(false)

  async function generate() {
    setError('')
    try {
      const r = await api<{ script: string }>('/hosts/token-script', {
        method: 'POST',
        body: JSON.stringify({ capabilities }) })
      setScript(r.script)
    } catch {
      setError('Could not generate the script. Try again.')
    }
  }

  return (
    <>
      <button type="button" aria-expanded={open} onClick={() => setOpen(o => !o)}
        className="flex w-full items-center gap-1.5 text-left text-[12.5px] text-text-2
                   transition hover:text-text">
        <Icon name="expand_more" size={16}
          className={`shrink-0 text-text-3 transition-transform motion-reduce:transition-none
                      ${open ? 'rotate-180 text-amber' : ''}`} />
        Don&rsquo;t have a token yet?
      </button>
      {open && (
        <p className="mt-1.5 text-[11.5px] text-text-3">
          Proxploy can write the commands that create one. Tick the capabilities
          you want first: the script only creates roles for those.
        </p>
      )}
      {open && (
        <ButtonGroup className="mt-2">
          <Button type="button" size="sm" variant="ghost" onClick={generate}>
            Generate script
          </Button>
          {script && (
            <>
              <ButtonGroupSeparator />
              <Button type="button" size="sm" variant="ghost"
                onClick={() => navigator.clipboard.writeText(script)}>
                Copy script
              </Button>
            </>
          )}
        </ButtonGroup>
      )}
      {open && error && <p className="mt-2 text-[12.5px] text-red">{error}</p>}
      {open && script && (
        <>
          <p className="mt-2 text-[11.5px] text-text-3">
            Run this in a shell on the node. It creates a dedicated user with
            only the privileges Proxploy needs, and prints one token secret per
            capability. Proxploy never sees your root credentials.
          </p>
          <p className="mt-1 text-[11.5px] text-text-3">
            If that user already exists on the node, the first line fails and
            everything after it still runs, so keep going instead of stopping there.
          </p>
          {/* Dark in both themes on purpose, like ScriptPanel and the
              authorized_keys block in onboarding: this is shell text, and
              shell text that follows a light theme stops reading as shell. */}
          <pre className="mt-2 max-h-64 overflow-auto rounded-ctl bg-[#0a0e14] p-3 font-mono text-[11px] leading-[1.6] text-text-2">{script}</pre>
        </>
      )}
    </>
  )
}
