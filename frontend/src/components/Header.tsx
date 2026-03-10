import { Link } from 'react-router-dom'
import './Header.css'

export function Header() {
  return (
    <header className="header">
      <div className="header-inner">
        <Link to="/" className="header-brand" aria-label="Voa Lá – início">
          <img
            src="/voa-la-logo.png"
            alt="Voa Lá – Passagens & Promoções Aéreas"
            className="header-logo-img"
          />
        </Link>
        <nav className="header-nav">
          <Link to="/alertas" className="header-link">
            Alertas WhatsApp
          </Link>
        </nav>
      </div>
    </header>
  )
}
