import { useMemo } from 'react'
import type { RouteWithOffers } from '../types'
import { HighlightCard } from './HighlightCard'
import './HighlightCards.css'

const HIGHLIGHT_COUNT = 9
const TOP_FIXED = 3

function routeScore(route: RouteWithOffers): number {
  const minPrice = Math.min(...(route.offers || []).map((o) => o.price || 0))
  if (minPrice <= 0) return 0
  return 1000000 / minPrice
}

function bestGlobalRank(route: RouteWithOffers): number {
  if (!route?.offers?.length) return Infinity
  const r = route.offers[0].global_rank
  return r != null ? r : Infinity
}

function shuffle<T>(arr: T[]): T[] {
  const out = [...arr]
  for (let i = out.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [out[i], out[j]] = [out[j], out[i]]
  }
  return out
}

interface HighlightCardsProps {
  routes: RouteWithOffers[]
  labels: Record<string, string>
  onVerTodas: () => void
}

export function HighlightCards({ routes, labels, onVerTodas }: HighlightCardsProps) {
  const displayRoutes = useMemo(() => {
    const sorted = [...routes].sort((a, b) => {
      const rankA = bestGlobalRank(a)
      const rankB = bestGlobalRank(b)
      if (rankA !== Infinity || rankB !== Infinity) return rankA - rankB
      return routeScore(b) - routeScore(a)
    })
    const best = sorted.slice(0, TOP_FIXED)
    const rest = sorted.slice(TOP_FIXED)
    const random = shuffle(rest).slice(0, HIGHLIGHT_COUNT - TOP_FIXED)
    return [...best, ...random]
  }, [routes])

  const top = displayRoutes

  return (
    <section className="highlight-section">
      <h2 className="highlight-title">Passagens aéreas</h2>
      <p className="highlight-desc">Confira os melhores preços – promoções em destaque</p>
      <div className="highlight-cards">
        {top.map((route) => (
          <HighlightCard key={`${route.origin}-${route.destination}`} route={route} labels={labels} />
        ))}
      </div>
      <div className="highlight-actions">
        <button type="button" className="btn-ver-todas" onClick={onVerTodas}>
          Ver mais ofertas
        </button>
      </div>
    </section>
  )
}
