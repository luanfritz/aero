import type { RouteWithOffers } from '../types'
import { RouteCard } from './RouteCard'
import './OpportunityList.css'

interface OpportunityListProps {
  routes: RouteWithOffers[]
  labels: Record<string, string>
  onVoltarHome: () => void
}

export function OpportunityList({ routes, labels, onVoltarHome }: OpportunityListProps) {
  return (
    <section className="list-section">
      <div className="list-section-header">
        <button type="button" className="btn-voltar-home" onClick={onVoltarHome}>
          ← Voltar à home
        </button>
      </div>
      <div className="opportunities">
        {routes.map((route) => (
          <RouteCard
            key={`${route.origin}-${route.destination}`}
            route={route}
            labels={labels}
          />
        ))}
      </div>
    </section>
  )
}
