import './Header.css'

export function Header() {
  return (
    <header className="header">
      <div className="header-inner">
        <a href="/" className="header-brand" aria-label="Voa Lá – início">
          <img
            src="/voa-la-logo.png"
            alt="Voa Lá – Passagens & Promoções Aéreas"
            className="header-logo-img"
          />
        </a>
      </div>
    </header>
  )
}
