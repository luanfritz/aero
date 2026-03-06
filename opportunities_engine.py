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
    departure_date: Optional[Any] = None,
    return_date: Optional[Any] = None,
) -> str:
    """Link para a página de busca da fonte para a rota."""
    if source and source.lower() == "viajanet":
        o = (origin or "").strip().upper()
        d = (destination or "").strip().upper()
        if not o or not d:
            return f"https://www.viajanet.com.br/passagens-aereas/{origin.lower()}/{destination.lower()}/?from=SB&di=1&reSearch=true"
        if not return_date and departure_date:
            try:
                if hasattr(departure_date, "isoformat"):
                    date_str = departure_date.isoformat()
                else:
                    date_str = str(departure_date)[:10]
                if len(date_str) >= 10 and date_str[4] == "-" and date_str[7] == "-":
                    return (
                        f"https://www.viajanet.com.br/shop/flights/results/oneway/"
                        f"{o}/{d}/{date_str}/1/0/0?from=SB&di=1&reSearch=true"
                    )
            except (TypeError, AttributeError, IndexError):
                pass
        return (
            f"https://www.viajanet.com.br/passagens-aereas/"
            f"{origin.lower()}/{destination.lower()}/?from=SB&di=1&reSearch=true"
        )
    if source and source.lower() == "passagens_imperdiveis" and payload and payload.get("promo_url"):
        return str(payload.get("promo_url", ""))
    if source and source.lower() == "passagens_imperdiveis":
        return "https://passagensimperdiveis.com.br/promocoes-recentes/"
    if source and source.lower() == "melhores_destinos":
        if payload:
            if payload.get("ver_voos_url"):
                return str(payload.get("ver_voos_url", ""))
            if payload.get("promo_url"):
                return str(payload.get("promo_url", ""))
        return "https://www.melhoresdestinos.com.br/promocoes-passagens"
    return f"# rota {origin}-{destination} (fonte: {source or '?'})"


