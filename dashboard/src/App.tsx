import { Navigate, Route, Routes } from 'react-router'
import { useAuth } from './auth/useAuth'
import { Layout } from './components/Layout'
import { BudgetsPage } from './pages/BudgetsPage'
import { KeysPage } from './pages/KeysPage'
import { LoginPage } from './pages/LoginPage'
import { OverviewPage } from './pages/OverviewPage'
import { RequestsPage } from './pages/RequestsPage'
import { AccountSettings } from './pages/settings/AccountSettings'
import { AuditSettings } from './pages/settings/AuditSettings'
import { SettingsPage } from './pages/settings/SettingsPage'
import { UsersSettings } from './pages/settings/UsersSettings'

export function App() {
  const { me, can, unavailable, retry } = useAuth()
  if (me === undefined && unavailable) {
    return (
      <main className="login">
        <div className="card login-card" role="alert">
          <p>Could not reach Tollbooth.</p>
          <button type="button" className="button" onClick={retry}>
            Retry
          </button>
        </div>
      </main>
    )
  }
  if (me === undefined) return <div className="boot" aria-busy="true" />
  if (me === null) return <LoginPage />
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<OverviewPage />} />
        <Route path="budgets" element={<BudgetsPage />} />
        <Route path="keys" element={<KeysPage />} />
        <Route path="requests" element={<RequestsPage />} />
        <Route path="settings" element={<SettingsPage />}>
          <Route index element={<AccountSettings />} />
          {can('admin') && <Route path="users" element={<UsersSettings />} />}
          {can('admin') && <Route path="audit" element={<AuditSettings />} />}
        </Route>
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  )
}
