import { useState, useEffect, useMemo } from 'react'
import { fetchDeals, fetchOriginsDestinations } from './api'
import type { Offer, RouteWithOffers, AirportOption } from './types'
import { parseAirportInput, parseDateOnly, parseMonthInput } from './utils'
import { Header } from './components/Header'
import { Filters } from './components/Filters'
import { HighlightCards } from './components/HighlightCards'
import { OpportunityList } from './components/OpportunityList'
import './components/States.css'
import './App.css'

type ViewMode = 'home' | 'list'
type UiState = 'loading' | 'empty' | 'error' | 'ok'

function groupByRoute(opportunities: Offer[]): RouteWithOffers[] {
  const byRoute: Record<string, RouteWithOffers> = {}
  for (const o of opportunities) {
    const key = o.origin + '|' + o.destination
    if (!byRoute[key]) byRoute[key] = { origin: o.origin, destination: o.destination, offers: [] }
    byRoute[key].offers.push(o)
  }
  for (const k of Object.keys(byRoute)) {
    const offers = byRoute[k].offers
    offers.sort((a, b) => {
      if (a.global_rank != null && b.global_rank != null) return a.global_rank - b.global_rank
      return a.price - b.price
    })
  }
  return Object.values(byRoute)
}

function App() {
  const [allOpportunities, setAllOpportunities] = useState<Offer[]>([])
  const [labels, setLabels] = useState<Record<string, string>>({})
  const [originOptions, setOriginOptions] = useState<AirportOption[]>([])
  const [destOptions, setDestOptions] = useState<AirportOption[]>([])

  const [origin, setOrigin] = useState('')
  const [destination, setDestination] = useState('')
  const [dateFrom, setDateFrom] = useState('')
  const [dateTo, setDateTo] = useState('')
  const [useMonth, setUseMonth] = useState(false)
  const [monthValue, setMonthValue] = useState('')

  const [uiState, setUiState] = useState<UiState>('loading')
  const [errorMsg, setErrorMsg] = useState('')
  const [viewMode, setViewMode] = useState<ViewMode>('home')

  function loadOriginsDestinations() {
    fetchOriginsDestinations()
      .then((data) => {
        setLabels(data.labels || {})
        const codes = [...new Set([...(data.origins || []), ...(data.destinations || [])])].sort()
        const opts: AirportOption[] = codes.map((c) => ({
          code: c,
          label: (data.labels && data.labels[c]) || '',
        }))
        setOriginOptions(opts)
        setDestOptions(opts)
      })
      .catch(() => {})
  }

  function loadDeals() {
    setUiState('loading')
    setErrorMsg('')
    const originParam = parseAirportInput(origin)
    const destParam = parseAirportInput(destination)
    fetchDeals({
      origin: originParam || undefined,
      destination: destParam || undefined,
      limit: 200,
    })
      .then((data) => {
        setAllOpportunities(data)
        if (data.length === 0) setUiState('empty')
        else setUiState('ok')
      })
      .catch((err) => {
        setErrorMsg(err.message || 'Falha ao carregar ofertas.')
        setUiState('error')
      })
  }

  useEffect(() => {
    loadOriginsDestinations()
  }, [])

  useEffect(() => {
    loadDeals()
  }, [])

  function applyDateFilter(list: Offer[]): Offer[] {
    if (!list.length) return list
    let fromTs: number | null = null
    let toTs: number | null = null
    if (useMonth && monthValue) {
      const p = parseMonthInput(monthValue)
      if (p) {
        fromTs = new Date(p.year, p.month, 1).getTime()
        toTs = new Date(p.year, p.month + 1, 0).getTime()
      }
    } else if (dateFrom && dateTo) {
      fromTs = parseDateOnly(dateFrom)
      toTs = parseDateOnly(dateTo)
      if (fromTs != null && toTs != null && fromTs > toTs) {
        const t = fromTs
        fromTs = toTs
        toTs = t
      }
    }
    if (fromTs == null && toTs == null) return list
    return list.filter((o) => {
      const dep = parseDateOnly(o.departure_date)
      if (dep == null) return false
      if (fromTs != null && dep < fromTs) return false
      if (toTs != null && dep > toTs) return false
      return true
    })
  }

  const filteredOpportunities = useMemo(() => {
    let out = allOpportunities
    const originStr = parseAirportInput(origin).trim().toUpperCase()
    const destStr = parseAirportInput(destination).trim().toUpperCase()
    const originExact = originStr.length === 3
    const destExact = destStr.length === 3
    if (originStr) {
      out = out.filter((o) => {
        const oOrig = (o.origin || '').trim().toUpperCase()
        return originExact ? oOrig === originStr : oOrig.includes(originStr)
      })
    }
    if (destStr) {
      out = out.filter((o) => {
        const oDest = (o.destination || '').trim().toUpperCase()
        return destExact ? oDest === destStr : oDest.includes(destStr)
      })
    }
    return applyDateFilter(out)
  }, [allOpportunities, origin, destination, dateFrom, dateTo, useMonth, monthValue])

  const routes = useMemo(() => groupByRoute(filteredOpportunities), [filteredOpportunities])

  const showList =
    viewMode === 'list' ||
    (parseAirportInput(origin).trim().length >= 3 && parseAirportInput(destination).trim().length >= 3)

  const onFilterChange = () => {} // re-render is driven by state

  return (
    <>
      <Header />
      <main className="main">
        <Filters
          origin={origin}
          setOrigin={setOrigin}
          destination={destination}
          setDestination={setDestination}
          dateFrom={dateFrom}
          setDateFrom={setDateFrom}
          dateTo={dateTo}
          setDateTo={setDateTo}
          useMonth={useMonth}
          setUseMonth={setUseMonth}
          monthValue={monthValue}
          setMonthValue={setMonthValue}
          originOptions={originOptions}
          destOptions={destOptions}
          onRefresh={loadDeals}
          onFilterChange={onFilterChange}
        />

        {uiState === 'loading' && (
          <div className="state state-loading">
            <div className="spinner" />
            <p>Carregando ofertas...</p>
          </div>
        )}

        {uiState === 'empty' && (
          <div className="state state-empty">
            <p>Nenhuma oferta encontrada.</p>
            <p className="state-hint">
              Execute o scraper e o motor de oportunidades para popular os dados.
            </p>
          </div>
        )}

        {uiState === 'error' && (
          <div className="state state-error">
            <p>{errorMsg}</p>
          </div>
        )}

        {uiState === 'ok' && routes.length === 0 && (
          <div className="state state-empty">
            <p>Nenhuma oferta encontrada para os filtros selecionados.</p>
          </div>
        )}

        {uiState === 'ok' && routes.length > 0 && !showList && (
          <HighlightCards
            routes={routes}
            labels={labels}
            onVerTodas={() => setViewMode('list')}
          />
        )}

        {uiState === 'ok' && routes.length > 0 && showList && (
          <OpportunityList
            routes={routes}
            labels={labels}
            onVoltarHome={() => setViewMode('home')}
          />
        )}
      </main>

      <footer className="footer">
        <p>
          Construído por <strong>BransStack Labs</strong>
        </p>
      </footer>
    </>
  )
}

export default App
