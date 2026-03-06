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

/** Ofertas de TODAS as fontes (flight_prices_raw). Com origin/destination retorna todas as ofertas cadastradas que batem no filtro. */
export async function fetchOpportunities(params?: {
  origin?: string
  destination?: string
}): Promise<Offer[]> {
  const search = new URLSearchParams()
  if (params?.origin?.trim()) search.set('origin', params.origin.trim())
  if (params?.destination?.trim()) search.set('destination', params.destination.trim())
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
