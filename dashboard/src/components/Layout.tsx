import { NavLink, Outlet } from 'react-router'
import { ROLE_LABELS } from '../auth/roles'
import { useAuth } from '../auth/useAuth'
import './Layout.css'

const NAV = [
  { to: '/', label: 'Overview', end: true },
  { to: '/budgets', label: 'Budgets', end: false },
  { to: '/keys', label: 'Keys', end: false },
  { to: '/requests', label: 'Requests', end: false },
]

export function Layout() {
  const { me, signOut } = useAuth()
  return (
    <div className="layout">
      <header className="topbar">
        <div className="topbar-inner">
          <span className="brand">
            <img src={`${import.meta.env.BASE_URL}favicon.svg`} alt="" width={22} height={22} />
            Tollbooth
          </span>
          <nav className="nav" aria-label="Main">
            {NAV.map((item) => (
              <NavLink key={item.to} to={item.to} end={item.end} className="nav-link">
                {item.label}
              </NavLink>
            ))}
          </nav>
          <NavLink to="/settings" className="nav-link account-link" title="Settings">
            {me?.user?.name ?? 'Admin token'}
            {me && <span className="muted"> · {ROLE_LABELS[me.role]}</span>}
          </NavLink>
          <button type="button" className="button button-ghost" onClick={() => void signOut()}>
            Sign out
          </button>
        </div>
      </header>
      <main className="content">
        <Outlet />
      </main>
    </div>
  )
}
