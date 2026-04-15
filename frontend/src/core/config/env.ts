const trimTrailingSlash = (value: string): string => value.replace(/\/+$/, '')
const defaultApiBaseUrl = '/api'

export const appEnv = {
  apiBaseUrl: trimTrailingSlash(import.meta.env.VITE_API_BASE_URL?.trim() || defaultApiBaseUrl),
}
