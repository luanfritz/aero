import type { Offer, OriginsDestinationsResponse } from './types'

const API = '/api'

export async function fetchDeals(params?: {
  origin?: string
  destination?: string
  limit?: number
}): Promise<Offer[]> {
  const search = new URLSearchParams()
  search.set('limit', String(params?.limit ?? 200))
  if (params?.origin) search.set('origin', params.origin)
  if (params?.destination) search.set('destination', params.destination)
  const res = await fetch(`${API}/deals?${search}`)
  if (!res.ok) throw new Error(`${res.status} ${res.statusText || 'Erro'}`)
  const ct = res.headers.get('Content-Type') || ''
  if (!ct.includes('application/json')) throw new Error('Resposta inválida do servidor (não é JSON).')
  const data = await res.json()
  if (data?.error) throw new Error(data.error)
  return Array.isArray(data) ? data : []
}

/** Ofertas de TODAS as fontes (flight_prices_raw). Com origin/destination retorna todas as ofertas cadastradas que batem no filtro. forHome=true só busca o mínimo para os cards da home (carga rápida). */
export async function fetchOpportunities(params?: {
  origin?: string
  destination?: string
  forHome?: boolean
}): Promise<Offer[]> {
  const search = new URLSearchParams()
  if (params?.origin?.trim()) search.set('origin', params.origin.trim())
  if (params?.destination?.trim()) search.set('destination', params.destination.trim())
  if (params?.forHome) search.set('for_home', '1')
  const qs = search.toString()
  const url = qs ? `${API}/opportunities?${qs}` : `${API}/opportunities`
  const res = await fetch(url)
  if (!res.ok) throw new Error(`${res.status} ${res.statusText || 'Erro'}`)
  const ct = res.headers.get('Content-Type') || ''
  if (!ct.includes('application/json')) throw new Error('Resposta inválida do servidor (não é JSON).')
  const data = await res.json()
  if (data?.error) throw new Error(data.error)
  const arr = Array.isArray(data) ? data : []
  return arr.map((row: Record<string, unknown>, index: number) => ({
    source: row.source as string,
    origin: row.origin as string,
    destination: row.destination as string,
    departure_date: (row.departure_date as string) ?? null,
    return_date: (row.return_date as string) ?? null,
    price: Number(row.price),
    url: (row.url as string) || undefined,
    score: row.score != null ? Number(row.score) : null,
    global_rank: index + 1,
  }))
}

export async function fetchOriginsDestinations(): Promise<OriginsDestinationsResponse> {
  const res = await fetch(`${API}/origins_destinations`)
  if (!res.ok) throw new Error(`${res.status}`)
  const data = await res.json()
  if (data?.error) throw new Error(data.error)
  return {
    origins: data.origins || [],
    destinations: data.destinations || [],
    labels: data.labels || {},
  }
}

// ---------- Alertas WhatsApp ----------
export interface AlertSubscription {
  id: number
  phone: string
  origin: string
  destination: string
  preferred_date?: string | null
  preferred_month?: string | null
  active: boolean
  created_at: string
  whatsapp_sent?: boolean
}

export async function createAlertSubscription(body: {
  phone: string
  origin: string
  destination: string
  preferred_date?: string
  preferred_month?: string
}): Promise<AlertSubscription> {
  const res = await fetch(`${API}/alert-subscriptions`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  const data = await res.json()
  if (data?.error) throw new Error(data.error)
  if (!res.ok) throw new Error(data?.error || `${res.status}`)
  return data as AlertSubscription
}

export async function fetchAlertSubscriptions(phone: string): Promise<AlertSubscription[]> {
  const res = await fetch(`${API}/alert-subscriptions?phone=${encodeURIComponent(phone)}`)
  if (!res.ok) throw new Error(`${res.status}`)
  const data = await res.json()
  if (data?.error) throw new Error(data.error)
  return Array.isArray(data) ? data : []
}

export async function deleteAlertSubscription(id: number): Promise<void> {
  const res = await fetch(`${API}/alert-subscriptions/${id}`, { method: 'DELETE' })
  if (!res.ok) {
    const data = await res.json().catch(() => ({}))
    throw new Error(data?.error || `${res.status}`)
  }
}

// ---------- Admin ----------
const ADMIN_TOKEN_KEY = 'voala_admin_token'

export function getAdminToken(): string | null {
  return sessionStorage.getItem(ADMIN_TOKEN_KEY)
}

export function setAdminToken(token: string): void {
  sessionStorage.setItem(ADMIN_TOKEN_KEY, token)
}

export function clearAdminToken(): void {
  sessionStorage.removeItem(ADMIN_TOKEN_KEY)
}

function adminHeaders(): Record<string, string> {
  const t = getAdminToken()
  return t ? { 'X-Admin-Token': t } : {}
}

export async function fetchAdminAlertSubscriptions(params?: {
  active_only?: boolean
  phone?: string
  origin?: string
  destination?: string
}): Promise<AlertSubscription[]> {
  const search = new URLSearchParams()
  if (params?.active_only) search.set('active_only', '1')
  if (params?.phone) search.set('phone', params.phone)
  if (params?.origin) search.set('origin', params.origin)
  if (params?.destination) search.set('destination', params.destination)
  const qs = search.toString()
  const url = qs ? `${API}/admin/alert-subscriptions?${qs}` : `${API}/admin/alert-subscriptions`
  const res = await fetch(url, { headers: adminHeaders() })
  if (res.status === 403) throw new Error('Token inválido ou ausente')
  if (!res.ok) throw new Error(`${res.status}`)
  const data = await res.json()
  if (data?.error) throw new Error(data.error)
  return Array.isArray(data) ? data : []
}

export async function sendAlertsNow(): Promise<{ sent: number; message?: string }> {
  const res = await fetch(`${API}/admin/send-alerts`, {
    method: 'POST',
    headers: adminHeaders(),
  })
  const data = await res.json()
  if (res.status === 403) throw new Error('Token inválido ou ausente')
  if (data?.error) throw new Error(data.error)
  return { sent: data.sent ?? 0, message: data.message }
}
