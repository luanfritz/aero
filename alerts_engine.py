# -*- coding: utf-8 -*-
"""
Motor de alertas: envia WhatsApp aos inscritos.
- send_alerts_for_new_offer: chamado quando um novo voo é cadastrado (scraper).
- run_send_alerts: envia para todos os inscritos cujas preferências batem com ofertas recentes (cron/admin).
"""
from datetime import date
from typing import Any, Callable, Dict, Optional

import psycopg2
from psycopg2.extras import RealDictCursor

import whatsapp_sender


def send_alerts_for_new_offer(
    db_config: Dict[str, Any],
    origin: str,
    destination: str,
    departure_date: date,
    return_date: Optional[date],
    price_brl: int,
) -> int:
    """
    Encontra inscrições ativas para (origin, destination) cuja preferência
    (data ou mês) bate com departure_date e envia um WhatsApp por inscrição.
    Retorna quantidade de mensagens enviadas.
    """
    conn = psycopg2.connect(**db_config)
    sent = 0
    try:
        dep_ym = departure_date.strftime("%Y-%m") if departure_date else None
        dep_str = departure_date.isoformat() if departure_date else None
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                SELECT id, phone, origin, destination, preferred_date, preferred_month
                FROM alert_subscriptions
                WHERE active = true
                  AND origin = %s AND destination = %s
            """, (origin, destination))
            rows = cur.fetchall()
        for r in rows:
            pref_date = r.get("preferred_date")
            pref_month = r.get("preferred_month")
            if pref_date is not None and departure_date != pref_date:
                continue
            if pref_month is not None and dep_ym != pref_month:
                continue
            msg = (
                f"Voa Lá – Novo voo {origin} → {destination}: "
                f"ida {dep_str or '?'} a partir de R$ {price_brl:.0f}. Confira no site."
            )
            if whatsapp_sender.send_whatsapp(r["phone"], msg):
                sent += 1
        return sent
    finally:
        conn.close()


def run_send_alerts(
    db_config: Dict[str, Any],
    days_recent: int = 3,
    send_func: Optional[Callable[[str, str], bool]] = None,
) -> int:
    """
    Para cada inscrição ativa, verifica se há ofertas em flight_prices_raw
    que batem com a preferência (data/mês ou qualquer oferta recente) e envia um alerta.
    send_func(phone, body) -> bool; se None, usa whatsapp_sender.send_whatsapp.
    """
    send = send_func or whatsapp_sender.send_whatsapp
    conn = psycopg2.connect(**db_config)
    sent = 0
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                SELECT id, phone, origin, destination, preferred_date, preferred_month
                FROM alert_subscriptions
                WHERE active = true
            """)
            subs = cur.fetchall()
            for s in subs:
                o, d = s["origin"], s["destination"]
                pref_date = s.get("preferred_date")
                pref_month = s.get("preferred_month")
                if pref_date is not None:
                    cur.execute("""
                        SELECT MIN(price) AS min_price, MIN(departure_date) AS dep
                        FROM flight_prices_raw
                        WHERE origin = %s AND destination = %s AND departure_date = %s
                          AND (scraped_at IS NULL OR scraped_at >= now() - (%s * interval '1 day'))
                    """, (o, d, pref_date, days_recent))
                elif pref_month is not None:
                    cur.execute("""
                        SELECT MIN(price) AS min_price, MIN(departure_date) AS dep
                        FROM flight_prices_raw
                        WHERE origin = %s AND destination = %s
                          AND to_char(departure_date, 'YYYY-MM') = %s
                          AND (scraped_at IS NULL OR scraped_at >= now() - (%s * interval '1 day'))
                    """, (o, d, pref_month, days_recent))
                else:
                    cur.execute("""
                        SELECT MIN(price) AS min_price, MIN(departure_date) AS dep
                        FROM flight_prices_raw
                        WHERE origin = %s AND destination = %s
                          AND (scraped_at IS NULL OR scraped_at >= now() - (%s * interval '1 day'))
                    """, (o, d, days_recent))
                row = cur.fetchone()
                if not row or row["min_price"] is None:
                    continue
                dep_str = row["dep"].strftime("%d/%m/%Y") if row.get("dep") else "?"
                msg = (
                    f"Voa Lá – Oferta {o} → {d}: "
                    f"a partir de R$ {float(row['min_price']):.0f} (ida {dep_str}). Confira no site."
                )
                if send(s["phone"], msg):
                    sent += 1
        return sent
    finally:
        conn.close()
