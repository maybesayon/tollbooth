import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { Credential, VirtualKey } from '../api/types'
import { EMPTY_ROUTES, Reply, fakeApi } from '../test/fakeApi'
import { renderApp } from '../test/render'

const CREDENTIAL: Credential = {
  id: 'cred1',
  name: 'openai-prod',
  provider: 'openai',
  created_at: '2026-09-01T10:00:00Z',
}

function key(overrides: Partial<VirtualKey>): VirtualKey {
  return {
    id: 'k1',
    name: 'search-api',
    team: 'search',
    key_prefix: 'tb_abcdefgh',
    provider: 'openai',
    credential_id: 'cred1',
    created_at: '2026-09-02T10:00:00Z',
    revoked_at: null,
    ...overrides,
  }
}

function body(init: RequestInit): unknown {
  return JSON.parse(String(init.body))
}

afterEach(() => vi.unstubAllGlobals())

describe('keys page', () => {
  it('lists active keys and reveals revoked ones on request', async () => {
    fakeApi({
      ...EMPTY_ROUTES,
      '/admin/credentials': [CREDENTIAL],
      '/admin/keys': [
        key({}),
        key({ id: 'k2', name: 'old-bot', revoked_at: '2026-09-03T00:00:00Z' }),
      ],
    })
    renderApp('/keys')
    const table = await screen.findByRole('table', { name: '' })
    expect(within(table).getByText('search-api')).toBeInTheDocument()
    expect(within(table).queryByText('old-bot')).not.toBeInTheDocument()

    await userEvent.click(screen.getByLabelText('Show 1 revoked key'))
    expect(screen.getByText('old-bot')).toBeInTheDocument()
    expect(screen.getByText('Revoked')).toBeInTheDocument()
  })

  it('creates a key and shows it exactly once', async () => {
    const api = fakeApi({
      ...EMPTY_ROUTES,
      '/admin/credentials': [CREDENTIAL],
      '/admin/keys': (_url: URL, init: RequestInit) =>
        init.method === 'POST' ? { ...key({ team: 'ads' }), key: 'tb_secret_value' } : [],
    })
    renderApp('/keys')
    await userEvent.click(await screen.findByRole('button', { name: 'Create key' }))
    await userEvent.type(screen.getByLabelText('Name'), 'ads-service')
    await userEvent.type(screen.getByLabelText('Team'), 'ads')
    expect(screen.getByLabelText('Provider credential')).toHaveValue('cred1')
    const submit = screen
      .getAllByRole('button', { name: 'Create key' })
      .find((b) => b.getAttribute('type') === 'submit')!
    await userEvent.click(submit)

    expect(await screen.findByLabelText('New virtual key')).toHaveTextContent('tb_secret_value')
    const post = api.calls.find((c) => c.init.method === 'POST')!
    expect(body(post.init)).toEqual({ name: 'ads-service', team: 'ads', credential_id: 'cred1' })

    await userEvent.click(screen.getByRole('button', { name: 'Done' }))
    expect(screen.queryByText('tb_secret_value')).not.toBeInTheDocument()
  })

  it('revokes only after confirmation', async () => {
    const api = fakeApi({
      ...EMPTY_ROUTES,
      '/admin/credentials': [CREDENTIAL],
      '/admin/keys': [key({})],
      '/admin/keys/k1/revoke': key({ revoked_at: '2026-09-04T00:00:00Z' }),
    })
    renderApp('/keys')
    await userEvent.click(await screen.findByRole('button', { name: 'Revoke search-api' }))
    expect(api.calls.some((c) => c.url.pathname.endsWith('/revoke'))).toBe(false)

    await userEvent.click(screen.getByRole('button', { name: 'Revoke key' }))
    await waitFor(() =>
      expect(api.calls.some((c) => c.url.pathname === '/admin/keys/k1/revoke')).toBe(true),
    )
  })

  it('needs a credential before a key can be created', async () => {
    fakeApi(EMPTY_ROUTES)
    renderApp('/keys')
    expect(await screen.findByText(/No credentials yet/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Create key' })).toBeDisabled()
  })

  it('adds a credential without echoing the secret', async () => {
    const api = fakeApi({
      ...EMPTY_ROUTES,
      '/admin/credentials': (_url: URL, init: RequestInit) =>
        init.method === 'POST' ? CREDENTIAL : [],
    })
    renderApp('/keys')
    await userEvent.click(await screen.findByRole('button', { name: 'Add credential' }))
    await userEvent.type(screen.getByLabelText('Name'), 'anthropic-prod')
    await userEvent.selectOptions(screen.getByLabelText('Provider'), 'anthropic')
    await userEvent.type(screen.getByLabelText('API key'), 'sk-ant-real')
    await userEvent.click(screen.getByRole('button', { name: 'Save credential' }))

    await waitFor(() => expect(api.calls.some((c) => c.init.method === 'POST')).toBe(true))
    const post = api.calls.find((c) => c.init.method === 'POST')!
    expect(body(post.init)).toEqual({
      name: 'anthropic-prod',
      provider: 'anthropic',
      api_key: 'sk-ant-real',
    })
    await waitFor(() => expect(screen.queryByLabelText('API key')).not.toBeInTheDocument())
  })

  it('explains a duplicate credential name', async () => {
    fakeApi({
      ...EMPTY_ROUTES,
      '/admin/credentials': (_url: URL, init: RequestInit) =>
        init.method === 'POST' ? new Reply(409, { detail: 'exists' }) : [],
    })
    renderApp('/keys')
    await userEvent.click(await screen.findByRole('button', { name: 'Add credential' }))
    await userEvent.type(screen.getByLabelText('Name'), 'dup')
    await userEvent.type(screen.getByLabelText('API key'), 'x')
    await userEvent.click(screen.getByRole('button', { name: 'Save credential' }))
    expect(
      await screen.findByText('A credential with that name already exists.'),
    ).toBeInTheDocument()
  })
})
