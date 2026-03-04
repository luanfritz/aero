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