def generate_opportunities(
    db_config: Optional[Dict[str, Any]] = None,
    source: Optional[str] = DEFAULT_SOURCE,
    days_lookback: int = DAYS_LOOKBACK,
    max_per_route: int = 5,
    max_routes: Optional[int] = None,
    max_raw_rows: Optional[int] = None,
    silent: bool = False,
) -> List[Dict[str, Any]]:
    """
    Analisa preços em flight_prices_raw e retorna oportunidades (melhores
    preços por rota). source=None considera todas as fontes (viajanet + passagens_imperdiveis).
    Se max_routes for informado, só busca ofertas das N melhores rotas (por preço mínimo).
    Se max_raw_rows for informado (ex.: 3000), limita a leitura da tabela a N linhas recentes — acelera muito a home.
    """
    config = db_config or DEFAULT_DB_CONFIG
    conn = psycopg2.connect(**config)
    opportunities: List[Dict[str, Any]] = []
    all_sources = source is None
    date_filter = "(scraped_at >= now() - (%s * interval '1 day') OR scraped_at IS NULL)"

    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            if max_routes is not None and max_routes > 0:
                # Query limitada: top max_routes rotas. Com max_raw_rows, cap na quantidade de linhas lidas (muito mais rápido).
                if all_sources:
                    if max_raw_rows and max_raw_rows > 0:
                        try:
                            cur.execute(
                                """
                                WITH recent AS (
                                    SELECT source, origin, destination, departure_date, return_date, price, scraped_at, payload
                                    FROM flight_prices_raw
                                    WHERE scraped_at >= now() - (%s * interval '1 day') OR scraped_at IS NULL
                                    ORDER BY scraped_at DESC NULLS LAST
                                    LIMIT %s
                                ),
                                top_routes AS (
                                    SELECT origin, destination FROM recent
                                    GROUP BY origin, destination
                                    ORDER BY MIN(price) ASC
                                    LIMIT %s
                                )
                                SELECT r.source, r.origin, r.destination, r.departure_date, r.return_date,
                                       r.price, r.scraped_at, r.payload
                                FROM recent r
                                INNER JOIN top_routes t ON r.origin = t.origin AND r.destination = t.destination
                                ORDER BY r.source, r.origin, r.destination, r.price ASC, r.departure_date
                                """,
                                (days_lookback, max_raw_rows, max_routes),
                            )
                        except psycopg2.Error:
                            cur.execute(
                                """
                                WITH recent AS (
                                    SELECT source, origin, destination, departure_date, return_date, price,
                                           NULL::timestamptz AS scraped_at, payload
                                    FROM flight_prices_raw
                                    ORDER BY origin, destination, price
                                    LIMIT %s
                                ),
                                top_routes AS (
                                    SELECT origin, destination FROM recent
                                    GROUP BY origin, destination
                                    ORDER BY MIN(price) ASC
                                    LIMIT %s
                                )
                                SELECT r.source, r.origin, r.destination, r.departure_date, r.return_date,
                                       r.price, r.scraped_at, r.payload
                                FROM recent r
                                INNER JOIN top_routes t ON r.origin = t.origin AND r.destination = t.destination
                                ORDER BY r.source, r.origin, r.destination, r.price ASC, r.departure_date
                                """,
                                (max_raw_rows, max_routes),
                            )
                    else:
                        try:
                            cur.execute(
                                """
                                WITH top_routes AS (
                                    SELECT origin, destination
                                    FROM flight_prices_raw
                                    WHERE (""" + date_filter + """)
                                    GROUP BY origin, destination
                                    ORDER BY MIN(price) ASC
                                    LIMIT %s
                                )
                                SELECT r.source, r.origin, r.destination, r.departure_date, r.return_date,
                                       r.price, r.scraped_at, r.payload
                                FROM flight_prices_raw r
                                INNER JOIN top_routes t ON r.origin = t.origin AND r.destination = t.destination
                                WHERE (r.scraped_at >= now() - (%s * interval '1 day') OR r.scraped_at IS NULL)
                                ORDER BY r.source, r.origin, r.destination, r.price ASC, r.departure_date
                                """,
                                (days_lookback, max_routes, days_lookback),
                            )
                        except psycopg2.Error:
                            cur.execute(
                                """
                                WITH top_routes AS (
                                    SELECT origin, destination
                                    FROM flight_prices_raw
                                    GROUP BY origin, destination
                                    ORDER BY MIN(price) ASC
                                    LIMIT %s
                                )
                                SELECT r.source, r.origin, r.destination, r.departure_date, r.return_date,
                                       r.price, NULL::timestamptz AS scraped_at, r.payload
                                FROM flight_prices_raw r
                                INNER JOIN top_routes t ON r.origin = t.origin AND r.destination = t.destination
                                ORDER BY r.source, r.origin, r.destination, r.price ASC, r.departure_date
                                """,
                                (max_routes,),
                            )
                else:
                    try:
                        cur.execute(
                            """
                            WITH top_routes AS (
                                SELECT origin, destination
                                FROM flight_prices_raw
                                WHERE source = %s AND (""" + date_filter + """)
                                GROUP BY origin, destination
                                ORDER BY MIN(price) ASC
                                LIMIT %s
                            )
                            SELECT r.source, r.origin, r.destination, r.departure_date, r.return_date,
                                   r.price, r.scraped_at, r.payload
                            FROM flight_prices_raw r
                            INNER JOIN top_routes t ON r.origin = t.origin AND r.destination = t.destination
                            WHERE r.source = %s AND (r.scraped_at >= now() - (%s * interval '1 day') OR r.scraped_at IS NULL)
                            ORDER BY r.origin, r.destination, r.price ASC, r.departure_date
                            """,
                            (source, days_lookback, max_routes, source, days_lookback),
                        )
                    except psycopg2.Error:
                        cur.execute(
                            """
                            WITH top_routes AS (
                                SELECT origin, destination
                                FROM flight_prices_raw
                                WHERE source = %s
                                GROUP BY origin, destination
                                ORDER BY MIN(price) ASC
                                LIMIT %s
                            )
                            SELECT r.source, r.origin, r.destination, r.departure_date, r.return_date,
                                   r.price, NULL::timestamptz AS scraped_at, r.payload
                            FROM flight_prices_raw r
                            INNER JOIN top_routes t ON r.origin = t.origin AND r.destination = t.destination
                            WHERE r.source = %s
                            ORDER BY r.origin, r.destination, r.price ASC, r.departure_date
                            """,
                            (source, max_routes, source),
                        )
            elif all_sources:
                try:
                    cur.execute(
                        """
                        SELECT
                            source,
                            origin,
                            destination,
                            departure_date,
                            return_date,
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
                            return_date,
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
                            return_date,
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
                            return_date,
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
            if not silent:
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
                is_best = rec["price"] == min_price
                # score para o badge no frontend: 25 = Imbatível, 15-24 = Imperdível, 5-14 = Ótima, <5 = Boa/Oferta
                score = 25 if is_best else 10
                opportunities.append({
                    "source": src,
                    "origin": origin,
                    "destination": destination,
                    "departure_date": rec.get("departure_date"),
                    "return_date": rec.get("return_date"),
                    "price": rec["price"],
                    "scraped_at": rec.get("scraped_at"),
                    "is_best_for_route": is_best,
                    "score": score,
                    "url": search_url,
                })

        # Saída em texto (agrupada por fonte quando all_sources)
        if not silent:
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