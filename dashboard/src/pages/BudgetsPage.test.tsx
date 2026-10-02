import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { AlertChannel, Budget, BudgetAlert, VirtualKey } from '../api/types'
import { EMPTY_ROUTES, fakeApi, type Routes } from '../test/fakeApi'
import { renderApp } from '../test/render'

function budget(overrides: Partial<Budget> = {}): Budget {
  return {
    id: 'b1',
    name: 'Search weekly',
    scope: { type: 'team', value: 'search' },
    period: 'week',
    limit_usd: '3',
    enforcement: 'hard',
    thresholds: [50, 80, 100],
    enabled: true,
    channel_ids: [],
    created_at: '2026-09-20T00:00:00Z',
    updated_at: '2026-09-20T00:00:00Z',
    usage: {
      period_start: '2026-09-21T00:00:00Z',
      period_end: '2026-09-28T00:00:00Z',
      spend_usd: '3.2753',
      percent_used: 109.2,
      exhausted: true,
    },
    ...overrides,
  }
}

const CHANNEL: AlertChannel = {
  id: 'c1',
  name: '#llm-costs',
  type: 'slack',
  url_hint: 'hooks.slack.com',
  created_at: '2026-09-20T00:00:00Z',
}

const KEYS: VirtualKey[] = [
  {
    id: 'k1',
    name: 'search-api',
    team: 'search',
    key_prefix: 'tb_x',
    provider: 'openai',
    credential_id: 'c',
    created_at: '2026-09-01T00:00:00Z',
    revoked_at: null,
  },
]

function routes(extra: Routes = {}): Routes {
  return {
    ...EMPTY_ROUTES,
    '/admin/keys': KEYS,
    '/admin/budgets': [],
    '/admin/alerts': [],
    '/admin/channels': [],
    ...extra,
  }
}

function jsonBody(init: RequestInit): unknown {
  return JSON.parse(String(init.body))
}

afterEach(() => vi.unstubAllGlobals())

