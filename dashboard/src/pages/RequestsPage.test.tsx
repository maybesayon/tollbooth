import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { LedgerRequest } from '../api/types'
import { EMPTY_ROUTES, fakeApi } from '../test/fakeApi'
import { renderApp } from '../test/render'

function request(overrides: Partial<LedgerRequest>): LedgerRequest {
  return {
    id: 'r1',
    created_at: '2026-09-01T12:15:03Z',
    team: 'search',
    key_id: 'k1',
    provider: 'openai',
    model: 'gpt-4o-mini',
    streamed: true,
    status_code: 200,
    outcome: 'success',
    latency_ms: 1534,
    ttfb_ms: 210,
    input_tokens: 1134,
    output_tokens: 567,
    cache_read_tokens: 100,
    cache_write_tokens: 0,
    cost_usd: '0.0005178',
    error_type: null,
    upstream_request_id: 'req_abc',
    ...overrides,
  }
}

const KEYS = [
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

afterEach(() => vi.unstubAllGlobals())

describe('requests page', () => {
  it('lists requests with key names, outcomes, and costs', async () => {
    fakeApi({
      ...EMPTY_ROUTES,
      '/admin/keys': KEYS,
      '/admin/requests': {
        items: [
          request({}),
          request({
            id: 'r2',
            outcome: 'upstream_error',
            status_code: 429,
            cost_usd: null,
            error_type: 'rate_limit_exceeded',
          }),
        ],
        next_cursor: null,
      },
    })
    renderApp('/requests')
    await screen.findAllByText('search-api')
    const rows = screen.getAllByRole('row')
    expect(rows[1]).toHaveTextContent('search-api')
    expect(rows[1]).toHaveTextContent('Success')
    expect(rows[1]).toHaveTextContent('$0.000518')
    expect(rows[1]).toHaveTextContent('1.2K / 567')
    expect(rows[1]).toHaveTextContent('1.53 s')
    expect(rows[2]).toHaveTextContent('Upstream error')
    expect(rows[2]).toHaveTextContent('unpriced')
    expect(screen.queryByRole('button', { name: 'Load more' })).not.toBeInTheDocument()
  })

  it('expands a row into its details', async () => {
    fakeApi({
      ...EMPTY_ROUTES,
      '/admin/requests': {
        items: [request({ error_type: 'overloaded_error' })],
        next_cursor: null,
      },
    })
    renderApp('/requests')
    const toggle = await screen.findByRole('button', { name: /Sep 1/ })
    await userEvent.click(toggle)
    expect(toggle).toHaveAttribute('aria-expanded', 'true')
    expect(screen.getByText('overloaded_error')).toBeInTheDocument()
    expect(screen.getByText('req_abc')).toBeInTheDocument()
    expect(screen.getByText('$0.0005178')).toBeInTheDocument()
  })

  it('pages with the cursor', async () => {
    const api = fakeApi({
      ...EMPTY_ROUTES,
      '/admin/requests': (url: URL) =>
        url.searchParams.get('cursor') === 'next-1'
          ? { items: [request({ id: 'r2', team: 'ads' })], next_cursor: null }
          : { items: [request({})], next_cursor: 'next-1' },
    })
    renderApp('/requests')
    await userEvent.click(await screen.findByRole('button', { name: 'Load more' }))
    expect(await screen.findByText('ads')).toBeInTheDocument()
    expect(api.paramsFor('/admin/requests').at(-1)?.get('cursor')).toBe('next-1')
    await waitFor(() =>
      expect(screen.queryByRole('button', { name: 'Load more' })).not.toBeInTheDocument(),
    )
  })

  it('filters by outcome and can clear filters', async () => {
    const api = fakeApi(EMPTY_ROUTES)
    renderApp('/requests')
    expect(await screen.findByText('No requests recorded yet.')).toBeInTheDocument()

    await userEvent.selectOptions(screen.getByLabelText('Outcome'), 'upstream_error')
    await waitFor(() =>
      expect(api.paramsFor('/admin/requests').at(-1)?.get('outcome')).toBe('upstream_error'),
    )
    expect(await screen.findByText('No requests match these filters.')).toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: 'Clear filters' }))
    await waitFor(() => expect(api.paramsFor('/admin/requests').at(-1)?.has('outcome')).toBe(false))
    expect(
      within(screen.getByLabelText('Outcome')).getByRole('option', { selected: true }),
    ).toHaveTextContent('All outcomes')
  })
})
