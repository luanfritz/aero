import { useState, useEffect } from 'react'
import { Link } from 'react-router-dom'
import { Header } from '../components/Header'
import { fetchOriginsDestinations, createAlertSubscription } from '../api'
import type { AirportOption } from '../types'
import { parseAirportInput } from '../utils'
import '../App.css'
import './AlertasPage.css'

type PeriodType = 'any' | 'date' | 'month'

export function AlertasPage() {
  const [phone, setPhone] = useState('')
  const [origin, setOrigin] = useState('')
  const [destination, setDestination] = useState('')
  const [periodType, setPeriodType] = useState<PeriodType>('any')
  const [preferredDate, setPreferredDate] = useState('')
  const [preferredMonth, setPreferredMonth] = useState('')
  const [options, setOptions] = useState<AirportOption[]>([])
  const [loading, setLoading] = useState(false)
  const [success, setSuccess] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    fetchOriginsDestinations()
      .then((data) => {
        const codes = [...new Set([...(data.origins || []), ...(data.destinations || [])])].sort()
        setOptions(
          codes.map((c) => ({
            code: c,
            label: (data.labels && data.labels[c]) || '',
          }))
        )
      })
      .catch(() => setOptions([]))
  }, [])

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    setError(null)
    setSuccess(null)
    const originCode = parseAirportInput(origin).trim()
    const destCode = parseAirportInput(destination).trim()
    if (!phone.trim()) {
      setError('Informe o número do WhatsApp.')
      return
    }
    if (!originCode || originCode.length < 2) {
      setError('Selecione a origem.')
      return
    }
    if (!destCode || destCode.length < 2) {
      setError('Selecione o destino.')
      return
    }
    const body: Parameters<typeof createAlertSubscription>[0] = {
      phone: phone.trim(),
      origin: originCode,
      destination: destCode,
    }
    if (periodType === 'date' && preferredDate) body.preferred_date = preferredDate
    if (periodType === 'month' && preferredMonth) body.preferred_month = preferredMonth

    setLoading(true)
    createAlertSubscription(body)
      .then((sub) => {
        setSuccess(
          sub.whatsapp_sent
            ? `Cadastrado! Enviamos uma confirmação no seu WhatsApp para o trecho ${sub.origin} → ${sub.destination}.`
            : `Cadastrado! Você receberá alertas de ofertas para ${sub.origin} → ${sub.destination} no WhatsApp.`
        )
        setOrigin('')
        setDestination('')
      })
      .catch((err) => setError(err.message || 'Falha ao cadastrar.'))
      .finally(() => setLoading(false))
  }

  const displayOption = (o: AirportOption) => (o.label ? `${o.label} (${o.code})` : o.code)

  return (
    <>
      <Header />
      <main className="main alertas-page">
        <div className="alertas-card">
          <h1 className="alertas-title">Alertas por WhatsApp</h1>
          <p className="alertas-desc">
            Cadastre o trecho que você quer monitorar. Enviaremos ofertas de passagens quando
            encontrarmos preços interessantes.
          </p>

          <form onSubmit={handleSubmit} className="alertas-form">
            <div className="alertas-field">
              <label htmlFor="alertas-phone">WhatsApp (com DDD)</label>
              <input
                id="alertas-phone"
                type="tel"
                value={phone}
                onChange={(e) => setPhone(e.target.value)}
                placeholder="Ex: 11 99999-9999 ou 5511999999999"
                autoComplete="tel"
                disabled={loading}
              />
            </div>

            <div className="alertas-field">
              <label htmlFor="alertas-origin">Origem</label>
              <input
                id="alertas-origin"
                type="text"
                value={origin}
                onChange={(e) => setOrigin(e.target.value)}
                placeholder="Cidade ou código (ex: GRU)"
                list="alertas-origin-list"
                disabled={loading}
              />
              <datalist id="alertas-origin-list">
                {options.map((o) => (
                  <option key={o.code} value={displayOption(o)} />
                ))}
              </datalist>
            </div>

            <div className="alertas-field">
              <label htmlFor="alertas-destination">Destino</label>
              <input
                id="alertas-destination"
                type="text"
                value={destination}
                onChange={(e) => setDestination(e.target.value)}
                placeholder="Cidade ou código (ex: CNF)"
                list="alertas-dest-list"
                disabled={loading}
              />
              <datalist id="alertas-dest-list">
                {options.map((o) => (
                  <option key={o.code} value={displayOption(o)} />
                ))}
              </datalist>
            </div>

            <div className="alertas-field">
              <span className="alertas-label">Período de interesse</span>
              <div className="alertas-period-options">
                <label className="alertas-radio">
                  <input
                    type="radio"
                    name="period"
                    checked={periodType === 'any'}
                    onChange={() => setPeriodType('any')}
                    disabled={loading}
                  />
                  Qualquer oferta recente
                </label>
                <label className="alertas-radio">
                  <input
                    type="radio"
                    name="period"
                    checked={periodType === 'date'}
                    onChange={() => setPeriodType('date')}
                    disabled={loading}
                  />
                  Data específica
                </label>
                <label className="alertas-radio">
                  <input
                    type="radio"
                    name="period"
                    checked={periodType === 'month'}
                    onChange={() => setPeriodType('month')}
                    disabled={loading}
                  />
                  Mês específico
                </label>
              </div>
              {periodType === 'date' && (
                <input
                  type="date"
                  className="alertas-date-input"
                  value={preferredDate}
                  onChange={(e) => setPreferredDate(e.target.value)}
                  disabled={loading}
                />
              )}
              {periodType === 'month' && (
                <input
                  type="month"
                  className="alertas-date-input"
                  value={preferredMonth}
                  onChange={(e) => setPreferredMonth(e.target.value)}
                  disabled={loading}
                />
              )}
            </div>

            {error && <p className="alertas-msg alertas-error">{error}</p>}
            {success && <p className="alertas-msg alertas-success">{success}</p>}

            <button type="submit" className="alertas-submit" disabled={loading}>
              {loading ? 'Cadastrando...' : 'Quero receber alertas'}
            </button>
          </form>

          <p className="alertas-back">
            <Link to="/">← Voltar para ofertas</Link>
          </p>
        </div>
      </main>
    </>
  )
}
