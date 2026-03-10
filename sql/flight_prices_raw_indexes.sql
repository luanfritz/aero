-- Índices para acelerar /api/opportunities e /api/origins_destinations.
-- Execute uma vez: psql -U postgres -d postgres -f sql/flight_prices_raw_indexes.sql

-- Filtro por data (scraped_at) na CTE e no JOIN
CREATE INDEX IF NOT EXISTS idx_fpr_scraped_at
  ON flight_prices_raw (scraped_at)
  WHERE scraped_at IS NOT NULL;

-- Agrupamento e ordenação por rota e preço (top rotas por MIN(price))
CREATE INDEX IF NOT EXISTS idx_fpr_origin_dest_price
  ON flight_prices_raw (origin, destination, price ASC);

-- DISTINCT origin / destination (origins_destinations)
CREATE INDEX IF NOT EXISTS idx_fpr_origin
  ON flight_prices_raw (origin)
  WHERE origin IS NOT NULL AND origin != '';
CREATE INDEX IF NOT EXISTS idx_fpr_destination
  ON flight_prices_raw (destination)
  WHERE destination IS NOT NULL AND destination != '';

-- LATERAL lookup em _get_deals (origin, destination, dates, price, source)
CREATE INDEX IF NOT EXISTS idx_fpr_deals_lookup
  ON flight_prices_raw (origin, destination, departure_date, return_date, price, source);

-- Para consultas com source (fonte específica)
CREATE INDEX IF NOT EXISTS idx_fpr_source_scraped
  ON flight_prices_raw (source, scraped_at)
  WHERE source IS NOT NULL AND source != '';
