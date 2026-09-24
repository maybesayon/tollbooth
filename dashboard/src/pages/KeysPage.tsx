import { CredentialsSection } from '../components/keys/CredentialsSection'
import { KeysSection } from '../components/keys/KeysSection'
import './KeysPage.css'

export function KeysPage() {
  return (
    <div className="page">
      <div className="page-header">
        <h1>Keys</h1>
      </div>
      <KeysSection />
      <CredentialsSection />
    </div>
  )
}
