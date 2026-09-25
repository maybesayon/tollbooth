import { NavLink, Outlet } from 'react-router'
import { useAuth } from '../../auth/useAuth'
import '../KeysPage.css'
import './SettingsPage.css'

export function SettingsPage() {
  const { can } = useAuth()
  return (
    <div className="page">
      <div className="page-header">
        <h1>Settings</h1>
      </div>
      <nav className="subnav" aria-label="Settings">
        <NavLink to="/settings" end className="subnav-link">
          Account
        </NavLink>
        {can('admin') && (
          <NavLink to="/settings/users" className="subnav-link">
            Users
          </NavLink>
        )}
        {can('admin') && (
          <NavLink to="/settings/audit" className="subnav-link">
            Audit log
          </NavLink>
        )}
      </nav>
      <Outlet />
    </div>
  )
}
