# -*- coding: utf-8 -*-
"""
Motor de ranking de ofertas: popula a tabela `deals` a partir de flight_prices.

Para cada oferta recente, calcula:
- baseline_avg_30d / baseline_min_30d: média e mínimo da rota (source, origin, destination) nos últimos 30 dias
- drop_pct: (avg - price) / avg * 100 (quanto abaixo da média)
- score: usado para ranquear (maior = melhor oferta)

deal_day = data do dia (America/Sao_Paulo). O índice único evita duplicar a mesma oferta no mesmo dia.
"""
import sys
import time
from datetime import date
from decimal import Decimal
from typing import Any, Dict, List, Optional

import json
import psycopg2
from psycopg2.extras import RealDictCursor, Json

# Compatível com main.DB_CONFIG
DEFAULT_DB_CONFIG = {
    "host": "localhost",
    "port": 5432,
    "dbname": "postgres",
    "user": "postgres",
    "password": "290535",
}

BASELINE_DAYS = 30
# Só entram no ranking ofertas capturadas nas últimas N horas
CANDIDATES_HOURS = 54
TIMEZONE = "America/Sao_Paulo"


def _get_baselines(conn, baseline_days: int = BASELINE_DAYS) -> Dict[tuple, Dict[str, Any]]:
    """Por (source, origin, destination) retorna avg(price) e min(price) nos últimos baseline_days dias."""
    sql = """
    WITH recent AS (
        SELECT fp.source, r.origin, r.destination, fp.price_brl AS price
        FROM flight_prices fp
        JOIN routes r ON r.id = fp.route_id
        WHERE fp.scraped_at >= now() - (%s * interval '1 day')
           OR fp.scraped_at IS NULL
    )
    SELECT
        source,
        origin,
        destination,
        AVG(price)::numeric AS avg_price,
        MIN(price)::integer AS min_price
    FROM recent
    GROUP BY source, origin, destination
    """
    out = {}
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(sql, (baseline_days,))
        for r in cur.fetchall():
            key = (r["source"], r["origin"], r["destination"])
            out[key] = {"avg": r["avg_price"], "min": r["min_price"]}
    return out


def _get_candidates(conn, candidates_hours: int = CANDIDATES_HOURS) -> List[Dict[str, Any]]:
    """Ofertas capturadas nas últimas N horas que entram no ranking do dia."""
    sql = """
    SELECT
        fp.source,
        r.origin,
        r.destination,
        fp.departure_date,
        fp.return_date,
        (fp.price_brl)::integer AS price,
        NULL::jsonb AS payload
    FROM flight_prices fp
    JOIN routes r ON r.id = fp.route_id
    WHERE fp.scraped_at >= now() - (%s * interval '1 hour')
      AND fp.price_brl > 0
    ORDER BY fp.source, r.origin, r.destination, fp.departure_date, fp.price_brl
    """
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(sql, (candidates_hours,))
        return [dict(r) for r in cur.fetchall()]


def _compute_score(price: int, baseline_avg: Optional[Decimal], baseline_min: Optional[int]) -> tuple:
    """
    drop_pct = (avg - price) / avg * 100 (percentual abaixo da média).
    score = drop_pct (maior = melhor). Se não tiver baseline, score = 0 e drop_pct = None.
    """
    if baseline_avg is None or baseline_avg <= 0:
        return None, Decimal("0")
    avg = float(baseline_avg)
    drop_pct = (avg - price) / avg * 100
    return round(Decimal(str(drop_pct)), 2), round(Decimal(str(drop_pct)), 2)


