import type { Outcome } from '../api/types'
import { OUTCOMES, type Tone } from '../lib/labels'
import './Badge.css'

const ICONS: Record<Tone, string> = {
  good: '✓',
  warning: '!',
  serious: '!',
  critical: '✕',
  neutral: '–',
}

/** A status is never color alone: every badge carries an icon and a label. */
export function Badge({ tone, children }: { tone: Tone; children: string }) {
  return (
    <span className={`badge badge-${tone}`}>
      <span className="badge-icon" aria-hidden="true">
        {ICONS[tone]}
      </span>
      {children}
    </span>
  )
}

export function OutcomeBadge({ outcome }: { outcome: Outcome }) {
  const { tone, label } = OUTCOMES[outcome]
  return <Badge tone={tone}>{label}</Badge>
}
