-- Garante colunas usadas pelo motor de oportunidades e pela API.
-- Execute se aparecer erro "column return_date does not exist" ao chamar /api/opportunities.
-- Ex.: psql -U postgres -d postgres -f sql/flight_prices_raw_columns.sql

-- Coluna return_date (usada pelos scrapers e pelo opportunities_engine)
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = 'public'
      AND table_name = 'flight_prices_raw'
      AND column_name = 'return_date'
  ) THEN
    ALTER TABLE flight_prices_raw ADD COLUMN return_date DATE;
    RAISE NOTICE 'Coluna flight_prices_raw.return_date criada.';
  END IF;
END $$;
