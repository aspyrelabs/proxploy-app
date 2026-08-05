// api/migrate.ts — Cross-host app migration: preflight + the migrate.app job
// (doc 05 Tasks 14-16, doc 10 §Phase 8). Mirrors backend/proxploy/services/
// migrate.py's `preflight()` return shape exactly — see that module's own
// docstring for why every number here is either a live read or an honest
// `None`, never a guess.
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { api } from './client'
import type { ApiError } from './client'
import type { JobRow } from './jobs'

export type MigrateStrategy = 'cluster' | 'shared_storage' | 'transfer'

export type Preflight = {
  strategy: MigrateStrategy
  source: { host_id: number; host_name: string; node: string; ctid: number }
  target: { host_id: number; host_name: string; node: string; ctid: number }
  shared_storage: string | null
  /** null when neither a measured backup nor a live disk size exists — never fabricated. */
  transfer_bytes: number | null
  estimate_basis: 'last_backup' | 'allocated_disk' | null
  /** ESTIMATE only, from an assumed transfer rate. The job's own
   *  `result.downtime_s` is the MEASURED number — see MigrateDialog. */
  est_downtime_s: number | null
  est_note: string
  capacity_ok: boolean | null
  warnings: string[]
  blockers: string[]
  downtime_statement: string
  self_target: boolean
}

export function usePreflight() {
  return useMutation<Preflight, ApiError, { appId: number; targetHostId: number }>({
    mutationFn: ({ appId, targetHostId }) =>
      api<Preflight>(`/apps/${appId}/migrate/preflight`, {
        method: 'POST',
        body: JSON.stringify({ target_host_id: targetHostId }),
      }),
  })
}

export type MigrateVars = { appId: number; targetHostId: number; confirm?: string }

export function useMigrate() {
  const qc = useQueryClient()
  return useMutation<{ job: JobRow; preflight: Preflight }, ApiError, MigrateVars>({
    mutationFn: ({ appId, targetHostId, confirm }) =>
      api(`/apps/${appId}/migrate`, {
        method: 'POST',
        body: JSON.stringify(
          confirm ? { target_host_id: targetHostId, confirm } : { target_host_id: targetHostId }),
      }),
    onSettled: () => {
      qc.invalidateQueries({ queryKey: ['jobs'] })
      qc.invalidateQueries({ queryKey: ['cluster', 'activity'] })
    },
  })
}
