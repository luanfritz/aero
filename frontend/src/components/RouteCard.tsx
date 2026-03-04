import type { RouteWithOffers, Offer } from '../types'
import { formatDate, formatPrice, sourceLabel, sourceClass, getOfferUrl } from '../utils'
import './RouteCard.css'

function formatAirportLabel(code: string, labels: Record<string, string>): string {
  const label = labels[code]
  return label ? `${code} (${label})` : code
}

interface RouteCardProps {
  route: RouteWithOffers
  labels: Record<string, string>
}

export function RouteCard({ route, labels }: RouteCardProps) {
  const minPrice = Math.min(...route.offers.map((o) => o.price))
  const sortedOffers = [...route.offers].sort((a, b) => {
    const da = a.departure_date ? new Date(a.departure_date).getTime() : 0
    const db = b.departure_date ? new Date(b.departure_date).getTime() : 0
    return da - db
  })

  return (
    <div className="route-card">
      <div className="route-header">
        <span className="route-route">
          {formatAirportLabel(route.origin, labels)} <span>→</span>{' '}
          {formatAirportLabel(route.destination, labels)}
        </span>
        <span className="route-min-price">{formatPrice(minPrice)}</span>
      </div>
      <div className="offers">
        <div className="offer-row offer-header">
          <span className="offer-source">Fornecedor</span>
          <span className="offer-date">Data partida</span>
          <span className="offer-return-date">Data retorno</span>
          <span className="offer-price">Preço</span>
          <span className="offer-link-cell">Ver oferta</span>
        </div>
        {sortedOffers.map((offer: Offer, i: number) => {
          const href = getOfferUrl({
            ...offer,
            origin: route.origin,
            destination: route.destination,
          })
          const returnStr = offer.return_date ? formatDate(offer.return_date) : ''
          return (
            <div key={i} className="offer-row">
              <span className={'offer-source ' + sourceClass(offer.source)}>
                {sourceLabel(offer.source)}
              </span>
              <span className="offer-date">{formatDate(offer.departure_date)}</span>
              <span className="offer-return-date">{returnStr}</span>
              <span className="offer-price">{formatPrice(offer.price)}</span>
              {href && href !== '#' ? (
                <a
                  className="offer-link"
                  href={href}
                  target="_blank"
                  rel="noopener noreferrer"
                >
                  Ver oferta
                </a>
              ) : (
                <span className="offer-link-cell" />
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}
