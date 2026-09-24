import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { EMPTY_ROUTES, fakeApi } from './test/fakeApi'
import { renderApp, signIn } from './test/render'

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('sign in', () => {
  it('shows the sign-in form when there is no token', () => {
    renderApp()
    expect(screen.getByLabelText('Admin token')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Sign in' })).toBeDisabled()
  })

  it('verifies the token with the server, then shows the app', async () => {
    const api = fakeApi(EMPTY_ROUTES)
    renderApp()
    await userEvent.type(screen.getByLabelText('Admin token'), 'secret-token')
    await userEvent.click(screen.getByRole('button', { name: 'Sign in' }))

    expect(await screen.findByRole('navigation', { name: 'Main' })).toBeInTheDocument()
    const [first] = api.calls
    expect(first?.url.pathname).toBe('/admin/credentials')
    expect(first?.init.headers).toMatchObject({ Authorization: 'Bearer secret-token' })
    expect(sessionStorage.getItem('tollbooth.adminToken')).toBe('secret-token')
  })

  it('reports a rejected token', async () => {
    fakeApi({ '/admin/credentials': { detail: 'invalid or missing admin token' } }, 401)
    renderApp()
    await userEvent.type(screen.getByLabelText('Admin token'), 'wrong')
    await userEvent.click(screen.getByRole('button', { name: 'Sign in' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('That token was rejected.')
    expect(sessionStorage.getItem('tollbooth.adminToken')).toBeNull()
  })

  it('reports an unreachable server', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => Promise.reject(new TypeError('offline'))),
    )
    renderApp()
    await userEvent.type(screen.getByLabelText('Admin token'), 'x')
    await userEvent.click(screen.getByRole('button', { name: 'Sign in' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Could not reach Tollbooth')
  })
})

describe('signed in', () => {
  beforeEach(() => {
    signIn()
    fakeApi(EMPTY_ROUTES)
  })

  it('navigates between pages', async () => {
    renderApp()
    expect(screen.getByRole('heading', { name: 'Overview' })).toBeInTheDocument()
    await userEvent.click(screen.getByRole('link', { name: 'Keys' }))
    expect(screen.getByRole('heading', { name: 'Keys' })).toBeInTheDocument()
  })

  it('sends unknown paths to the overview', () => {
    renderApp('/nope')
    expect(screen.getByRole('heading', { name: 'Overview' })).toBeInTheDocument()
  })

  it('signs out when the server rejects the stored token', async () => {
    fakeApi(EMPTY_ROUTES, 401)
    renderApp()
    expect(await screen.findByLabelText('Admin token')).toBeInTheDocument()
    expect(sessionStorage.getItem('tollbooth.adminToken')).toBeNull()
  })

  it('signs out', async () => {
    renderApp()
    await userEvent.click(screen.getByRole('button', { name: 'Sign out' }))
    expect(screen.getByLabelText('Admin token')).toBeInTheDocument()
    expect(sessionStorage.getItem('tollbooth.adminToken')).toBeNull()
  })
})
