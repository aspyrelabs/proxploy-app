import { useQuery } from '@tanstack/react-query'
import { api } from '../api/client'
import { SkeletonGroup, SkeletonLine } from './ui/skeleton'

type ScriptOut = { version: number; content: string; source: string; diff_vs_upstream: string | null }

function DiffLine({ line }: { line: string }) {
  const cls = line.startsWith('+') ? 'text-green' : line.startsWith('-') ? 'text-red' : 'text-text-3'
  return <div className={cls}>{line}</div>
}

export function ScriptPanel({ appId }: { appId: number }) {
  const { data, isPending } = useQuery({
    queryKey: ['apps', appId, 'script'],
    queryFn: () => api<ScriptOut>(`/apps/${appId}/script`),
  })
  // `if (!data) return null` covered the fetch and the failure with the same
  // blank tab, which is the wrong answer to one of them and no answer to the
  // other. The failure still renders nothing (unchanged, and out of scope
  // here), but a script on its way now looks like a script on its way: a
  // version line and the dark slab the source lands in.
  if (isPending) {
    return (
      <SkeletonGroup label="Loading the install script">
        <SkeletonLine className="mb-2 w-40 text-[12px]" />
        <SkeletonLine className="mb-3 w-56 text-[12px]" />
        <div className="rounded-card bg-[#0a0e14] p-4">
          {['w-3/4', 'w-1/2', 'w-5/6', 'w-2/3', 'w-11/12', 'w-1/3', 'w-4/5', 'w-3/5']
            .map((w) => <SkeletonLine key={w} className={`${w} text-[12px]`} />)}
        </div>
      </SkeletonGroup>
    )
  }
  if (!data) return null
  return (
    <div>
      <div className="mb-2 text-[12px] text-text-3">version {data.version} · {data.source}</div>
      {data.diff_vs_upstream ? (
        <div className="mb-3">
          <div className="mb-1 text-[12px] font-semibold text-amber">Differs from upstream</div>
          <pre className="overflow-x-auto rounded-card bg-[#0a0e14] p-4 font-mono text-[12px]">
            {data.diff_vs_upstream.split('\n').map((l, i) => <DiffLine key={i} line={l} />)}
          </pre>
        </div>
      ) : (
        <div className="mb-3 text-[12px] text-text-3">Matches upstream, no local edits.</div>
      )}
      <pre className="overflow-x-auto rounded-card bg-[#0a0e14] p-4 font-mono text-[12px] text-text-2">
        {data.content}
      </pre>
    </div>
  )
}
