export interface Offer {
  source: string
  origin: string
  destination: string
  departure_date: string | null
  return_date: string | null
  price: number
  url?: string
  global_rank?: number | null
  /** Score da oferta (maior = melhor; baseado em drop_pct vs média 30d) */
  score?: number | null
}

export interface RouteWithOffers {
  origin: string
  destination: string
  offers: Offer[]
}

export interface AirportOption {
  code: string
  label: string
}

export interface OriginsDestinationsResponse {
  origins: string[]
  destinations: string[]
  labels: Record<string, string>
}
