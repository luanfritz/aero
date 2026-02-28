import json
from typing import Dict

import psycopg2

DB_CONFIG: Dict[str, object] = {
    "host": "localhost",
    "port": 5432,
    "dbname": "postgres",
    "user": "postgres",
    "password": "290535",
}

SOURCE_NAME = "viajanet"
CURRENCY = "BRL"

OPPORTUNITY_MIN_SAMPLES = 3
OPPORTUNITY_MIN_DISCOUNT_PERCENT = 20
OPPORTUNITY_MAX_ALERTS_PER_RUN = 20


def ensure_opportunities_table() -> None:
    conn = psycopg2.connect(**DB_CONFIG)
    try:
        with conn, conn.cursor() as cur:
            cur.execute(
                """
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
                )
                """
            )
    finally:
        conn.close()


def generate_opportunities() -> int:
    ensure_opportunities_table()

    conn = psycopg2.connect(**DB_CONFIG)
    try:
        with conn, conn.cursor() as cur:
            cur.execute(
                """
                WITH route_stats AS (
                    SELECT
                        origin,
                        destination,
                        departure_date,
                        MIN(price) AS best_price,
                        AVG(price)::NUMERIC(10,2) AS avg_price,
                        COUNT(*) AS samples,
                        MIN(payload->>'url') AS sample_url
                    FROM flight_prices_raw
                    WHERE source = %s
                      AND currency = %s
                      AND departure_date >= CURRENT_DATE
                    GROUP BY origin, destination, departure_date
                ), opportunities AS (
                    SELECT
                        origin,
                        destination,
                        departure_date,
                        best_price,
                        avg_price,
                        samples,
                        sample_url,
                        ROUND(((avg_price - best_price) / NULLIF(avg_price, 0)) * 100, 2) AS discount_percent
                    FROM route_stats
                    WHERE samples >= %s
                      AND best_price > 0
                      AND avg_price > 0
                )
                SELECT
                    origin, destination, departure_date, best_price, avg_price,
                    samples, sample_url, discount_percent
                FROM opportunities
                WHERE discount_percent >= %s
                ORDER BY discount_percent DESC
                LIMIT %s
                """,
                (
                    SOURCE_NAME,
                    CURRENCY,
                    OPPORTUNITY_MIN_SAMPLES,
                    OPPORTUNITY_MIN_DISCOUNT_PERCENT,
                    OPPORTUNITY_MAX_ALERTS_PER_RUN,
                ),
            )

            rows = cur.fetchall()
            created = 0

            for row in rows:
                (
                    origin,
                    destination,
                    departure_date,
                    best_price,
                    avg_price,
                    samples,
                    sample_url,
                    discount_percent,
                ) = row

                payload = {
                    "rule": "best_price_vs_avg",
                    "min_samples": OPPORTUNITY_MIN_SAMPLES,
                    "min_discount_percent": OPPORTUNITY_MIN_DISCOUNT_PERCENT,
                }

                cur.execute(
                    """
                    INSERT INTO flight_price_opportunities
                        (origin, destination, departure_date, best_price, avg_price,
                         discount_percent, samples, source, url, payload)
                    VALUES
                        (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
                    ON CONFLICT (origin, destination, departure_date, best_price, source)
                    DO NOTHING
                    """,
                    (
                        origin,
                        destination,
                        departure_date,
                        best_price,
                        int(float(avg_price)),
                        float(discount_percent),
                        samples,
                        SOURCE_NAME,
                        sample_url,
                        json.dumps(payload, ensure_ascii=False),
                    ),
                )

                if cur.rowcount > 0:
                    created += 1
                    print(
                        f"🚨 Oportunidade: {origin}->{destination} {departure_date} | "
                        f"R$ {best_price} (média R$ {int(float(avg_price))}, -{float(discount_percent):.2f}%)"
                    )

            return created
    finally:
        conn.close()


if __name__ == "__main__":
    total = generate_opportunities()
    print(f"🚨 Oportunidades novas geradas: {total}")
