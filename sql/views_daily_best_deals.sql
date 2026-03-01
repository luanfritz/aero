-- =============================================================================
-- Views para uso no dia a dia: melhor oferta por rota+datas e ranking.
-- Executar uma vez: psql -U postgres -d postgres -f sql/views_daily_best_deals.sql
-- =============================================================================

-- 1) daily_best_deals
-- Consolida entre fontes e mantém só o melhor (menor preço; desempate por score)
-- por rota + datas (origin, destination, departure_date, return_date, deal_day).
DROP VIEW IF EXISTS daily_best_deals_ranked;
DROP VIEW IF EXISTS daily_best_deals;

CREATE VIEW daily_best_deals AS
SELECT
  source,
  origin,
  destination,
  departure_date,
  return_date,
  airline,
  price,
  currency,
  baseline_avg_30d,
  baseline_min_30d,
  drop_pct,
  score,
  payload,
  deal_day
FROM (
  SELECT
    source, origin, destination, departure_date, return_date, airline, price, currency,
    baseline_avg_30d, baseline_min_30d, drop_pct, score, payload, deal_day,
    ROW_NUMBER() OVER (
      PARTITION BY origin, destination, departure_date, return_date, deal_day
      ORDER BY price ASC, score DESC NULLS LAST
    ) AS rn
  FROM deals
) t
WHERE rn = 1;

-- 2) daily_best_deals_ranked
-- Mesmos dados + ranking global e ranking por rota (para exibição ordenada).
CREATE VIEW daily_best_deals_ranked AS
SELECT
  source,
  origin,
  destination,
  departure_date,
  return_date,
  airline,
  price,
  currency,
  baseline_avg_30d,
  baseline_min_30d,
  drop_pct,
  score,
  payload,
  deal_day,
  ROW_NUMBER() OVER (ORDER BY score DESC NULLS LAST, price ASC) AS global_rank,
  ROW_NUMBER() OVER (
    PARTITION BY origin, destination
    ORDER BY score DESC NULLS LAST, price ASC
  ) AS route_rank
FROM daily_best_deals;
