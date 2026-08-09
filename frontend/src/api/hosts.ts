import { useQuery } from '@tanstack/react-query'
import { api } from './client'

// Mirrors backend/proxploy/api/hosts.py::host_tasks' row dict, the node's own
// task list (PVE tasks Proxploy did not necessarily start itself).
export type HostTaskRow = {
  upid: string; type: string | null; id: string | null; node: string | null
  user: string | null; status: string | null; exitstatus: string | null
  starttime: number | null; endtime: number | null
}

export type HostTaskLog = { upid: string; lines: string[] }

export function useHostTasks(hostId: number | null, enabled = true) {
  return useQuery({
    queryKey: ['hosts', hostId, 'tasks'],
    queryFn: () => api<HostTaskRow[]>(`/hosts/${hostId}/tasks?limit=50`),
    enabled: enabled && hostId != null,
  })
}

export function useHostTaskLog(hostId: number | null, upid: string | null) {
  // Encoded outside the template literal: a UPID is full of characters that
  // must not reach the path raw, and the cast this used to need inline is
  // what the route-coverage audit (backend/tests/test_openapi_surface.py)
  // choked on, silently reading the call as /hosts/{}/tasks/{} with no /log.
  const upidPath = upid == null ? '' : encodeURIComponent(upid)
  return useQuery({
    queryKey: ['hosts', hostId, 'tasks', upid, 'log'],
    queryFn: () => api<HostTaskLog>(`/hosts/${hostId}/tasks/${upidPath}/log`),
    enabled: hostId != null && upid != null,
  })
}
