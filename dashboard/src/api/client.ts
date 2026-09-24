export class ApiError extends Error {
  readonly status: number

  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

export type Params = Record<string, string | number | boolean | null | undefined>

export interface RequestOptions {
  method?: 'GET' | 'POST'
  params?: Params
  body?: unknown
  signal?: AbortSignal
}

export function buildPath(path: string, params: Params = {}): string {
  const query = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) {
    if (value !== null && value !== undefined && value !== '') query.set(key, String(value))
  }
  const qs = query.toString()
  return qs ? `${path}?${qs}` : path
}

export async function apiRequest<T>(
  token: string,
  path: string,
  { method = 'GET', params, body, signal }: RequestOptions = {},
): Promise<T> {
  const response = await fetch(buildPath(path, params), {
    method,
    signal,
    headers: {
      Authorization: `Bearer ${token}`,
      ...(body === undefined ? {} : { 'Content-Type': 'application/json' }),
    },
    body: body === undefined ? undefined : JSON.stringify(body),
  })
  if (!response.ok) {
    throw new ApiError(response.status, await errorMessage(response))
  }
  return (await response.json()) as T
}

async function errorMessage(response: Response): Promise<string> {
  try {
    const payload: unknown = await response.json()
    if (payload && typeof payload === 'object' && 'detail' in payload) {
      const detail = payload.detail
      if (typeof detail === 'string') return detail
      if (Array.isArray(detail) && detail.length > 0) {
        const first: unknown = detail[0]
        if (first && typeof first === 'object' && 'msg' in first) return String(first.msg)
      }
    }
  } catch {
    // Non-JSON error body; fall through to the status text.
  }
  return response.statusText || `Request failed with status ${response.status}`
}
