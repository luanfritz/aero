import { useState, useRef, useEffect } from 'react'
import type { AirportOption } from '../types'
import { MONTH_NAMES_LONG, parseMonthInput } from '../utils'
import './Filters.css'

interface FiltersProps {
  origin: string
  setOrigin: (v: string) => void
  destination: string
  setDestination: (v: string) => void
  dateFrom: string
  setDateFrom: (v: string) => void
  dateTo: string
  setDateTo: (v: string) => void
  useMonth: boolean
  setUseMonth: (v: boolean) => void
  monthValue: string
  setMonthValue: (v: string) => void
  originOptions: AirportOption[]
  destOptions: AirportOption[]
  onRefresh: () => void
  onFilterChange: () => void
}

function AutocompleteInput({
  value,
  onChange,
  options,
  placeholder,
  id,
  ariaLabel,
  onFilterChange,
}: {
  value: string
  onChange: (v: string) => void
  options: AirportOption[]
  placeholder: string
  id: string
  ariaLabel: string
  onFilterChange: () => void
}) {
  const [open, setOpen] = useState(false)
  const [highlight, setHighlight] = useState(-1)
  const ref = useRef<HTMLDivElement>(null)
  const q = value.trim().toLowerCase()
  const filtered = options
    .filter(
      (o) =>
        !q || (o.label || '').toLowerCase().includes(q) || (o.code || '').toLowerCase().includes(q)
    )
    .slice(0, 18)

  const displayText = (o: AirportOption) => (o.label ? `${o.label} (${o.code})` : o.code)

  useEffect(() => {
    function handleClickOutside(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('click', handleClickOutside)
    return () => document.removeEventListener('click', handleClickOutside)
  }, [])

  const onSelect = (o: AirportOption) => {
    onChange(displayText(o))
    setOpen(false)
    setHighlight(-1)
  }

  return (
    <div className="filter-group filter-group-autocomplete" ref={ref}>
      <label htmlFor={id}>{ariaLabel}</label>
      <input
        type="text"
        id={id}
        value={value}
        onChange={(e) => {
          onChange(e.target.value)
          setOpen(true)
          setHighlight(-1)
          onFilterChange?.()
        }}
        onFocus={() => setOpen(true)}
        placeholder={placeholder}
        autoComplete="off"
        aria-label={ariaLabel}
        aria-expanded={open}
        aria-autocomplete="list"
        aria-controls={id + '-list'}
        onKeyDown={(e) => {
          if (e.key === 'Escape') {
            setOpen(false)
            return
          }
          if (!open || filtered.length === 0) return
          if (e.key === 'ArrowDown') {
            e.preventDefault()
            setHighlight((h) => (h < filtered.length - 1 ? h + 1 : h))
          } else if (e.key === 'ArrowUp') {
            e.preventDefault()
            setHighlight((h) => (h > 0 ? h - 1 : 0))
          } else if (e.key === 'Enter' && highlight >= 0 && filtered[highlight]) {
            e.preventDefault()
            onSelect(filtered[highlight])
          }
        }}
      />
      <div
        id={id + '-list'}
        className="autocomplete-dropdown"
        role="listbox"
        aria-label={'Sugestões ' + ariaLabel}
        hidden={!open || filtered.length === 0}
      >
        {filtered.map((o, i) => (
          <div
            key={o.code}
            className={'autocomplete-item' + (i === highlight ? ' active' : '')}
            role="option"
            aria-selected={i === highlight}
            onMouseDown={(e) => {
              e.preventDefault()
              onSelect(o)
            }}
          >
            {o.label || o.code}
            {o.label && o.code && <span className="autocomplete-code"> · {o.code}</span>}
          </div>
        ))}
      </div>
    </div>
  )
}

export function Filters({
  origin,
  setOrigin,
  destination,
  setDestination,
  dateFrom,
  setDateFrom,
  dateTo,
  setDateTo,
  useMonth,
  setUseMonth,
  monthValue,
  setMonthValue,
  originOptions,
  destOptions,
  onRefresh,
  onFilterChange,
}: FiltersProps) {
  const [monthPickerOpen, setMonthPickerOpen] = useState(false)
  const [monthYear, setMonthYear] = useState(() => {
    const p = parseMonthInput(monthValue)
    return p ? p.year : new Date().getFullYear()
  })

  const monthLabel =
    monthValue && parseMonthInput(monthValue)
      ? MONTH_NAMES_LONG[parseMonthInput(monthValue)!.month] + ' ' + parseMonthInput(monthValue)!.year
      : 'Selecione o mês'

  const grid = []
  for (let m = 0; m < 12; m++) {
    const val = `${monthYear}-${String(m + 1).padStart(2, '0')}`
    grid.push(
      <button
        key={val}
        type="button"
        className="month-picker-cell"
        onClick={() => {
          setMonthValue(val)
          setMonthPickerOpen(false)
          onFilterChange()
        }}
      >
        {['Jan', 'Fev', 'Mar', 'Abr', 'Mai', 'Jun', 'Jul', 'Ago', 'Set', 'Out', 'Nov', 'Dez'][m]}
      </button>
    )
  }

  return (
    <section className="filters">
      <AutocompleteInput
        id="filter-origin"
        ariaLabel="Origem"
        value={origin}
        onChange={setOrigin}
        options={originOptions}
        placeholder="Ex: Belo Horizonte ou CNF"
        onFilterChange={onFilterChange}
      />
      <AutocompleteInput
        id="filter-dest"
        ariaLabel="Destino"
        value={destination}
        onChange={setDestination}
        options={destOptions}
        placeholder="Ex: Belo Horizonte ou CNF"
        onFilterChange={onFilterChange}
      />
      <div
        className={'filter-group filter-period-dates' + (useMonth ? ' filter-hidden' : '')}
        id="filter-period-wrap"
      >
        <label>Período</label>
        <div className="filter-period-inputs">
          <input
            type="date"
            aria-label="Data início"
            value={dateFrom}
            onChange={(e) => {
              setDateFrom(e.target.value)
              onFilterChange()
            }}
          />
          <span className="filter-period-sep">até</span>
          <input
            type="date"
            aria-label="Data fim"
            value={dateTo}
            onChange={(e) => {
              setDateTo(e.target.value)
              onFilterChange()
            }}
          />
        </div>
      </div>
      <div
        className={'filter-group filter-month-wrap' + (useMonth ? '' : ' filter-hidden')}
        id="filter-month-wrap"
      >
        <label>Mês das promoções</label>
        <div className="month-picker-wrapper">
          <button
            type="button"
            className="month-picker-trigger"
            onClick={() => setMonthPickerOpen((o) => !o)}
            aria-expanded={monthPickerOpen}
            aria-label="Abrir calendário de meses"
          >
            {monthLabel}
          </button>
          {monthPickerOpen && (
            <div className="month-picker-dropdown">
              <div className="month-picker-header">
                <button
                  type="button"
                  className="month-picker-prev"
                  aria-label="Ano anterior"
                  onClick={() => setMonthYear((y) => y - 1)}
                >
                  ‹
                </button>
                <span className="month-picker-year">{monthYear}</span>
                <button
                  type="button"
                  className="month-picker-next"
                  aria-label="Próximo ano"
                  onClick={() => setMonthYear((y) => y + 1)}
                >
                  ›
                </button>
              </div>
              <div className="month-picker-grid">{grid}</div>
            </div>
          )}
        </div>
      </div>
      <div className="filter-group filter-toggle-row">
        <label className="filter-toggle-label">Escolher por mês</label>
        <button
          type="button"
          className="toggle-btn"
          role="switch"
          aria-checked={useMonth}
          aria-label="Escolher por mês"
          onClick={() => {
            setUseMonth(!useMonth)
            onFilterChange()
          }}
        >
          <span className="toggle-track">
            <span className="toggle-thumb" />
          </span>
        </button>
      </div>
      <button type="button" className="btn-refresh" onClick={onRefresh} title="Atualizar">
        Atualizar
      </button>
    </section>
  )
}
