import { useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { api, ApiError } from '../api/client'
import { inputCls } from './LoginForm'
import { Button } from './ui/button'

type RotateResult = { id: number; rotated: string[]; public_key?: string; consent_note?: string }

const detailOf = (e: unknown) =>
  e instanceof ApiError && typeof (e.body as any)?.detail === 'string'
    ? (e.body as any).detail : 'Request failed, try again.'

export function HostRotateDialog({ hostId, hostName, onClose }: {
  hostId: number; hostName: string; onClose: () => void
}) {
  const qc = useQueryClient()
  const [tokenId, setTokenId] = useState('')
  const [tokenSecret, setTokenSecret] = useState('')
  const [rotateSsh, setRotateSsh] = useState(false)
  const [result, setResult] = useState<RotateResult | null>(null)

  // A half-filled token pair is meaningless (POST /hosts/{id}/credentials
  // 422s on it), refuse it here instead of proving the same thing over the
  // network.
  const halfFilled = Boolean(tokenId) !== Boolean(tokenSecret)
  const nothingToRotate = !tokenId && !tokenSecret && !rotateSsh

  const rotate = useMutation({
    mutationFn: () => api<RotateResult>(`/hosts/${hostId}/credentials`, {
      method: 'POST',
      body: JSON.stringify({
        ...(tokenId ? { token_id: tokenId } : {}),
        ...(tokenSecret ? { token_secret: tokenSecret } : {}),
        rotate_ssh: rotateSsh,
      }),
    }),
    onSuccess: (r) => { setResult(r); qc.invalidateQueries({ queryKey: ['hosts'] }) },
    onError: (e) => toast.error(detailOf(e)),
  })

  return (
    <div role="dialog" aria-label={`Rotate credentials for ${hostName}`}
         className="fixed inset-0 z-30 grid place-items-center bg-scrim backdrop-blur-[3px]">
      <div className="w-[440px] max-w-[92vw] rounded-card border border-line bg-panel p-5">
        <h2 className="font-display text-[16px] font-semibold">Rotate credentials, {hostName}</h2>
        {result ? (
          <div className="mt-4 space-y-3">
            <p className="text-[13px] text-green">Rotated: {result.rotated.join(', ')}</p>
            {result.public_key && (
              <>
                <p className="text-[12.5px] text-text-2">{result.consent_note}</p>
                <code className="block max-h-24 overflow-auto rounded-ctl border border-line
                                 bg-panel-2 p-2 font-mono text-[11px] text-text">
                  {result.public_key}
                </code>
              </>
            )}
            <div className="flex justify-end">
              <Button onClick={onClose}>Done</Button>
            </div>
          </div>
        ) : (
          <div className="mt-4 space-y-3">
            <div>
              <label htmlFor="rotate-token-id"
                className="mb-1 block text-[11px] uppercase tracking-wide text-text-3">
                New API token id
              </label>
              <input id="rotate-token-id" className={inputCls} value={tokenId}
                onChange={(e) => setTokenId(e.target.value)} placeholder="leave blank to keep the current one" />
            </div>
            <div>
              <label htmlFor="rotate-token-secret"
                className="mb-1 block text-[11px] uppercase tracking-wide text-text-3">
                New API token secret
              </label>
              <input id="rotate-token-secret" type="password" className={inputCls} value={tokenSecret}
                onChange={(e) => setTokenSecret(e.target.value)} />
            </div>
            <label className="flex items-center gap-2 text-[13px] text-text-2">
              <input type="checkbox" checked={rotateSsh}
                onChange={(e) => setRotateSsh(e.target.checked)} />
              Regenerate SSH key (the new key still needs installing on the node)
            </label>
            {halfFilled && (
              <p className="text-[12px] text-red">
                Token id and secret must both be filled in, or both left blank.
              </p>
            )}
            <div className="flex justify-end gap-2">
              <Button variant="ghost" onClick={onClose}>Cancel</Button>
              <Button disabled={halfFilled || nothingToRotate || rotate.isPending}
                onClick={() => rotate.mutate()}>
                {rotate.isPending ? 'Rotating…' : 'Rotate'}
              </Button>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
