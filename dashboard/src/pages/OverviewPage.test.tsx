import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { EMPTY_ROUTES, Reply, fakeApi, metrics, spendReport, timeseries } from '../test/fakeApi'
import { renderApp } from '../test/render'

const GROUPS = [
  {
    ...metrics({
      requests: 120,
      error_requests: 6,
      input_tokens: 5000,
      output_tokens: 900,
      cost_usd: '12.5',
    }),
    group: 'search',
  },
  { ...metrics({ requests: 30, unpriced_requests: 2, cost_usd: '0.0421' }), group: 'ads' },
]

afterEach(() => vi.unstubAllGlobals())

describe('overview', () => {
  it('shows totals and the breakdown', async () => {
    fakeApi({
      ...EMPTY_ROUTES,
      '/admin/spend': spendReport(GROUPS),
      '/admin/spend/timeseries': timeseries([{ ...GROUPS[0]!, bucket: '2026-09-01T00:00:00Z' }]),
    })
    renderApp()

    const summary = await screen.findByRole('region', { name: 'Summary' })
    expect(within(summary).getByText('$12.54')).toBeInTheDocument()
    expect(within(summary).getByText('4%')).toBeInTheDocument()
    expect(within(summary).getByText(/Excludes 2 unpriced requests/)).toBeInTheDocument()

    const table = screen.getByRole('table')
    const rows = within(table).getAllByRole('row')
    expect(rows[1]).toHaveTextContent('search')
    expect(rows[1]).toHaveTextContent('$12.50')
    expect(rows[1]).toHaveTextContent('99.7%')
    expect(rows[2]).toHaveTextContent('$0.0421')
  })

  it('gives table rows the same colors as the chart, including Other', async () => {
    const models = Array.from({ length: 8 }, (_, i) => ({
      ...metrics({ requests: 1, cost_usd: String(8 - i) }),
      group: `model-${i}`,
    }))
    fakeApi({
      ...EMPTY_ROUTES,
      '/admin/spend': spendReport(models),
      '/admin/spend/timeseries': timeseries(
        models.map((m) => ({ ...m, bucket: '2026-09-01T00:00:00Z' })),
      ),
    })
    renderApp('/?split=model')
    const table = await screen.findByRole('table')
    await waitFor(() => {
      const swatches = table.querySelectorAll<HTMLElement>('.legend-swatch')
      expect([...swatches].map((s) => s.style.background)).toEqual([
        'var(--series-1)',
        'var(--series-2)',
        'var(--series-3)',
        'var(--series-4)',
        'var(--series-5)',
        'var(--series-6)',
        'var(--series-other)',
        'var(--series-other)',
      ])
    })
  })

  it('shows an empty state when nothing was recorded', async () => {
    fakeApi(EMPTY_ROUTES)
    renderApp()
    expect(await screen.findByText('No requests in this range.')).toBeInTheDocument()
    expect(screen.queryByRole('table')).not.toBeInTheDocument()
  })

  it('reports load errors', async () => {
    fakeApi({ ...EMPTY_ROUTES, '/admin/spend': new Reply(500, { detail: 'boom' }) })
    renderApp()
    expect(await screen.findByRole('alert')).toHaveTextContent('Could not load spend data')
  })

  it('scopes every query to the selected filters', async () => {
    const api = fakeApi({ ...EMPTY_ROUTES, '/admin/spend': spendReport(GROUPS) })
    renderApp()
    await screen.findByRole('table')

    await userEvent.click(screen.getByRole('button', { name: 'Last 7 days' }))
    await userEvent.selectOptions(screen.getByLabelText('Provider'), 'anthropic')
    await userEvent.click(screen.getByRole('button', { name: 'Model' }))

    await waitFor(() => {
      const last = api.paramsFor('/admin/spend/timeseries').at(-1)
      expect(last?.get('group_by')).toBe('model')
    })
    const series = api.paramsFor('/admin/spend/timeseries').at(-1)!
    const spend = api.paramsFor('/admin/spend').at(-1)!
    for (const params of [series, spend]) {
      expect(params.get('provider')).toBe('anthropic')
      const days = (Date.parse(params.get('end')!) - Date.parse(params.get('start')!)) / 86_400_000
      expect(days).toBe(7)
    }
    expect(screen.getByRole('heading', { name: 'Breakdown by model' })).toBeInTheDocument()
  })

  it('offers teams from the current range as a filter', async () => {
    const api = fakeApi({ ...EMPTY_ROUTES, '/admin/spend': spendReport(GROUPS) })
    renderApp()
    const teamSelect = await screen.findByLabelText('Team')
    await waitFor(() => expect(within(teamSelect).getAllByRole('option')).toHaveLength(3))
    await userEvent.selectOptions(teamSelect, 'search')
    await waitFor(() =>
      expect(api.paramsFor('/admin/spend/timeseries').at(-1)?.get('team')).toBe('search'),
    )
  })

  it('shows date inputs for a custom range', async () => {
    fakeApi(EMPTY_ROUTES)
    renderApp()
    await userEvent.click(await screen.findByRole('button', { name: 'Custom' }))
    expect(screen.getByLabelText('From')).toHaveValue()
    expect(screen.getByLabelText('To')).toHaveValue()
  })
})
