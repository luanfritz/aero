import { useState, useEffect, useCallback } from 'react'
import { Link } from 'react-router-dom'
import { Header } from '../components/Header'
import {
  getAdminToken,
  setAdminToken,
  clearAdminToken,
  fetchAdminAlertSubscriptions,
  sendAlertsNow,
  deleteAlertSubscription,
  type AlertSubscription,
} from '../api'
import '../App.css'
import './AdminAlertasPage.css'

function formatDate(iso: string | null | undefined): string {
  if (!iso) return '—'
  const d = new Date(iso)
  if (isNaN(d.getTime())) return '—'
  return d.toLocaleString('pt-BR', {
    day: '2-digit',
    month: '2-digit',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}

export function AdminAlertasPage() {
  const [tokenInput, setTokenInput] = useState('')
  const [token, setTokenState] = useState<string | null>(() => getAdminToken())
  const [list, setList] = useState<AlertSubscription[]>([])
  const [loading, setLoading] = useState(false)
  const [sending, setSending] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [message, setMessage] = useState<string | null>(null)
  const [activeOnly, setActiveOnly] = useState(true)

  const loadList = useCallback(() => {
    if (!token) return
    setLoading(true)
    setError(null)
    fetchAdminAlertSubscriptions({ active_only: activeOnly })
      .then(setList)
      .catch((e) => setError(e.message || 'Erro ao carregar'))
      .finally(() => setLoading(false))
  }, [token, activeOnly])

  useEffect(() => {
    if (token) loadList()
    else setList([])
  }, [token, loadList])

  const handleLogin = (e: React.FormEvent) => {
    e.preventDefault()
    const t = tokenInput.trim()
    if (!t) return
    setAdminToken(t)
    setTokenState(t)
    setTokenInput('')
    setError(null)
  }

  const handleLogout = () => {
    clearAdminToken()
    setTokenState(null)
    setList([])
  }

  const handleSendAlerts = () => {
    setSending(true)
    setError(null)
    setMessage(null)
    sendAlertsNow()
      .then((r) => setMessage(r.message || `Enviados ${r.sent} alertas.`))
      .then(loadList)
      .catch((e) => setError(e.message || 'Erro ao enviar'))
      .finally(() => setSending(false))
  }

  const handleDeactivate = (id: number) => {
    deleteAlertSubscription(id)
      .then(loadList)
      .catch((e) => setError(e.message))
  }

  return (
    <>
      <Header />
      <main className="main admin-alertas-page">
        <div className="admin-alertas-card">
          <h1 className="admin-alertas-title">Painel administrativo – Alertas</h1>

          {!token ? (
            <form onSubmit={handleLogin} className="admin-token-form">
              <label htmlFor="admin-token">Token de administrador</label>
              <input
                id="admin-token"
                type="password"
                value={tokenInput}
                onChange={(e) => setTokenInput(e.target.value)}
                placeholder="Digite o token (variável ADMIN_TOKEN)"
                autoComplete="off"
              />
              <button type="submit">Acessar</button>
            </form>
          ) : (
            <>
              <div className="admin-toolbar">
                <label className="admin-check">
                  <input
                    type="checkbox"
                    checked={activeOnly}
                    onChange={(e) => setActiveOnly(e.target.checked)}
                  />
                  Só ativos
                </label>
                <button type="button" className="admin-btn admin-btn-send" onClick={handleSendAlerts} disabled={sending}>
                  {sending ? 'Enviando...' : 'Enviar alertas agora'}
                </button>
                <button type="button" className="admin-btn admin-btn-outline" onClick={handleLogout}>
                  Sair
                </button>
              </div>

              {error && <p className="admin-msg admin-error">{error}</p>}
              {message && <p className="admin-msg admin-success">{message}</p>}

              {loading ? (
                <p className="admin-loading">Carregando...</p>
              ) : (
                <div className="admin-table-wrap">
                  <table className="admin-table">
                    <thead>
                      <tr>
                        <th>Telefone</th>
                        <th>Origem</th>
                        <th>Destino</th>
                        <th>Data/Mês</th>
                        <th>Status</th>
                        <th>Cadastro</th>
                        <th>Ações</th>
                      </tr>
                    </thead>
                    <tbody>
                      {list.length === 0 ? (
                        <tr>
                          <td colSpan={7}>Nenhuma inscrição encontrada.</td>
                        </tr>
                      ) : (
                        list.map((s) => (
                          <tr key={s.id}>
                            <td>{s.phone}</td>
                            <td>{s.origin}</td>
                            <td>{s.destination}</td>
                            <td>{s.preferred_date || s.preferred_month || '—'}</td>
                            <td>{s.active ? 'Ativo' : 'Inativo'}</td>
                            <td>{formatDate(s.created_at)}</td>
                            <td>
                              {s.active && (
                                <button
                                  type="button"
                                  className="admin-btn-link"
                                  onClick={() => handleDeactivate(s.id)}
                                >
                                  Desativar
                                </button>
                              )}
                            </td>
                          </tr>
                        ))
                      )}
                    </tbody>
                  </table>
                </div>
              )}
            </>
          )}

          <p className="admin-back">
            <Link to="/">← Voltar para o site</Link>
          </p>
        </div>
      </main>
    </>
  )
}
