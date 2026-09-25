import type { Role } from '../api/types'

const ORDER: Role[] = ['viewer', 'editor', 'admin']

export function includes(role: Role, needed: Role): boolean {
  return ORDER.indexOf(role) >= ORDER.indexOf(needed)
}

export const ROLE_LABELS: Record<Role, string> = {
  viewer: 'Viewer',
  editor: 'Editor',
  admin: 'Admin',
}
