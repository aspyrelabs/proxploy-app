import { useQuery } from '@tanstack/react-query'
import { api } from '../api/client'

type ScriptOut = { version: number; content: string; source: string; diff_vs_upstream: string | null }

function DiffLine({ line }: { line: string }) {
  const cls = line.startsWith('+') ? 'text-green-400' : line.startsWith('-') ? 'text-red-400' : 'text-text-3'
  return <div className={cls}>{line}</div>
}

export function ScriptPanel({ appId }: { appId: number }) {
  const { data } = useQuery({
    queryKey: ['apps', appId, 'script'],
    queryFn: () => api<ScriptOut>(`/apps/${appId}/script`),
  })
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
        <div className="mb-3 text-[12px] text-text-3">Matches upstream — no local edits.</div>
      )}
      <pre className="overflow-x-auto rounded-card bg-[#0a0e14] p-4 font-mono text-[12px] text-text-2">
        {data.content}
      </pre>
    </div>
  )
}
