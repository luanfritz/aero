-- Adiciona preferência de data ou mês ao cadastro de alertas.
-- Execute uma vez: psql -U postgres -d postgres -f sql/alert_subscriptions_preferred_date_month.sql

ALTER TABLE alert_subscriptions
  ADD COLUMN IF NOT EXISTS preferred_date DATE,
  ADD COLUMN IF NOT EXISTS preferred_month VARCHAR(7);

COMMENT ON COLUMN alert_subscriptions.preferred_date IS 'Data específica desejada para voos (opcional).';
COMMENT ON COLUMN alert_subscriptions.preferred_month IS 'Mês desejado no formato YYYY-MM (opcional).';
