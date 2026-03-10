# -*- coding: utf-8 -*-
"""Envio de WhatsApp (Evolution API ou Twilio). Sem dependência de Flask/main."""
import json
import os
import sys


def send_whatsapp(to_phone: str, body: str) -> bool:
    """Tenta Evolution API primeiro; se não configurada, usa Twilio."""
    if _send_evolution(to_phone, body):
        return True
    return _send_twilio(to_phone, body)


def _send_evolution(to_phone: str, body: str) -> bool:
    base = (os.environ.get("EVOLUTION_API_URL") or "").rstrip("/")
    instance = (os.environ.get("EVOLUTION_INSTANCE") or "").strip()
    if not base or not instance:
        return False
    phone = "".join(c for c in to_phone if c.isdigit())
    if not phone.startswith("55"):
        phone = "55" + phone
    try:
        import urllib.request
        url = f"{base}/message/sendText/{instance}"
        data = json.dumps({"number": phone, "text": body}).encode("utf-8")
        req = urllib.request.Request(url, data=data, method="POST")
        req.add_header("Content-Type", "application/json")
        api_key = os.environ.get("EVOLUTION_API_KEY")
        if api_key:
            req.add_header("apikey", api_key)
        with urllib.request.urlopen(req, timeout=15) as resp:
            return 200 <= resp.status < 300
    except Exception as e:
        print(">>> [whatsapp_sender] Evolution error:", e, file=sys.stderr)
        return False


def _send_twilio(to_phone: str, body: str) -> bool:
    if not all([
        os.environ.get("TWILIO_ACCOUNT_SID"),
        os.environ.get("TWILIO_AUTH_TOKEN"),
        os.environ.get("TWILIO_WHATSAPP_FROM"),
    ]):
        return False
    try:
        from twilio.rest import Client
        client = Client(
            os.environ["TWILIO_ACCOUNT_SID"],
            os.environ["TWILIO_AUTH_TOKEN"],
        )
        to = to_phone if to_phone.startswith("whatsapp:") else f"whatsapp:+{to_phone.lstrip('+')}"
        client.messages.create(
            body=body,
            from_=os.environ["TWILIO_WHATSAPP_FROM"],
            to=to,
        )
        return True
    except Exception as e:
        print(">>> [whatsapp_sender] Twilio error:", e, file=sys.stderr)
        return False
