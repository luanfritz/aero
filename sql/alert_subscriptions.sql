-- Cadastro de alertas por WhatsApp (trecho: origem -> destino).
-- Execute uma vez: psql -U postgres -d postgres -f sql/alert_subscriptions.sql

CREATE TABLE IF NOT EXISTS alert_subscriptions (
  id SERIAL PRIMARY KEY,
  phone VARCHAR(20) NOT NULL,
  origin VARCHAR(10) NOT NULL,
  destination VARCHAR(10) NOT NULL,
  preferred_date DATE,
  preferred_month VARCHAR(7),
  active BOOLEAN NOT NULL DEFAULT true,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT alert_subscriptions_phone_origin_dest_unique UNIQUE (phone, origin, destination)
);

CREATE INDEX IF NOT EXISTS idx_alert_subscriptions_phone ON alert_subscriptions (phone);
CREATE INDEX IF NOT EXISTS idx_alert_subscriptions_route ON alert_subscriptions (origin, destination) WHERE active = true;
CREATE INDEX IF NOT EXISTS idx_alert_subscriptions_active ON alert_subscriptions (active) WHERE active = true;

COMMENT ON TABLE alert_subscriptions IS 'Inscrições para receber alertas de preço no WhatsApp por trecho (origem/destino).';
