import type { Provider } from '../../api/types'
import { PRESETS, type RangePreset } from '../../lib/dates'

export interface Filters {
  preset: RangePreset
  from: string
  to: string
  provider: Provider | ''
  team: string
}

interface Props {
  filters: Filters
  teams: string[]
  onChange: (next: Partial<Filters>) => void
}

export function FilterBar({ filters, teams, onChange }: Props) {
  return (
    <div className="filter-bar" role="group" aria-label="Filters">
      <div className="segmented" role="group" aria-label="Date range">
        {PRESETS.map((p) => (
          <button
            key={p.value}
            type="button"
            className="segment"
            aria-pressed={filters.preset === p.value}
            aria-label={`Last ${p.days} days`}
            onClick={() => onChange({ preset: p.value })}
          >
            {p.days} days
          </button>
        ))}
        <button
          type="button"
          className="segment"
          aria-pressed={filters.preset === 'custom'}
          onClick={() => onChange({ preset: 'custom' })}
        >
          Custom
        </button>
      </div>
      {filters.preset === 'custom' && (
        <div className="custom-range">
          <label className="visually-hidden" htmlFor="range-from">
            From
          </label>
          <input
            id="range-from"
            className="input"
            type="date"
            value={filters.from}
            max={filters.to || undefined}
            onChange={(e) => onChange({ from: e.target.value })}
          />
          <span className="muted">to</span>
          <label className="visually-hidden" htmlFor="range-to">
            To
          </label>
          <input
            id="range-to"
            className="input"
            type="date"
            value={filters.to}
            min={filters.from || undefined}
            onChange={(e) => onChange({ to: e.target.value })}
          />
        </div>
      )}
      <label className="visually-hidden" htmlFor="filter-provider">
        Provider
      </label>
      <select
        id="filter-provider"
        className="select"
        value={filters.provider}
        onChange={(e) => onChange({ provider: e.target.value as Provider | '' })}
      >
        <option value="">All providers</option>
        <option value="openai">OpenAI</option>
        <option value="anthropic">Anthropic</option>
      </select>
      <label className="visually-hidden" htmlFor="filter-team">
        Team
      </label>
      <select
        id="filter-team"
        className="select"
        value={filters.team}
        onChange={(e) => onChange({ team: e.target.value })}
      >
        <option value="">All teams</option>
        {teams.map((team) => (
          <option key={team} value={team}>
            {team}
          </option>
        ))}
      </select>
    </div>
  )
}
