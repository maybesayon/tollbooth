import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router'
import { App } from './App'
import { AuthProvider } from './auth/AuthProvider'

function renderApp(path = '/') {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={queryClient}>
      <AuthProvider>
        <MemoryRouter initialEntries={[path]}>
          <App />
        </MemoryRouter>
      </AuthProvider>
    </QueryClientProvider>,
  )
}

function mockFetch(status: number, body: unknown = []) {
  const fetchMock = vi.fn(async () => new Response(JSON.stringify(body), { status }))
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

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
    const fetchMock = mockFetch(200)
    renderApp()
    await userEvent.type(screen.getByLabelText('Admin token'), 'secret-token')
    await userEvent.click(screen.getByRole('button', { name: 'Sign in' }))

    expect(await screen.findByRole('navigation', { name: 'Main' })).toBeInTheDocument()
    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit]
    expect(url).toBe('/admin/credentials')
    expect(init.headers).toMatchObject({ Authorization: 'Bearer secret-token' })
    expect(sessionStorage.getItem('tollbooth.adminToken')).toBe('secret-token')
  })

  it('reports a rejected token', async () => {
    mockFetch(401, { detail: 'invalid or missing admin token' })
    renderApp()
    await userEvent.type(screen.getByLabelText('Admin token'), 'wrong')
    await userEvent.click(screen.getByRole('button', { name: 'Sign in' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('That token was rejected.')
    expect(sessionStorage.getItem('tollbooth.adminToken')).toBeNull()
  })

  it('reports an unreachable server', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => Promise.reject(new TypeError('offline'))))
    renderApp()
    await userEvent.type(screen.getByLabelText('Admin token'), 'x')
    await userEvent.click(screen.getByRole('button', { name: 'Sign in' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Could not reach Tollbooth')
  })
})

describe('signed in', () => {
  beforeEach(() => {
    sessionStorage.setItem('tollbooth.adminToken', 'secret-token')
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

  it('signs out', async () => {
    renderApp()
    await userEvent.click(screen.getByRole('button', { name: 'Sign out' }))
    expect(screen.getByLabelText('Admin token')).toBeInTheDocument()
    expect(sessionStorage.getItem('tollbooth.adminToken')).toBeNull()
  })
})
