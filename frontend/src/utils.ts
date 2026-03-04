/** Níveis de promoção com base no score (drop_pct): 1 = mais fraco, 5 = imbatível */
export type PromotionLevel = { level: number; label: string; className: string }

export function getPromotionLevel(score: number | null | undefined): PromotionLevel {
  const s = score == null ? -1 : Number(score)
  if (s < 0) return { level: 1, label: 'Oferta', className: 'level-1' }
  if (s < 5) return { level: 2, label: 'Boa oferta', className: 'level-2' }
  if (s < 15) return { level: 3, label: 'Ótima oferta', className: 'level-3' }
  if (s < 25) return { level: 4, label: 'Imperdível', className: 'level-4' }
  return { level: 5, label: 'Imbatível 🔥', className: 'level-5' }
}

export function formatPrice(n: number): string {
  return 'R$ ' + Number(n).toLocaleString('pt-BR')
}

export function formatDate(iso: string | null | undefined): string {
  if (!iso) return '—'
  return new Date(iso).toLocaleDateString('pt-BR', {
    day: '2-digit',
    month: '2-digit',
    year: 'numeric',
  })
}

export function toYyyyMmDd(isoOrDate: string | Date | null | undefined): string {
  if (!isoOrDate) return ''
  const d = new Date(isoOrDate)
  if (isNaN(d.getTime())) return ''
  const y = d.getFullYear()
  const m = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  return `${y}-${m}-${day}`
}

export function sourceLabel(source: string | undefined): string {
  if (!source) return '—'
  if (source === 'viajanet') return 'ViajaNet'
  if (source === 'passagens_imperdiveis') return 'Passagens Imperdíveis'
  if (source === 'melhores_destinos') return 'Melhores Destinos'
  return source.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase())
}

export function sourceClass(source: string | undefined): string {
  if (!source) return ''
  return source.toLowerCase().replace(/[^a-z0-9]/g, '_')
}

export function parseAirportInput(val: string): string {
  val = (val || '').trim()
  const match = val.match(/\s*\(([A-Z0-9]{3})\)\s*$/i)
  return match ? match[1].toUpperCase() : val.toUpperCase()
}

export function buildViajanetOnewayUrl(
  origin: string,
  destination: string,
  departureDate: string
): string | null {
  const o = (origin || '').toUpperCase()
  const d = (destination || '').toUpperCase()
  const dateStr = toYyyyMmDd(departureDate)
  if (!o || !d || !dateStr) return null
  return `https://www.viajanet.com.br/shop/flights/results/oneway/${o}/${d}/${dateStr}/1/0/0?from=SB&di=1&reSearch=true`
}

export function getOfferUrl(offer: {
  source?: string
  origin: string
  destination: string
  departure_date?: string | null
  return_date?: string | null
  url?: string
}): string {
  if (offer.url && offer.url.startsWith('http')) return offer.url
  const src = (offer.source || '').toLowerCase()
  const isOneway = !offer.return_date
  if (src === 'viajanet' && isOneway && offer.departure_date) {
    const u = buildViajanetOnewayUrl(
      offer.origin,
      offer.destination,
      offer.departure_date
    )
    if (u) return u
  }
  return offer.url || '#'
}

export function parseDateOnly(iso: string | null | undefined): number | null {
  if (!iso) return null
  const d = new Date(iso)
  if (isNaN(d.getTime())) return null
  return new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime()
}

export function parseMonthInput(val: string): { year: number; month: number } | null {
  const s = (val || '').trim()
  if (!s) return null
  const parts = s.split(/[/-]/)
  if (parts.length !== 2) return null
  const a = parseInt(parts[0], 10)
  const b = parseInt(parts[1], 10)
  const year = parts[0].length === 4 ? a : b
  const month = parts[0].length === 4 ? b : a
  if (month >= 1 && month <= 12 && year >= 2000 && year <= 2100) {
    return { year, month: month - 1 }
  }
  return null
}

export const MONTH_NAMES_SHORT = ['Jan', 'Fev', 'Mar', 'Abr', 'Mai', 'Jun', 'Jul', 'Ago', 'Set', 'Out', 'Nov', 'Dez']
export const MONTH_NAMES_LONG = [
  'Janeiro', 'Fevereiro', 'Março', 'Abril', 'Maio', 'Junho',
  'Julho', 'Agosto', 'Setembro', 'Outubro', 'Novembro', 'Dezembro',
]
