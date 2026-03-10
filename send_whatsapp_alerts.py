# -*- coding: utf-8 -*-
"""
Envia alertas por WhatsApp aos inscritos (respeitando data/mês preferido).
Rode após o scraping ou por cron.
Requer Evolution API ou Twilio. Uso: python send_whatsapp_alerts.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import main
import whatsapp_sender
from alerts_engine import run_send_alerts

DAYS_RECENT = int(os.environ.get("ALERTS_DAYS_RECENT", "3"))


def run():
    if not (os.environ.get("EVOLUTION_API_URL") and os.environ.get("EVOLUTION_INSTANCE")) and not all([
        os.environ.get("TWILIO_ACCOUNT_SID"),
        os.environ.get("TWILIO_AUTH_TOKEN"),
        os.environ.get("TWILIO_WHATSAPP_FROM"),
    ]):
        print("Configure Evolution API ou Twilio.")
        return
    sent = run_send_alerts(main.DB_CONFIG, days_recent=DAYS_RECENT, send_func=whatsapp_sender.send_whatsapp)
    print(f"Total enviados: {sent}")


if __name__ == "__main__":
    run()
