import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { AuditEvent, User } from '../../api/types'
import { EMPTY_ROUTES, Reply, fakeApi, me } from '../../test/fakeApi'
import { renderApp } from '../../test/render'

afterEach(() => vi.unstubAllGlobals())

function bodyOf(init: RequestInit): unknown {
  return JSON.parse(String(init.body))
}

function user(overrides: Partial<User>): User {
  return { ...me('viewer').user!, ...overrides }
}

describe('account settings', () => {
  it('changes the password', async () => {
    const api = fakeApi({
      ...EMPTY_ROUTES,
      '/auth/tokens': [],
      '/auth/password': (_url: URL, init: RequestInit) => {
        const { current_password } = bodyOf(init) as { current_password: string }
        return current_password === 'old password here'
          ? new Reply(204)
          : new Reply(400, { detail: 'current password is wrong' })
      },
    })
    renderApp('/settings')
    expect(await screen.findByText('admin@example.com')).toBeInTheDocument()
    await userEvent.type(screen.getByLabelText('Current password'), 'wrong one')
    await userEvent.type(screen.getByLabelText(/New password/), 'a brand new password')
    await userEvent.click(screen.getByRole('button', { name: 'Change password' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Your current password is wrong.')

    await userEvent.clear(screen.getByLabelText('Current password'))
    await userEvent.type(screen.getByLabelText('Current password'), 'old password here')
    await userEvent.click(screen.getByRole('button', { name: 'Change password' }))
    expect(await screen.findByText('Password changed.')).toBeInTheDocument()
    expect(api.calls.filter((c) => c.url.pathname === '/auth/password')).toHaveLength(2)
  })

  it('creates an API token and shows it once', async () => {
    const api = fakeApi({
      ...EMPTY_ROUTES,
      '/auth/tokens': (_url: URL, init: RequestInit) =>
        init.method === 'POST'
          ? {
              id: 't1',
              name: 'ci',
              prefix: 'tbu_abcdefgh',
              created_at: '2026-09-24T00:00:00Z',
              last_used_at: null,
              token: 'tbu_abcdefgh_the_rest',
            }
          : [],
    })
    renderApp('/settings')
    await userEvent.type(await screen.findByLabelText('Token name'), 'ci')
    await userEvent.click(screen.getByRole('button', { name: 'Create token' }))
    expect(await screen.findByLabelText('New API token')).toHaveTextContent('tbu_abcdefgh_the_rest')
    expect(bodyOf(api.calls.find((c) => c.init.method === 'POST')!.init)).toEqual({ name: 'ci' })
    await userEvent.click(screen.getByRole('button', { name: 'Done' }))
    expect(screen.queryByText('tbu_abcdefgh_the_rest')).not.toBeInTheDocument()
  })

  it('explains that the admin token has no account', async () => {
    fakeApi({ ...EMPTY_ROUTES, '/auth/me': { user: null, role: 'admin', via: 'admin_token' } })
    renderApp('/settings')
    expect(await screen.findByText(/admin token, which has no account/)).toBeInTheDocument()
  })
})

describe('users settings', () => {
  const USERS = [
    user({ id: 'u1', email: 'admin@example.com', name: 'Ada admin', role: 'admin' }),
    user({ id: 'u2', email: 'vi@example.com', name: 'Vi', role: 'viewer' }),
  ]

  it('changes roles, disables users, and resets passwords', async () => {
    const api = fakeApi({
      ...EMPTY_ROUTES,
      '/admin/users': USERS,
      '/admin/users/u2': (_url: URL, init: RequestInit) => ({
        ...USERS[1],
        ...(bodyOf(init) as object),
      }),
      '/admin/users/u2/reset-password': { temporary_password: 'Temp-Pass-123456' },
    })
    renderApp('/settings/users')
    const rows = await screen.findAllByRole('row')
    expect(within(rows[1]!).getByText('(you)')).toBeInTheDocument()
    expect(within(rows[1]!).getByLabelText('Role for admin@example.com')).toBeDisabled()
    expect(within(rows[1]!).queryByRole('button', { name: /Disable/ })).not.toBeInTheDocument()

    await userEvent.selectOptions(screen.getByLabelText('Role for vi@example.com'), 'editor')
    await userEvent.click(screen.getByRole('button', { name: 'Disable vi@example.com' }))
    await userEvent.click(screen.getByRole('button', { name: 'Reset password for vi@example.com' }))
    expect(await screen.findByLabelText('Temporary password')).toHaveTextContent('Temp-Pass-123456')

    const patches = api.calls.filter((c) => c.init.method === 'PATCH').map((c) => bodyOf(c.init))
    expect(patches).toEqual([{ role: 'editor' }, { disabled: true }])
  })

  it('adds a user and shows the temporary password', async () => {
    const api = fakeApi({
      ...EMPTY_ROUTES,
      '/admin/users': (_url: URL, init: RequestInit) =>
        init.method === 'POST'
          ? {
              ...user({ id: 'u3', email: 'new@example.com' }),
              temporary_password: 'Fresh-Temp-987654',
            }
          : USERS,
    })
    renderApp('/settings/users')
    await userEvent.click(await screen.findByRole('button', { name: 'Add user' }))
    const form = screen.getByRole('form', { name: 'New user' })
    await userEvent.type(within(form).getByLabelText('Name'), 'New')
    await userEvent.type(within(form).getByLabelText('Email'), 'new@example.com')
    await userEvent.selectOptions(within(form).getByLabelText('Role'), 'editor')
    await userEvent.click(within(form).getByRole('button', { name: 'Add user' }))
    expect(await screen.findByLabelText('Temporary password')).toHaveTextContent(
      'Fresh-Temp-987654',
    )
    expect(bodyOf(api.calls.find((c) => c.init.method === 'POST')!.init)).toEqual({
      name: 'New',
      email: 'new@example.com',
      role: 'editor',
    })
  })

  it('is admin-only', async () => {
    fakeApi({ ...EMPTY_ROUTES, '/auth/me': me('editor'), '/auth/tokens': [] })
    renderApp('/settings/users')
    expect(await screen.findByRole('heading', { name: 'Overview' })).toBeInTheDocument()
  })
})

describe('audit settings', () => {
  function events(count: number, offset = 0): AuditEvent[] {
    return Array.from({ length: count }, (_, i) => ({
      id: `e${i + offset}`,
      created_at: `2026-09-24T12:${String(59 - i - offset).padStart(2, '0')}:00Z`,
      actor_type: 'session',
      actor_id: 'u1',
      actor_label: 'admin@example.com',
      action: 'key.created',
      target_type: 'key',
      target_id: 'k',
      details: { name: `svc-${i + offset}`, team: 'search' },
    }))
  }

  it('lists events, filters by action, and pages', async () => {
    const api = fakeApi({
      ...EMPTY_ROUTES,
      '/admin/audit': (url: URL) => (url.searchParams.get('before') ? events(3, 50) : events(50)),
    })
    renderApp('/settings/audit')
    expect(await screen.findByText('svc-0 · team: search')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Load more' }))
    expect(await screen.findByText('svc-52 · team: search')).toBeInTheDocument()
    expect(api.paramsFor('/admin/audit').at(-1)?.get('before')).toBe('2026-09-24T12:10:00Z')
    expect(screen.queryByRole('button', { name: 'Load more' })).not.toBeInTheDocument()

    await userEvent.selectOptions(screen.getByLabelText('Action'), 'auth.login_failed')
    await waitFor(() =>
      expect(api.paramsFor('/admin/audit').at(-1)?.get('action')).toBe('auth.login_failed'),
    )
  })
})
