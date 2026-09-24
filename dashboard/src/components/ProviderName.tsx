import type { Provider } from '../api/types'
import { PROVIDER_NAMES } from '../lib/labels'

export function ProviderName({ provider }: { provider: Provider }) {
  return <>{PROVIDER_NAMES[provider]}</>
}