describe('budgets page', () => {
  it('shows each budget with its usage and state', async () => {
    fakeApi(
      routes({
        '/admin/budgets': [
          budget(),
          budget({
            id: 'b2',
            name: 'Research monthly',
            period: 'month',
            enforcement: 'soft',
            limit_usd: '15',
            usage: {
              period_start: '2026-09-01T00:00:00Z',
              period_end: '2026-10-01T00:00:00Z',
              spend_usd: '12.5',
              percent_used: 83.3,
              exhausted: false,
            },
          }),
          budget({ id: 'b3', name: 'Paused one', enabled: false }),
        ],
      }),
    )
    renderApp('/budgets')
    const [search, research, paused] = await screen.findAllByRole('listitem')
    expect(search).toHaveTextContent('Team search · Weekly · Resets Sep 28')
    expect(search).toHaveTextContent('Blocking')
    expect(search).toHaveTextContent('$3.28 of $3.00 · 109.2%')
    expect(within(search!).getByRole('meter')).toHaveAttribute('aria-valuenow', '100')
    expect(research).toHaveTextContent('Near limit')
    expect(research).toHaveTextContent('Alert only')
    expect(paused).toHaveTextContent('Paused')
    expect(paused).not.toHaveTextContent('Blocking')
  })

  it('creates a budget from the form', async () => {
    const api = fakeApi(
      routes({
        '/admin/channels': [CHANNEL],
        '/admin/budgets': (_url: URL, init: RequestInit) =>
          init.method === 'POST' ? budget() : [],
      }),
    )
    renderApp('/budgets')
    await userEvent.click(await screen.findByRole('button', { name: 'New budget' }))
    const form = screen.getByRole('form', { name: 'New budget' })
    await userEvent.type(within(form).getByLabelText('Name'), 'Search weekly')
    await userEvent.type(within(form).getByLabelText('Team'), 'search')
    await userEvent.selectOptions(within(form).getByLabelText('Period (UTC)'), 'week')
    await userEvent.type(within(form).getByLabelText('Limit (USD)'), '3.50')
    const thresholds = within(form).getByLabelText('Alert at (% of limit)')
    await userEvent.clear(thresholds)
    await userEvent.type(thresholds, '90, 75')
    await userEvent.click(within(form).getByLabelText('Block requests until the period resets'))
    await userEvent.click(await within(form).findByLabelText('#llm-costs'))
    await userEvent.click(within(form).getByRole('button', { name: 'Create budget' }))

    await waitFor(() => expect(api.calls.some((c) => c.init.method === 'POST')).toBe(true))
    const post = api.calls.find((c) => c.init.method === 'POST')!
    expect(jsonBody(post.init)).toEqual({
      name: 'Search weekly',
      scope: { type: 'team', value: 'search' },
      period: 'week',
      limit_usd: '3.50',
      enforcement: 'hard',
      thresholds: [75, 90],
      enabled: true,
      channel_ids: ['c1'],
    })
    await waitFor(() =>
      expect(screen.queryByRole('form', { name: 'New budget' })).not.toBeInTheDocument(),
    )
  })

  it('will not submit an invalid limit or thresholds', async () => {
    fakeApi(routes())
    renderApp('/budgets')
    await userEvent.click(await screen.findByRole('button', { name: 'New budget' }))
    const form = screen.getByRole('form', { name: 'New budget' })
    await userEvent.type(within(form).getByLabelText('Name'), 'x')
    await userEvent.type(within(form).getByLabelText('Team'), 'search')
    await userEvent.type(within(form).getByLabelText('Limit (USD)'), '-1')
    const submit = within(form).getByRole('button', { name: 'Create budget' })
    expect(submit).toBeDisabled()
    expect(within(form).getByLabelText('Limit (USD)')).toHaveAttribute('aria-invalid', 'true')

    await userEvent.clear(within(form).getByLabelText('Limit (USD)'))
    await userEvent.type(within(form).getByLabelText('Limit (USD)'), '10')
    expect(submit).toBeEnabled()
    await userEvent.type(within(form).getByLabelText('Alert at (% of limit)'), ', 0')
    expect(submit).toBeDisabled()
  })

  it('scopes a budget to a key and to all traffic', async () => {
    const api = fakeApi(
      routes({
        '/admin/budgets': (_url: URL, init: RequestInit) =>
          init.method === 'POST' ? budget() : [],
      }),
    )
    renderApp('/budgets')
    await userEvent.click(await screen.findByRole('button', { name: 'New budget' }))
    const form = screen.getByRole('form', { name: 'New budget' })
    await userEvent.type(within(form).getByLabelText('Name'), 'All')
    await userEvent.selectOptions(within(form).getByLabelText('Applies to'), 'key')
    await userEvent.selectOptions(await within(form).findByLabelText('Key'), 'k1')
    await userEvent.selectOptions(within(form).getByLabelText('Applies to'), 'global')
    expect(within(form).queryByLabelText('Key')).not.toBeInTheDocument()
    await userEvent.type(within(form).getByLabelText('Limit (USD)'), '250')
    await userEvent.click(within(form).getByRole('button', { name: 'Create budget' }))
    await waitFor(() => expect(api.calls.some((c) => c.init.method === 'POST')).toBe(true))
    const post = api.calls.find((c) => c.init.method === 'POST')!
    expect(jsonBody(post.init)).toMatchObject({ scope: { type: 'global', value: null } })
  })

  it('edits and deletes budgets', async () => {
    const api = fakeApi(
      routes({
        '/admin/budgets': [budget()],
        '/admin/budgets/b1': (_url: URL, init: RequestInit) =>
          init.method === 'DELETE' ? null : budget({ limit_usd: '10' }),
      }),
    )
    renderApp('/budgets')
    await userEvent.click(await screen.findByRole('button', { name: 'Edit Search weekly' }))
    const form = screen.getByRole('form', { name: 'Edit Search weekly' })
    expect(within(form).getByLabelText('Limit (USD)')).toHaveValue('3')
    await userEvent.clear(within(form).getByLabelText('Limit (USD)'))
    await userEvent.type(within(form).getByLabelText('Limit (USD)'), '10')
    await userEvent.click(within(form).getByLabelText('Enabled'))
    await userEvent.click(within(form).getByRole('button', { name: 'Save changes' }))
    await waitFor(() => expect(api.calls.some((c) => c.init.method === 'PATCH')).toBe(true))
    const patch = api.calls.find((c) => c.init.method === 'PATCH')!
    expect(patch.url.pathname).toBe('/admin/budgets/b1')
    expect(jsonBody(patch.init)).toMatchObject({ limit_usd: '10', enabled: false })

    await userEvent.click(await screen.findByRole('button', { name: 'Delete Search weekly' }))
    expect(api.calls.some((c) => c.init.method === 'DELETE')).toBe(false)
    await userEvent.click(screen.getByRole('button', { name: 'Delete' }))
    await waitFor(() => expect(api.calls.some((c) => c.init.method === 'DELETE')).toBe(true))
  })

  it('lists alerts with delivery outcomes', async () => {
    const alert: BudgetAlert = {
      id: 'a1',
      budget_id: 'b1',
      budget_name: 'Search weekly',
      threshold_percent: 100,
      spend_usd: '3.2753',
      limit_usd: '3',
      period_start: '2026-09-21T00:00:00Z',
      period_end: '2026-09-28T00:00:00Z',
      created_at: '2026-09-24T20:31:47Z',
      deliveries: [
        {
          channel_id: 'c1',
          channel_name: '#llm-costs',
          status: 'failed',
          attempts: 4,
          last_error: 'ConnectError',
          updated_at: '2026-09-24T20:32:18Z',
        },
        {
          channel_id: 'c2',
          channel_name: 'pager',
          status: 'delivered',
          attempts: 1,
          last_error: null,
          updated_at: '2026-09-24T20:31:48Z',
        },
      ],
    }
    fakeApi(routes({ '/admin/alerts': [alert, { ...alert, id: 'a2', deliveries: [] }] }))
    renderApp('/budgets')
    const table = await screen.findByRole('table')
    const rows = within(table).getAllByRole('row')
    expect(rows[1]).toHaveTextContent('Search weekly')
    expect(rows[1]).toHaveTextContent('100%')
    expect(rows[1]).toHaveTextContent('$3.28 / $3.00')
    expect(within(rows[1]!).getByTitle('Failed after 4 attempts: ConnectError')).toHaveTextContent(
      '#llm-costs',
    )
    expect(within(rows[1]!).getByTitle('1 attempt')).toHaveTextContent('pager')
    expect(rows[2]).toHaveTextContent('No channels')
  })

  it('adds a webhook channel and shows its secret once', async () => {
    const api = fakeApi(
      routes({
        '/admin/channels': (_url: URL, init: RequestInit) =>
          init.method === 'POST'
            ? { ...CHANNEL, id: 'c9', type: 'webhook', signing_secret: 'whsec_abc' }
            : [],
      }),
    )
    renderApp('/budgets')
    await userEvent.click(await screen.findByRole('button', { name: 'Add channel' }))
    await userEvent.type(screen.getByLabelText('Name'), 'pager')
    await userEvent.selectOptions(screen.getByLabelText('Type'), 'webhook')
    await userEvent.type(screen.getByLabelText('URL'), 'https://example.com/hook')
    await userEvent.click(screen.getByRole('button', { name: 'Add channel' }))

    expect(await screen.findByLabelText('Signing secret')).toHaveTextContent('whsec_abc')
    const post = api.calls.find((c) => c.init.method === 'POST')!
    expect(jsonBody(post.init)).toEqual({
      name: 'pager',
      type: 'webhook',
      url: 'https://example.com/hook',
    })
    await userEvent.click(screen.getByRole('button', { name: 'Done' }))
    expect(screen.queryByText('whsec_abc')).not.toBeInTheDocument()
  })

  it('sends a test and reports the result', async () => {
    fakeApi(
      routes({
        '/admin/channels': [CHANNEL],
        '/admin/channels/c1/test': { ok: false, status_code: 404, error: 'HTTP 404' },
      }),
    )
    renderApp('/budgets')
    await userEvent.click(await screen.findByRole('button', { name: 'Send test to #llm-costs' }))
    expect(await screen.findByText('Test failed: HTTP 404')).toBeInTheDocument()
  })
})
