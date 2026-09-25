import { useMemo, useState, type FormEvent } from 'react'
import { useAlertChannels, useKeys, useSaveBudget } from '../../api/queries'
import type {
  Budget,
  BudgetInput,
  BudgetPeriod,
  BudgetScopeType,
  Enforcement,
} from '../../api/types'
import { isValidLimit, parseThresholds } from '../../lib/budgets'

interface Props {
  budget: Budget | null
  onDone: () => void
}

export function BudgetForm({ budget, onDone }: Props) {
  const keys = useKeys(false)
  const channels = useAlertChannels()
  const save = useSaveBudget()

  const [name, setName] = useState(budget?.name ?? '')
  const [scopeType, setScopeType] = useState<BudgetScopeType>(budget?.scope.type ?? 'team')
  const [scopeValue, setScopeValue] = useState(budget?.scope.value ?? '')
  const [period, setPeriod] = useState<BudgetPeriod>(budget?.period ?? 'month')
  const [limit, setLimit] = useState(budget?.limit_usd ?? '')
  const [enforcement, setEnforcement] = useState<Enforcement>(budget?.enforcement ?? 'soft')
  const [thresholdText, setThresholdText] = useState(
    (budget?.thresholds ?? [50, 80, 100]).join(', '),
  )
  const [channelIds, setChannelIds] = useState<string[]>(budget?.channel_ids ?? [])
  const [enabled, setEnabled] = useState(budget?.enabled ?? true)

  const teams = useMemo(
    () => [...new Set((keys.data ?? []).map((k) => k.team))].sort(),
    [keys.data],
  )
  const thresholds = parseThresholds(thresholdText)
  const limitOk = isValidLimit(limit)
  const scopeOk = scopeType === 'global' || scopeValue.trim() !== ''
  const canSave = name.trim() !== '' && limitOk && thresholds !== null && scopeOk

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!canSave || thresholds === null) return
    const input: BudgetInput = {
      name: name.trim(),
      scope: { type: scopeType, value: scopeType === 'global' ? null : scopeValue.trim() },
      period,
      limit_usd: limit.trim(),
      enforcement,
      thresholds,
      enabled,
      channel_ids: channelIds,
    }
    await save.mutateAsync({ id: budget?.id ?? null, input })
    onDone()
  }

  function toggleChannel(id: string) {
    setChannelIds((ids) => (ids.includes(id) ? ids.filter((c) => c !== id) : [...ids, id]))
  }

  return (
    <form
      className="inline-form budget-form"
      onSubmit={(e) => void submit(e).catch(() => {})}
      aria-label={budget ? `Edit ${budget.name}` : 'New budget'}
    >
      <label className="field">
        <span className="field-label">Name</span>
        <input
          className="input"
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="search monthly"
          autoFocus
        />
      </label>
      <label className="field">
        <span className="field-label">Applies to</span>
        <select
          className="select"
          value={scopeType}
          onChange={(e) => {
            setScopeType(e.target.value as BudgetScopeType)
            setScopeValue('')
          }}
        >
          <option value="team">A team</option>
          <option value="key">A virtual key</option>
          <option value="global">All traffic</option>
        </select>
      </label>
      {scopeType === 'team' && (
        <label className="field">
          <span className="field-label">Team</span>
          <input
            className="input"
            value={scopeValue}
            onChange={(e) => setScopeValue(e.target.value)}
            list="budget-teams"
          />
          <datalist id="budget-teams">
            {teams.map((t) => (
              <option key={t} value={t} />
            ))}
          </datalist>
        </label>
      )}
      {scopeType === 'key' && (
        <label className="field">
          <span className="field-label">Key</span>
          <select
            className="select"
            value={scopeValue}
            onChange={(e) => setScopeValue(e.target.value)}
          >
            <option value="">Choose a key</option>
            {keys.data?.map((k) => (
              <option key={k.id} value={k.id}>
                {k.name} ({k.team})
              </option>
            ))}
          </select>
        </label>
      )}
      <label className="field">
        <span className="field-label">Period (UTC)</span>
        <select
          className="select"
          value={period}
          onChange={(e) => setPeriod(e.target.value as BudgetPeriod)}
        >
          <option value="day">Daily</option>
          <option value="week">Weekly (from Monday)</option>
          <option value="month">Monthly</option>
        </select>
      </label>
      <label className="field">
        <span className="field-label">Limit (USD)</span>
        <input
          className="input"
          inputMode="decimal"
          value={limit}
          onChange={(e) => setLimit(e.target.value)}
          placeholder="100"
          aria-invalid={limit !== '' && !limitOk}
        />
      </label>
      <label className="field">
        <span className="field-label">Alert at (% of limit)</span>
        <input
          className="input"
          value={thresholdText}
          onChange={(e) => setThresholdText(e.target.value)}
          aria-invalid={thresholds === null}
        />
      </label>
      <fieldset className="field field-wide choice-group">
        <legend className="field-label">When the limit is reached</legend>
        <label className="choice">
          <input
            type="radio"
            name="enforcement"
            checked={enforcement === 'soft'}
            onChange={() => setEnforcement('soft')}
          />
          Alert only
        </label>
        <label className="choice">
          <input
            type="radio"
            name="enforcement"
            checked={enforcement === 'hard'}
            onChange={() => setEnforcement('hard')}
          />
          Block requests until the period resets
        </label>
      </fieldset>
      <fieldset className="field field-wide choice-group">
        <legend className="field-label">Notify</legend>
        {channels.data?.length === 0 && (
          <span className="muted">No alert channels yet; add one below.</span>
        )}
        {channels.data?.map((c) => (
          <label key={c.id} className="choice">
            <input
              type="checkbox"
              checked={channelIds.includes(c.id)}
              onChange={() => toggleChannel(c.id)}
            />
            {c.name}
          </label>
        ))}
      </fieldset>
      {budget && (
        <label className="choice field-wide">
          <input type="checkbox" checked={enabled} onChange={(e) => setEnabled(e.target.checked)} />
          Enabled
        </label>
      )}
      <div className="form-actions">
        <button type="button" className="button" onClick={onDone}>
          Cancel
        </button>
        <button
          type="submit"
          className="button button-primary"
          disabled={!canSave || save.isPending}
        >
          {save.isPending ? 'Saving…' : budget ? 'Save changes' : 'Create budget'}
        </button>
      </div>
      {save.error && (
        <p className="error-text form-error" role="alert">
          {save.error.message}
        </p>
      )}
    </form>
  )
}
