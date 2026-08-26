import { useState } from 'react'
import { api } from '../api/client'
import { Button } from './ui/button'

/** Capabilities and the two extra roles are read from the caller on every
 *  click, not copied in once: HostForm's own checkboxes decide them live, so
 *  the script reflects whatever is ticked when Generate is pressed, not what
 *  was ticked when this panel first appeared. */
export function HostScriptPanel({ capabilities, nodeShell, nodePower }: {
  capabilities: string[]; nodeShell: boolean; nodePower: boolean
}) {
  const [script, setScript] = useState<string | null>(null)
  const [error, setError] = useState('')

  async function generate() {
    setError('')
    try {
      const r = await api<{ script: string }>('/hosts/token-script', {
        method: 'POST',
        body: JSON.stringify({ capabilities, node_shell: nodeShell, node_power: nodePower }) })
      setScript(r.script)
    } catch {
      setError('Could not generate the script. Try again.')
    }
  }

  return (
    <>
      <div className="flex items-center justify-between gap-3">
        <p className="text-[12.5px] text-text-2">Don't have a token yet?</p>
        <Button type="button" variant="ghost" onClick={generate}>
          Generate setup script
        </Button>
      </div>
      {error && <p className="mt-2 text-[12.5px] text-red">{error}</p>}
      {script && (
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
          <Button type="button" variant="ghost" className="mt-2"
            onClick={() => navigator.clipboard.writeText(script)}>Copy script</Button>
        </>
      )}
    </>
  )
}
