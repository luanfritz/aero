# -*- coding: utf-8 -*-
"""
Envia alertas por WhatsApp aos inscritos quando há ofertas recentes no BD.
Rode após o scraping ou por cron. Requer TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_WHATSAPP_FROM.
Uso: python send_whatsapp_alerts.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import psycopg2
from psycopg2.extras import RealDictCursor

import main
from web_app import _send_whatsapp

DAYS_RECENT = int(os.environ.get("ALERTS_DAYS_RECENT", "3"))


def run():
    if not all([
        os.environ.get("TWILIO_ACCOUNT_SID"),
        os.environ.get("TWILIO_AUTH_TOKEN"),
        os.environ.get("TWILIO_WHATSAPP_FROM"),
    ]):
        print("Configure TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN e TWILIO_WHATSAPP_FROM.")
        return

    conn = psycopg2.connect(**main.DB_CONFIG)
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                SELECT origin, destination, MIN(price) AS min_price, MIN(departure_date) AS sample_date
                FROM flight_prices_raw
                WHERE origin IS NOT NULL AND destination IS NOT NULL
                  AND (scraped_at IS NULL OR scraped_at >= now() - (%s * interval '1 day'))
                GROUP BY origin, destination
            """, (DAYS_RECENT,))
            routes = cur.fetchall()

            cur.execute("""
                SELECT id, phone, origin, destination FROM alert_subscriptions WHERE active = true
            """)
            subs = cur.fetchall()

        by_route = {}
        for r in routes:
            key = (r["origin"], r["destination"])
            by_route[key] = r

        sent = 0
        for s in subs:
            key = (s["origin"], s["destination"])
            offer = by_route.get(key)
            if not offer:
                continue
            msg = (
                f"Voa Lá – Oferta {s['origin']} → {s['destination']}: "
                f"a partir de R$ {offer['min_price']:.0f} (dados recentes). "
                "Confira em voalá."
            )
            if _send_whatsapp(s["phone"], msg):
                sent += 1
                print(f"Enviado para {s['phone']}: {s['origin']}->{s['destination']}")

        print(f"Total enviados: {sent}")
    finally:
        conn.close()


if __name__ == "__main__":
    run()
