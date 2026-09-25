import { AlertsSection } from '../components/budgets/AlertsSection'
import { BudgetsSection } from '../components/budgets/BudgetsSection'
import { ChannelsSection } from '../components/budgets/ChannelsSection'
import './BudgetsPage.css'

export function BudgetsPage() {
  return (
    <div className="page">
      <div className="page-header">
        <h1>Budgets</h1>
        <span className="muted">Periods reset at midnight UTC</span>
      </div>
      <BudgetsSection />
      <AlertsSection />
      <ChannelsSection />
    </div>
  )
}
