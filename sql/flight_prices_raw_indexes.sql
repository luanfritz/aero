-- Índices para acelerar /api/opportunities (home e lista).
-- Execute uma vez: psql -U postgres -d postgres -f sql/flight_prices_raw_indexes.sql

-- Filtro por data (scraped_at) na CTE e no JOIN
CREATE INDEX IF NOT EXISTS idx_fpr_scraped_at
  ON flight_prices_raw (scraped_at)
  WHERE scraped_at IS NOT NULL;

-- Agrupamento e ordenação por rota e preço (top rotas por MIN(price))
CREATE INDEX IF NOT EXISTS idx_fpr_origin_dest_price
  ON flight_prices_raw (origin, destination, price ASC);

-- Para consultas com source (fonte específica)
CREATE INDEX IF NOT EXISTS idx_fpr_source_scraped
  ON flight_prices_raw (source, scraped_at)
  WHERE source IS NOT NULL AND source != '';
