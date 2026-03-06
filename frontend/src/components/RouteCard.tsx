import type { RouteWithOffers, Offer } from '../types'
import { formatDate, formatPrice, sourceLabel, sourceClass, getOfferUrl, daysBetweenDepartureAndReturn } from '../utils'
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
      <div className="offers-wrap">
        <table className="offers-table">
          <thead>
            <tr>
              <th className="offer-source">Fornecedor</th>
              <th className="offer-date">Data partida</th>
              <th className="offer-return-date">Data retorno</th>
              <th className="offer-days">Dias (ida–volta)</th>
              <th className="offer-price">Preço</th>
              <th className="offer-link-cell">Ver oferta</th>
            </tr>
          </thead>
          <tbody>
            {sortedOffers.map((offer: Offer, i: number) => {
              const href = getOfferUrl({
                ...offer,
                origin: route.origin,
                destination: route.destination,
              })
              const returnStr = offer.return_date ? formatDate(offer.return_date) : ''
              const days = daysBetweenDepartureAndReturn(offer.departure_date, offer.return_date)
              const daysStr = days != null ? `${days} dia${days !== 1 ? 's' : ''}` : '—'
              return (
                <tr key={i}>
                  <td className={'offer-source ' + sourceClass(offer.source)}>
                    {sourceLabel(offer.source)}
                  </td>
                  <td className="offer-date">{formatDate(offer.departure_date)}</td>
                  <td className="offer-return-date">{returnStr}</td>
                  <td className="offer-days">{daysStr}</td>
                  <td className="offer-price">{formatPrice(offer.price)}</td>
                  <td className="offer-link-cell">
                    {href && href !== '#' ? (
                      <a
                        className="offer-link"
                        href={href}
                        target="_blank"
                        rel="noopener noreferrer"
                      >
                        Ver oferta
                      </a>
                    ) : null}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </div>
  )
}
