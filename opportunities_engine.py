# -*- coding: utf-8 -*-
"""
Motor de análise de oportunidades: analisa flight_prices_raw e destaca
melhores preços por rota (ex.: mínimo nos últimos dias, comparação com média).
Considera todas as fontes (viajanet, passagens_imperdiveis) quando source=None.
"""
import json
from datetime import date
from typing import Any, Dict, List, Optional, Tuple

import psycopg2
from psycopg2.extras import RealDictCursor


# Usado quando o módulo é chamado standalone; senão main.py passa o config
DEFAULT_DB_CONFIG = {
    "host": "localhost",
    "port": 5432,
    "dbname": "postgres",
    "user": "postgres",
    "password": "290535",
}

DEFAULT_SOURCE = "viajanet"
DAYS_LOOKBACK = 7  # janela de análise em dias (usa scraped_at se existir)


def _format_flight_date(d: Any) -> str:
    """Formata data do voo para exibição (ex.: 15/03/2025)."""
    if d is None:
        return "—"
    if isinstance(d, date):
        return d.strftime("%d/%m/%Y")
    return str(d)


def build_search_url(
    origin: str,
    destination: str,
    source: str = DEFAULT_SOURCE,
    payload: Optional[Dict[str, Any]] = None,
) -> str:
    """Link para a página de busca da fonte para a rota."""
    if source and source.lower() == "viajanet":
        return (
            f"https://www.viajanet.com.br/passagens-aereas/"
            f"{origin.lower()}/{destination.lower()}/?from=SB&di=1&reSearch=true"
        )
    if source and source.lower() == "passagens_imperdiveis" and payload and payload.get("promo_url"):
        return str(payload.get("promo_url", ""))
    if source and source.lower() == "passagens_imperdiveis":
        return "https://passagensimperdiveis.com.br/promocoes-recentes/"
    return f"# rota {origin}-{destination} (fonte: {source or '?'})"


def generate_opportunities(
    db_config: Optional[Dict[str, Any]] = None,
    source: Optional[str] = DEFAULT_SOURCE,
    days_lookback: int = DAYS_LOOKBACK,
    max_per_route: int = 5,
) -> List[Dict[str, Any]]:
    """
    Analisa preços em flight_prices_raw e retorna oportunidades (melhores
    preços por rota). source=None considera todas as fontes (viajanet + passagens_imperdiveis).
    """
    config = db_config or DEFAULT_DB_CONFIG
    conn = psycopg2.connect(**config)
    opportunities: List[Dict[str, Any]] = []
    all_sources = source is None

    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            if all_sources:
                try:
                    cur.execute(
                        """
                        SELECT
                            source,
                            origin,
                            destination,
                            departure_date,
                            price,
                            scraped_at,
                            payload
                        FROM flight_prices_raw
                        WHERE scraped_at >= now() - (%s * interval '1 day')
                           OR scraped_at IS NULL
                        ORDER BY source, origin, destination, price ASC
                        """,
                        (days_lookback,),
                    )
                except psycopg2.Error:
                    cur.execute(
                        """
                        SELECT
                            source,
                            origin,
                            destination,
                            departure_date,
                            price,
                            NULL::timestamptz AS scraped_at,
                            payload
                        FROM flight_prices_raw
                        ORDER BY source, origin, destination, price ASC
                        """
                    )
            else:
                try:
                    cur.execute(
                        """
                        SELECT
                            source,
                            origin,
                            destination,
                            departure_date,
                            price,
                            scraped_at,
                            payload
                        FROM flight_prices_raw
                        WHERE source = %s
                          AND (scraped_at >= now() - (%s * interval '1 day') OR scraped_at IS NULL)
                        ORDER BY origin, destination, price ASC
                        """,
                        (source, days_lookback),
                    )
                except psycopg2.Error:
                    cur.execute(
                        """
                        SELECT
                            source,
                            origin,
                            destination,
                            departure_date,
                            price,
                            NULL::timestamptz AS scraped_at,
                            payload
                        FROM flight_prices_raw
                        WHERE source = %s
                        ORDER BY origin, destination, price ASC
                        """,
                        (source,),
                    )
            rows = cur.fetchall()

        if not rows:
            print("📭 Nenhum dado em flight_prices_raw na janela configurada.")
            return opportunities

        # Normalizar payload (pode vir como dict ou str)
        for r in rows:
            if isinstance(r.get("payload"), str):
                try:
                    r["payload"] = json.loads(r["payload"]) if r["payload"] else {}
                except Exception:
                    r["payload"] = {}

        # Agrupar por (source, origin, destination) quando all_sources, senão por (origin, destination)
        if all_sources:
            by_group: Dict[Tuple[str, str, str], List[Dict]] = {}
            for r in rows:
                key = (r["source"] or "", r["origin"], r["destination"])
                by_group.setdefault(key, []).append(dict(r))
        else:
            by_group = {}
            for r in rows:
                key = (source or "", r["origin"], r["destination"])
                by_group.setdefault(key, []).append(dict(r))

        for (src, origin, destination), recs in sorted(by_group.items()):
            recs_sorted = sorted(recs, key=lambda x: (x["price"], str(x.get("departure_date") or "")))[:max_per_route]
            min_price = recs_sorted[0]["price"] if recs_sorted else None
            payload = (recs_sorted[0].get("payload") or {}) if recs_sorted else {}
            search_url = build_search_url(origin, destination, src, payload)
            for rec in recs_sorted:
                opportunities.append({
                    "source": src,
                    "origin": origin,
                    "destination": destination,
                    "departure_date": rec.get("departure_date"),
                    "price": rec["price"],
                    "scraped_at": rec.get("scraped_at"),
                    "is_best_for_route": rec["price"] == min_price,
                    "url": search_url,
                })

        # Saída em texto (agrupada por fonte quando all_sources)
        print("\n" + "=" * 60)
        print("📊 MOTOR DE OPORTUNIDADES (melhores preços por rota)")
        print("=" * 60)
        if all_sources:
            sources_seen = sorted(set(k[0] for k in by_group.keys() if k[0]))
            print(f"Fontes: {', '.join(sources_seen) or '—'}  |  Janela: últimos {days_lookback} dias  |  Rotas: {len(by_group)}")
        else:
            print(f"Fonte: {source}  |  Janela: últimos {days_lookback} dias  |  Rotas: {len(by_group)}")
        print("-" * 60)

        for (src, origin, destination), recs in sorted(by_group.items()):
            recs_sorted = sorted(recs, key=lambda x: (x["price"], str(x.get("departure_date") or "")))[:max_per_route]
            min_p = recs_sorted[0]["price"]
            payload = (recs_sorted[0].get("payload") or {}) if recs_sorted else {}
            search_url = build_search_url(origin, destination, src, payload)
            if all_sources and src:
                print(f"\n  [{src}]")
            print(f"\n{origin} → {destination}  (mínimo: R$ {min_p:,})".replace(",", "."))
            print(f"   🔗 {search_url}")
            for rec in recs_sorted:
                dep = rec.get("departure_date")
                dep_str = _format_flight_date(dep)
                best = " ⭐" if rec["price"] == min_p else ""
                print(f"   Data do voo: {dep_str}  →  R$ {rec['price']:,}{best}".replace(",", "."))

        print("\n" + "=" * 60)
        return opportunities

    finally:
        conn.close()


if __name__ == "__main__":
    generate_opportunities(source=None)  # todas as fontes
