import type { RouteWithOffers } from '../types'
import { formatDate, formatPrice, sourceLabel, getOfferUrl, getPromotionLevel } from '../utils'
import './HighlightCard.css'

interface HighlightCardProps {
  route: RouteWithOffers
  labels: Record<string, string>
}

function formatAirportLabel(code: string, labels: Record<string, string>): string {
  const label = labels[code]
  return label ? `${label} (${code})` : code
}

export function HighlightCard({ route, labels }: HighlightCardProps) {
  const offers = route.offers
  const minPrice = Math.min(...offers.map((o) => o.price))
  const best = offers[0]
  const firstSource = best ? sourceLabel(best.source) : ''
  const offerUrl = best ? getOfferUrl({ ...best, origin: route.origin, destination: route.destination }) : '#'
  const isExternal = offerUrl && offerUrl !== '#'
  const isRoundtrip = best?.return_date != null
  const depStr = best?.departure_date ? formatDate(best.departure_date) : ''
  const retStr = best?.return_date ? formatDate(best.return_date) : ''

  const promotion = getPromotionLevel(best?.score)

  const content = (
    <>
      <div className="highlight-card-top">
        <span className={`highlight-card-badge highlight-card-badge--${promotion.className}`}>
          {promotion.label}
        </span>
        <div className="highlight-card-route-label">
          Saindo de {formatAirportLabel(route.origin, labels)}
        </div>
        <div className="highlight-card-route">
          {formatAirportLabel(route.origin, labels)} <span className="highlight-card-arrow">→</span>{' '}
          {formatAirportLabel(route.destination, labels)}
        </div>
        <div className="highlight-card-type">
          {isRoundtrip ? 'Ida e Volta' : 'Só ida'}
        </div>
      </div>

      {(depStr || retStr) && (
        <div className="highlight-card-date">
          <span className="highlight-card-date-icon">📅</span>
          {depStr && retStr ? `Ida ${depStr} · Volta ${retStr}` : depStr ? `Partida: ${depStr}` : ''}
        </div>
      )}

      <div className="highlight-card-bottom">
        <div className="highlight-card-price-label">
          {isRoundtrip ? 'Preço ida e volta' : 'Preço'}
        </div>
        <div className="highlight-card-price">{formatPrice(minPrice)}</div>
        {firstSource && <div className="highlight-card-source">Por {firstSource}</div>}
        {isExternal ? (
          <span className="highlight-card-cta">Ver oferta</span>
        ) : (
          <span className="highlight-card-cta" style={{ opacity: 0.7 }}>Ver oferta</span>
        )}
      </div>
    </>
  )

  if (isExternal) {
    return (
      <a
        href={offerUrl}
        target="_blank"
        rel="noopener noreferrer"
        className="highlight-card"
      >
        {content}
      </a>
    )
  }
  return <div className="highlight-card">{content}</div>
}
