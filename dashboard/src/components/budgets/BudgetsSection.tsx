import { useMemo, useState } from 'react'
import { useBudgets, useDeleteBudget, useKeys } from '../../api/queries'
import type { Budget, VirtualKey } from '../../api/types'
import { PERIOD_LABELS, resetLabel, scopeLabel, severity } from '../../lib/budgets'
import { formatUSD, formatUSDExact } from '../../lib/format'
import { Badge } from '../Badge'
import { BudgetForm } from './BudgetForm'
import { Meter } from './Meter'

export function BudgetsSection() {
  const budgets = useBudgets()
  const keys = useKeys(true)
  const [editing, setEditing] = useState<Budget | 'new' | null>(null)
  const keysById = useMemo(() => new Map((keys.data ?? []).map((k) => [k.id, k])), [keys.data])

  return (
    <section className="card" aria-labelledby="budgets-title">
      <div className="card-header">
        <div>
          <h2 id="budgets-title">Budgets</h2>
          <p className="muted section-hint">
            Spend limits per UTC day, week, or month. Hard limits block requests once reached.
          </p>
        </div>
        {editing === null && (
          <button type="button" className="button button-primary" onClick={() => setEditing('new')}>
            New budget
          </button>
        )}
      </div>
      <div className="card-body">
        {editing === 'new' && <BudgetForm budget={null} onDone={() => setEditing(null)} />}
        {budgets.error && (
          <p className="error-text" role="alert">
            Could not load budgets: {budgets.error.message}
          </p>
        )}
        {budgets.data?.length === 0 && editing === null && (
          <p className="secondary">No budgets yet.</p>
        )}
        <ul className="budget-list">
          {budgets.data?.map((budget) =>
            editing !== 'new' && editing?.id === budget.id ? (
              <li key={budget.id}>
                <BudgetForm budget={budget} onDone={() => setEditing(null)} />
              </li>
            ) : (
              <BudgetRow
                key={budget.id}
                budget={budget}
                keys={keysById}
                onEdit={() => setEditing(budget)}
              />
            ),
          )}
        </ul>
      </div>
    </section>
  )
}

interface RowProps {
  budget: Budget
  keys: Map<string, VirtualKey>
  onEdit: () => void
}

function BudgetRow({ budget, keys, onEdit }: RowProps) {
  const remove = useDeleteBudget()
  const [confirming, setConfirming] = useState(false)
  const { usage } = budget
  const level = severity(usage.percent_used)

  return (
    <li className={budget.enabled ? 'budget-row' : 'budget-row budget-paused'}>
      <div className="budget-head">
        <div>
          <h3 className="budget-name">{budget.name}</h3>
          <p className="muted budget-meta">
            {scopeLabel(budget, keys)} · {PERIOD_LABELS[budget.period]} ·{' '}
            {resetLabel(usage.period_end)}
          </p>
        </div>
        <div className="budget-badges">
          {!budget.enabled && <Badge tone="neutral">Paused</Badge>}
          {budget.enabled && usage.exhausted && budget.enforcement === 'hard' && (
            <Badge tone="critical">Blocking</Badge>
          )}
          {budget.enabled && usage.exhausted && budget.enforcement === 'soft' && (
            <Badge tone="critical">Over limit</Badge>
          )}
          {budget.enabled && level === 'near' && <Badge tone="warning">Near limit</Badge>}
          <span className="secondary enforcement">
            {budget.enforcement === 'hard' ? 'Hard limit' : 'Alert only'}
          </span>
        </div>
      </div>
      <Meter percent={usage.percent_used} label={`${budget.name} spend`} />
      <div className="budget-foot">
        <span>
          <strong title={formatUSDExact(usage.spend_usd)}>{formatUSD(usage.spend_usd)}</strong>
          <span className="secondary"> of {formatUSD(budget.limit_usd)}</span>
          <span className="muted"> · {usage.percent_used}%</span>
        </span>
        <span className="budget-actions">
          {confirming ? (
            <>
              <span className="secondary">Delete this budget?</span>
              <button type="button" className="button" onClick={() => setConfirming(false)}>
                Cancel
              </button>
              <button
                type="button"
                className="button button-danger"
                disabled={remove.isPending}
                onClick={() => remove.mutate(budget.id)}
              >
                Delete
              </button>
            </>
          ) : (
            <>
              <button
                type="button"
                className="button button-ghost"
                onClick={onEdit}
                aria-label={`Edit ${budget.name}`}
              >
                Edit
              </button>
              <button
                type="button"
                className="button button-ghost button-danger"
                onClick={() => setConfirming(true)}
                aria-label={`Delete ${budget.name}`}
              >
                Delete
              </button>
            </>
          )}
        </span>
      </div>
    </li>
  )
}