def refresh_deals_today(
    db_config: Optional[Dict[str, Any]] = None,
    baseline_days: int = BASELINE_DAYS,
    candidates_hours: int = CANDIDATES_HOURS,
    silent: bool = False,
) -> int:
    """
    Popula/atualiza a tabela deals para o dia atual (deal_day em America/Sao_Paulo).
    Só considera ofertas capturadas nas últimas candidates_hours horas.
    Retorna quantidade de linhas inseridas ou atualizadas.
    """
    config = db_config or DEFAULT_DB_CONFIG
    conn = psycopg2.connect(**config)
    inserted = 0

    try:
        baselines = _get_baselines(conn, baseline_days)
        candidates = _get_candidates(conn, candidates_hours)

        if not silent:
            print(f">>> Deals: {len(candidates)} candidatos (últimas {candidates_hours}h), {len(baselines)} rotas com baseline (30d)")

        with conn.cursor() as cur:
            cur.execute(
                "SELECT (NOW() AT TIME ZONE %s)::date AS today",
                (TIMEZONE,),
            )
            deal_day = cur.fetchone()[0]

        for c in candidates:
            key = (c["source"], c["origin"], c["destination"])
            bl = baselines.get(key)
            baseline_avg = bl["avg"] if bl else None
            baseline_min = bl["min"] if bl else None
            drop_pct, score = _compute_score(c["price"], baseline_avg, baseline_min)

            payload = c.get("payload")
            if isinstance(payload, str):
                try:
                    payload = json.loads(payload) if payload else None
                except Exception:
                    payload = None
            airline = None
            if isinstance(payload, dict):
                airline = payload.get("airline") or payload.get("airline_src")

            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO deals (
                        source, origin, destination,
                        departure_date, return_date, airline, price, currency,
                        baseline_avg_30d, baseline_min_30d, drop_pct, score,
                        flight_price_id, payload, deal_day
                    ) VALUES (
                        %s, %s, %s,
                        %s, %s, %s, %s, COALESCE(%s, 'BRL'),
                        %s, %s, %s, %s,
                        NULL, %s::jsonb, %s
                    )
                    ON CONFLICT (source, origin, destination, departure_date, return_date, price, deal_day)
                    DO UPDATE SET
                        baseline_avg_30d = EXCLUDED.baseline_avg_30d,
                        baseline_min_30d = EXCLUDED.baseline_min_30d,
                        drop_pct = EXCLUDED.drop_pct,
                        score = EXCLUDED.score,
                        payload = EXCLUDED.payload,
                        airline = EXCLUDED.airline
                    """,
                    (
                        c["source"],
                        c["origin"],
                        c["destination"],
                        c["departure_date"],
                        c.get("return_date"),
                        airline,
                        c["price"],
                        c.get("currency"),
                        baseline_avg,
                        baseline_min,
                        drop_pct,
                        score,
                        Json(payload) if payload else None,
                        deal_day,
                    ),
                )
                inserted += cur.rowcount

        conn.commit()
        if not silent:
            print(f">>> Deals: {inserted} oferta(s) inseridas/atualizadas para deal_day={deal_day}")
    finally:
        conn.close()

    return inserted


if __name__ == "__main__":
    silent = "--silent" in sys.argv
    run_once = "--once" in sys.argv
    interval_minutes = 60
    if "--interval" in sys.argv:
        try:
            i = sys.argv.index("--interval")
            if i + 1 < len(sys.argv):
                interval_minutes = max(1, int(sys.argv[i + 1]))
        except (ValueError, IndexError):
            pass

    if run_once:
        refresh_deals_today(silent=silent)
        sys.exit(0)

    print("======================================")
    print(">>> Deals engine (serviço)")
    print(">>> Candidatos: voos das últimas", CANDIDATES_HOURS, "horas")
    print(">>> Reexecutando a cada", interval_minutes, "minuto(s). Ctrl+C para parar.")
    print(">>> Use --once para rodar uma vez e sair.")
    print("======================================\n")

    try:
        while True:
            refresh_deals_today(silent=silent)
            print(f"\n>>> Próxima execução em {interval_minutes} minuto(s)...")
            time.sleep(interval_minutes * 60)
    except KeyboardInterrupt:
        print("\n>>> Deals engine encerrado.")
