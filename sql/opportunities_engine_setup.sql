-- Setup do motor de oportunidades
-- Execute este script no seu PostgreSQL antes de rodar o opportunities_engine.py em produção.

CREATE TABLE IF NOT EXISTS flight_price_opportunities (
    id BIGSERIAL PRIMARY KEY,
    origin VARCHAR(3) NOT NULL,
    destination VARCHAR(3) NOT NULL,
    departure_date DATE NOT NULL,
    best_price INTEGER NOT NULL,
    avg_price INTEGER NOT NULL,
    discount_percent NUMERIC(5,2) NOT NULL,
    samples INTEGER NOT NULL,
    source TEXT NOT NULL,
    url TEXT,
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    UNIQUE (origin, destination, departure_date, best_price, source)
);

-- Índices recomendados para consultas e deduplicação/alertas
CREATE INDEX IF NOT EXISTS idx_flight_price_opportunities_route_date
    ON flight_price_opportunities (origin, destination, departure_date);

CREATE INDEX IF NOT EXISTS idx_flight_price_opportunities_created_at
    ON flight_price_opportunities (created_at DESC);
