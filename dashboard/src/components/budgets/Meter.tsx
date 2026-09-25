import { severity } from '../../lib/budgets'

/** Spend against a limit. Fill carries severity; the track is a light step of the same hue. */
export function Meter({ percent, label }: { percent: number; label: string }) {
  const level = severity(percent)
  return (
    <div
      className={`meter meter-${level}`}
      role="meter"
      aria-label={label}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={Math.min(percent, 100)}
      aria-valuetext={`${percent}% used`}
    >
      <div className="meter-fill" style={{ width: `${Math.min(percent, 100)}%` }} />
    </div>
  )
}
