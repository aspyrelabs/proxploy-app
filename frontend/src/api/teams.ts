import { useQuery } from '@tanstack/react-query'
import { api } from './client'

export type TeamRow = {
  id: number; name: string; slug: string; description: string | null
  member_count: number; host_count: number
}

export type MemberRow = { user_id: number; email: string; display_name: string | null; role: string }

// Mirrors GET /users (auth.py::list_users), the member-picker source.
export type UserRow = {
  id: number; email: string; display_name: string | null; is_active: boolean
  teams: { team_id: number; role: string }[]
}

// Matches backend ROLE_ORDER (api/deps.py), MemberIn._known_role rejects anything else.
export const ROLE_OPTIONS = ['viewer', 'operator', 'admin', 'owner'] as const

export function useTeams(enabled = true) {
  return useQuery({ queryKey: ['teams'], queryFn: () => api<TeamRow[]>('/teams'), enabled })
}

export function useTeamMembers(teamId: number | null) {
  return useQuery({
    queryKey: ['teams', teamId, 'members'],
    queryFn: () => api<MemberRow[]>(`/teams/${teamId}/members`),
    enabled: teamId != null,
  })
}

export function useUsers(enabled = true) {
  return useQuery({ queryKey: ['users'], queryFn: () => api<UserRow[]>('/users'), enabled })
}
