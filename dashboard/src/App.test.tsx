import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { EMPTY_ROUTES, Reply, SIGNED_OUT, fakeApi, me } from './test/fakeApi'
import { renderApp } from './test/render'

afterEach(() => {
  vi.unstubAllGlobals()
})

function bodyOf(init: RequestInit): unknown {
  return JSON.parse(String(init.body))
}

describe('sign in', () => {
  it('shows the sign-in form when there is no session', async () => {
    fakeApi(SIGNED_OUT)
    renderApp()
    expect(await screen.findByLabelText('Email')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Sign in' })).toBeDisabled()
  })

  it('signs in with email and password over the session cookie', async () => {
    const api = fakeApi({ ...EMPTY_ROUTES, ...SIGNED_OUT, '/auth/login': me('editor') })
    renderApp()
    await userEvent.type(await screen.findByLabelText('Email'), 'ada@example.com')
    await userEvent.type(screen.getByLabelText('Password'), 'correct horse battery')
    await userEvent.click(screen.getByRole('button', { name: 'Sign in' }))

    expect(await screen.findByRole('navigation', { name: 'Main' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /Ada editor/ })).toHaveTextContent(
      'Ada editor · Editor',
    )
    const login = api.calls.find((c) => c.url.pathname === '/auth/login')!
    expect(bodyOf(login.init)).toEqual({
      email: 'ada@example.com',
      password: 'correct horse battery',
    })
    expect(login.init.credentials).toBe('same-origin')
    expect(login.init.headers).toMatchObject({ 'X-Tollbooth-CSRF': '1' })
    expect(login.init.headers).not.toHaveProperty('Authorization')
  })

  it.each([
    [401, 'Wrong email or password.'],
    [429, 'Too many attempts. Wait a few minutes and try again.'],
  ])('explains a %s', async (status, message) => {
    fakeApi({ ...SIGNED_OUT, '/auth/login': new Reply(status, { detail: 'nope' }) })
    renderApp()
    await userEvent.type(await screen.findByLabelText('Email'), 'ada@example.com')
    await userEvent.type(screen.getByLabelText('Password'), 'x')
    await userEvent.click(screen.getByRole('button', { name: 'Sign in' }))
    expect(await screen.findByRole('alert')).toHaveTextContent(message)
  })

  it('reports an unreachable server', async () => {
    fakeApi(SIGNED_OUT)
    renderApp()
    const email = await screen.findByLabelText('Email')
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => Promise.reject(new TypeError('offline'))),
    )
    await userEvent.type(email, 'a@b.co')
    await userEvent.type(screen.getByLabelText('Password'), 'x')
    await userEvent.click(screen.getByRole('button', { name: 'Sign in' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Could not reach Tollbooth')
  })
})

describe('first-run setup', () => {
  it('creates the first admin with the admin token', async () => {
    const api = fakeApi({
      ...EMPTY_ROUTES,
      ...SIGNED_OUT,
      '/auth/setup': (_url: URL, init: RequestInit) =>
        init.method === 'POST' ? me('admin') : { needs_setup: true, setup_with_admin_token: true },
    })
    renderApp()
    await userEvent.type(await screen.findByLabelText('Admin token'), 'the-admin-token')
    await userEvent.type(screen.getByLabelText('Your name'), 'Ada')
    await userEvent.type(screen.getByLabelText('Email'), 'ada@example.com')
    const submit = screen.getByRole('button', { name: 'Create admin account' })
    await userEvent.type(screen.getByLabelText(/Password/), 'short')
    expect(submit).toBeDisabled()
    await userEvent.type(screen.getByLabelText(/Password/), ' but long enough')
    await userEvent.click(submit)

    expect(await screen.findByRole('navigation', { name: 'Main' })).toBeInTheDocument()
    const post = api.calls.find((c) => c.init.method === 'POST')!
    expect(bodyOf(post.init)).toEqual({
      admin_token: 'the-admin-token',
      name: 'Ada',
      email: 'ada@example.com',
      password: 'short but long enough',
    })
  })

  it('points to the CLI when no admin token is configured', async () => {
    fakeApi({
      ...SIGNED_OUT,
      '/auth/setup': { needs_setup: true, setup_with_admin_token: false },
    })
    renderApp()
    expect(await screen.findByText(/tollbooth create-user/)).toBeInTheDocument()
    expect(screen.queryByLabelText('Admin token')).not.toBeInTheDocument()
  })
})

describe('signed in', () => {
  it('navigates between pages', async () => {
    fakeApi(EMPTY_ROUTES)
    renderApp()
    expect(await screen.findByRole('heading', { name: 'Overview' })).toBeInTheDocument()
    await userEvent.click(screen.getByRole('link', { name: 'Keys' }))
    expect(screen.getByRole('heading', { name: 'Keys' })).toBeInTheDocument()
  })

  it('sends unknown paths to the overview', async () => {
    fakeApi(EMPTY_ROUTES)
    renderApp('/nope')
    expect(await screen.findByRole('heading', { name: 'Overview' })).toBeInTheDocument()
  })

  it('offers a retry when the session check fails', async () => {
    fakeApi({ ...EMPTY_ROUTES, '/auth/me': new Reply(502, { detail: 'bad gateway' }) })
    renderApp()
    expect(await screen.findByRole('alert')).toHaveTextContent('Could not reach Tollbooth.')
    fakeApi(EMPTY_ROUTES)
    await userEvent.click(screen.getByRole('button', { name: 'Retry' }))
    expect(await screen.findByRole('heading', { name: 'Overview' })).toBeInTheDocument()
  })

  it('returns to sign-in when the session is rejected', async () => {
    fakeApi({ ...EMPTY_ROUTES, '/admin/spend': new Reply(401, { detail: 'session expired' }) })
    renderApp()
    expect(await screen.findByLabelText('Email')).toBeInTheDocument()
  })

  it('signs out', async () => {
    const api = fakeApi(EMPTY_ROUTES)
    renderApp()
    await userEvent.click(await screen.findByRole('button', { name: 'Sign out' }))
    expect(await screen.findByLabelText('Email')).toBeInTheDocument()
    await waitFor(() => expect(api.calls.some((c) => c.url.pathname === '/auth/logout')).toBe(true))
  })
})

describe('roles', () => {
  it('shows viewers no editing controls', async () => {
    fakeApi({ ...EMPTY_ROUTES, '/auth/me': me('viewer') })
    renderApp('/keys')
    expect(await screen.findByRole('heading', { name: 'Virtual keys' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Create key' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Add credential' })).not.toBeInTheDocument()
    await userEvent.click(screen.getByRole('link', { name: 'Budgets' }))
    expect(await screen.findByRole('heading', { name: 'Recent alerts' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'New budget' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Add channel' })).not.toBeInTheDocument()
  })

  it('lets editors manage keys but not credentials or users', async () => {
    fakeApi({
      ...EMPTY_ROUTES,
      '/auth/me': me('editor'),
      '/admin/credentials': [
        { id: 'c', name: 'openai', provider: 'openai', created_at: '2026-09-01T00:00:00Z' },
      ],
    })
    renderApp('/keys')
    const create = await screen.findByRole('button', { name: 'Create key' })
    await waitFor(() => expect(create).toBeEnabled())
    expect(screen.queryByRole('button', { name: 'Add credential' })).not.toBeInTheDocument()
    await userEvent.click(screen.getByRole('link', { name: /Ada editor/ }))
    expect(await screen.findByRole('heading', { name: 'Profile' })).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: 'Users' })).not.toBeInTheDocument()
  })
})
