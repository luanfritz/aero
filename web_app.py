# -*- coding: utf-8 -*-
"""
API e frontend para consulta de voos e promoções (flight_prices_raw).
Frontend: Vite + React (frontend/). Build em frontend/dist.
Rode: python web_app.py  ->  http://localhost:5000
"""
import json
import os
import sys
import time
from datetime import date, datetime
from typing import Optional

# Garante que o diretório do projeto está no path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from flask import Flask, jsonify, request, send_from_directory, Response
from flask_cors import CORS
import psycopg2
from psycopg2.extras import RealDictCursor

import main
from opportunities_engine import generate_opportunities, build_search_url

# Cache em memória para reduzir carga no BD (TTL em segundos)
_CACHE_ORIGINS_TTL = int(os.environ.get("CACHE_ORIGINS_TTL", "120"))  # 2 min
_CACHE_HOME_OPPORTUNITIES_TTL = int(os.environ.get("CACHE_HOME_OPPORTUNITIES_TTL", "90"))  # 1.5 min
_cache_origins = None
_cache_origins_ts = 0
_cache_home_opportunities = None
_cache_home_opportunities_ts = 0

# Frontend único: build Vite + React em frontend/dist
_static_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "frontend", "dist")
_HAS_BUILD = os.path.isdir(_static_dir) and os.path.isfile(os.path.join(_static_dir, "index.html"))
app = Flask(__name__, static_folder=_static_dir, static_url_path="")
CORS(app)

_HTML_BUILD_FIRST = """<!DOCTYPE html>
<html lang="pt-BR"><head><meta charset="UTF-8"/><meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>ScrapeAero – Build do frontend</title></head>
<body style="font-family:sans-serif;max-width:520px;margin:3rem auto;padding:1rem;background:#0a0e14;color:#e6edf3;">
<h1>Frontend não encontrado</h1>
<p>O frontend é Vite + React. Gere o build e reinicie:</p>
<pre style="background:#1e293b;padding:1rem;border-radius:8px;overflow:auto;">cd frontend
npm install
npm run build</pre>
<p>Depois acesse <a href="/" style="color:#38bdf8;">/</a> novamente. A <a href="/api/deals" style="color:#38bdf8;">API</a> já está disponível.</p>
</body></html>"""


def _serialize(obj):
    if isinstance(obj, (date, datetime)):
        return obj.isoformat()
    if isinstance(obj, dict):
        return {k: _serialize(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_serialize(x) for x in obj]
    if hasattr(obj, "__float__"):  # Decimal e similares
        return float(obj)
    return obj


def _get_origins_destinations():
    """Lista distintas origens e destinos em flight_prices_raw e labels da tabela airports."""
    conn = psycopg2.connect(**main.DB_CONFIG)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT DISTINCT origin FROM flight_prices_raw WHERE origin IS NOT NULL AND origin != '' ORDER BY 1"
            )
            origins = [r[0] for r in cur.fetchall()]
            cur.execute(
                "SELECT DISTINCT destination FROM flight_prices_raw WHERE destination IS NOT NULL AND destination != '' ORDER BY 1"
            )
            destinations = [r[0] for r in cur.fetchall()]
            codes = list(set(origins) | set(destinations))
            labels = {}
            if codes:
                try:
                    placeholders = ",".join(["%s"] * len(codes))
                    cur.execute(
                        "SELECT iata_code, COALESCE(NULLIF(TRIM(city), ''), name) FROM airports WHERE iata_code IN (%s)" % placeholders,
                        codes,
                    )
                    for row in cur.fetchall():
                        if row[1]:
                            labels[row[0]] = row[1]
                except Exception:
                    pass
        return {"origins": origins, "destinations": destinations, "labels": labels}
    finally:
        conn.close()


def _get_sources():
    """Lista distintas fontes (source) em flight_prices_raw, ordenadas."""
    conn = psycopg2.connect(**main.DB_CONFIG)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT DISTINCT source FROM flight_prices_raw WHERE source IS NOT NULL AND source != '' ORDER BY 1"
            )
            return [row[0] for row in cur.fetchall()]
    finally:
        conn.close()


@app.route("/api/sources")
def api_sources():
    """Retorna lista de fontes cadastradas na base (para filtro dinâmico)."""
    try:
        sources = _get_sources()
        return jsonify({"sources": sources})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/origins_destinations")
def api_origins_destinations():
    """Retorna listas de origens e destinos para autocomplete (com cache)."""
    global _cache_origins, _cache_origins_ts
    try:
        now = time.time()
        if _cache_origins is not None and (now - _cache_origins_ts) < _CACHE_ORIGINS_TTL:
            return jsonify(_cache_origins)
        data = _get_origins_destinations()
        _cache_origins = data
        _cache_origins_ts = now
        return jsonify(data)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# Ofertas só são exibidas se existir em flight_prices_raw registro com scraped_at dentro deste número de dias
DAYS_OFFER_ACTIVE = int(os.environ.get("DAYS_OFFER_ACTIVE", "3"))


def _get_deals(deal_day=None, date_from=None, date_to=None, origin=None, destination=None, limit=50):
    """Lista promoções a partir da view daily_best_deals_ranked. Filtra por origin/destination quando informados.
    Se a coluna scraped_at existir, só retorna ofertas com raw 'ativo' (últimos DAYS_OFFER_ACTIVE dias)."""
    conn = psycopg2.connect(**main.DB_CONFIG)
    try:
        origin = (origin or "").strip().upper() or None
        destination = (destination or "").strip().upper() or None
        where_parts = []
        params = []
        if date_from is not None and date_to is not None:
            where_parts.append("deal_day BETWEEN %s AND %s")
            params.extend([date_from, date_to])
        elif deal_day is not None:
            where_parts.append("deal_day = %s")
            params.append(deal_day)
        else:
            where_parts.append("deal_day = (SELECT MAX(deal_day) FROM daily_best_deals_ranked)")
        if origin:
            where_parts.append("d.origin = %s")
            params.append(origin)
        if destination:
            where_parts.append("d.destination = %s")
            params.append(destination)
        params.append(limit)
        where_sql = " AND ".join(where_parts)

        # Query completa (com filtro scraped_at e payload da raw)
        where_with_active = where_parts[:-1]  # sem o limit
        where_with_active.append("""
            EXISTS (
                SELECT 1 FROM flight_prices_raw r2
                WHERE r2.origin = d.origin AND r2.destination = d.destination
                  AND r2.departure_date = d.departure_date
                  AND r2.return_date IS NOT DISTINCT FROM d.return_date
                  AND r2.price = d.price AND r2.source = d.source
                  AND (r2.scraped_at IS NULL OR r2.scraped_at >= now() - (%s * interval '1 day'))
            )
        """.strip())
        params_full = params[:-1] + [DAYS_OFFER_ACTIVE, DAYS_OFFER_ACTIVE, params[-1]]
        sql_full = """
            SELECT d.source, d.origin, d.destination, d.departure_date, d.return_date,
                   d.airline, d.price, d.currency, d.baseline_avg_30d, d.baseline_min_30d,
                   d.drop_pct, d.score,
                   COALESCE(raw.payload, d.payload) AS payload,
                   d.deal_day, d.global_rank, d.route_rank
            FROM daily_best_deals_ranked d
            LEFT JOIN LATERAL (
                SELECT r.payload
                FROM flight_prices_raw r
                WHERE r.origin = d.origin AND r.destination = d.destination
                  AND r.departure_date = d.departure_date
                  AND r.return_date IS NOT DISTINCT FROM d.return_date
                  AND r.price = d.price AND r.source = d.source
                  AND (r.scraped_at IS NULL OR r.scraped_at >= now() - (%s * interval '1 day'))
                LIMIT 1
            ) raw ON true
            WHERE """ + " AND ".join(where_with_active) + """
            ORDER BY d.global_rank
            LIMIT %s
        """
        # Query fallback (sem scraped_at: para quando a coluna ainda não existe)
        sql_fallback = """
            SELECT d.source, d.origin, d.destination, d.departure_date, d.return_date,
                   d.airline, d.price, d.currency, d.baseline_avg_30d, d.baseline_min_30d,
                   d.drop_pct, d.score,
                   COALESCE(raw.payload, d.payload) AS payload,
                   d.deal_day, d.global_rank, d.route_rank
            FROM daily_best_deals_ranked d
            LEFT JOIN LATERAL (
                SELECT r.payload
                FROM flight_prices_raw r
                WHERE r.origin = d.origin AND r.destination = d.destination
                  AND r.departure_date = d.departure_date
                  AND r.return_date IS NOT DISTINCT FROM d.return_date
                  AND r.price = d.price AND r.source = d.source
                LIMIT 1
            ) raw ON true
            WHERE """ + where_sql + """
            ORDER BY d.global_rank
            LIMIT %s
        """

        with conn.cursor() as cur:
            err = None
            try:
                cur.execute(sql_full, params_full)
            except Exception as e:
                err = e
                conn.rollback()
                # Fallback: query sem scraped_at (coluna ou view pode não existir)
                try:
                    cur.execute(sql_fallback, params)
                except Exception as e2:
                    print(">>> [web_app] Erro ao buscar deals (query completa):", err, file=sys.stderr)
                    print(">>> [web_app] Erro no fallback:", e2, file=sys.stderr)
                    raise e2
            if err:
                print(">>> [web_app] Usando query fallback (sem scraped_at). Erro anterior:", err, file=sys.stderr)
            rows = cur.fetchall()
            cols = [d[0] for d in cur.description]
            return [dict(zip(cols, r)) for r in rows]
    finally:
        conn.close()


@app.route("/api/deals")
def api_deals():
    """Promoções a partir da view daily_best_deals_ranked (melhor por rota+datas, global_rank e route_rank). Query: ?limit=N&day=...&month=...&date_from=...&date_to=..."""
    from flask import request
    import calendar
    try:
        limit = 50
        try:
            limit = min(int(request.args.get("limit", 50)), 200)
        except (ValueError, TypeError):
            pass
        deal_day = None
        date_from = None
        date_to = None
        month_arg = request.args.get("month")
        date_from_arg = request.args.get("date_from")
        date_to_arg = request.args.get("date_to")
        day_arg = request.args.get("day")
        if month_arg:
            try:
                year, month = int(month_arg[:4]), int(month_arg[5:7])
                _, last = calendar.monthrange(year, month)
                date_from = date(year, month, 1)
                date_to = date(year, month, last)
            except (ValueError, TypeError, IndexError):
                pass
        elif date_from_arg and date_to_arg:
            try:
                date_from = datetime.strptime(date_from_arg, "%Y-%m-%d").date()
                date_to = datetime.strptime(date_to_arg, "%Y-%m-%d").date()
                if date_from > date_to:
                    date_from, date_to = date_to, date_from
            except ValueError:
                pass
        elif day_arg:
            try:
                deal_day = datetime.strptime(day_arg, "%Y-%m-%d").date()
            except ValueError:
                pass
        origin_arg = (request.args.get("origin") or "").strip().upper() or None
        destination_arg = (request.args.get("destination") or "").strip().upper() or None
        deals = _get_deals(
            deal_day=deal_day,
            date_from=date_from,
            date_to=date_to,
            origin=origin_arg,
            destination=destination_arg,
            limit=limit,
        )
        for d in deals:
            payload = d.get("payload")
            if isinstance(payload, str):
                try:
                    payload = json.loads(payload) if payload else {}
                except Exception:
                    payload = {}
            d["url"] = build_search_url(
                d.get("origin") or "",
                d.get("destination") or "",
                d.get("source") or "",
                payload or {},
                departure_date=d.get("departure_date"),
                return_date=d.get("return_date"),
            )
        return jsonify(_serialize(deals))
    except Exception as e:
        print(">>> [web_app] /api/deals erro:", e, file=sys.stderr)
        import traceback
        traceback.print_exc(file=sys.stderr)
        return jsonify({"error": str(e)}), 500


def _get_opportunities_filtered(origin: str = None, destination: str = None, days_lookback: int = 60, limit: int = 1000):
    """
    Busca em flight_prices_raw todas as ofertas que batem com o filtro (origin e/ou destination).
    Usa match exato quando o valor é código IATA (3 letras) para aproveitar índice.
    """
    origin = (origin or "").strip().upper() or None
    destination = (destination or "").strip().upper() or None
    if not origin and not destination:
        return None
    conn = psycopg2.connect(**main.DB_CONFIG)
    try:
        where_parts = ["(origin IS NOT NULL AND origin != '')", "(destination IS NOT NULL AND destination != '')"]
        params = []

        def add_origin_dest(field: str, val: str) -> None:
            if not val:
                return
            # Código IATA (3 letras) → match exato (usa índice)
            if len(val) == 3 and val.isalpha():
                where_parts.append(f"UPPER(TRIM({field})) = %s")
                params.append(val)
            else:
                v = val.replace("%", "\\%").replace("_", "\\_")
                where_parts.append(f"UPPER(TRIM({field})) LIKE UPPER(%s)")
                params.append("%" + v + "%")

        add_origin_dest("origin", origin or "")
        add_origin_dest("destination", destination or "")
        where_parts.append("(scraped_at IS NULL OR scraped_at >= now() - (%s * interval '1 day'))")
        params.extend([days_lookback, limit])
        sql = """
            SELECT source, origin, destination, departure_date, return_date, price, payload
            FROM flight_prices_raw
            WHERE """ + " AND ".join(where_parts) + """
            ORDER BY origin, destination, price ASC, departure_date
            LIMIT %s
        """
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()
        opportunities = []
        for r in rows:
            payload = r.get("payload") or {}
            if isinstance(payload, str):
                try:
                    payload = json.loads(payload) if payload else {}
                except Exception:
                    payload = {}
            url = build_search_url(
                r.get("origin") or "",
                r.get("destination") or "",
                r.get("source") or "",
                payload,
                departure_date=r.get("departure_date"),
                return_date=r.get("return_date"),
            )
            opportunities.append({
                "source": r.get("source"),
                "origin": r.get("origin"),
                "destination": r.get("destination"),
                "departure_date": r.get("departure_date"),
                "return_date": r.get("return_date"),
                "price": r.get("price"),
                "url": url,
            })
        return opportunities
    finally:
        conn.close()


@app.route("/api/opportunities")
def api_opportunities():
    """
    Retorna oportunidades (flight_prices_raw).
    Sem filtro: usa motor com max 10 por rota.
    Com ?origin=X e/ou ?destination=Y: retorna TODAS as ofertas cadastradas que batem no filtro (até 1000).
    """
    try:
        days = int(os.environ.get("OPPORTUNITIES_DAYS", "60"))
        origin_arg = (request.args.get("origin") or "").strip().upper() or None
        destination_arg = (request.args.get("destination") or "").strip().upper() or None
        if origin_arg or destination_arg:
            opportunities = _get_opportunities_filtered(
                origin=origin_arg,
                destination=destination_arg,
                days_lookback=days,
                limit=1000,
            )
            if opportunities is None:
                opportunities = []
        else:
            # for_home=1: mínimo para os 9 cards, janela curta (7 dias) para resposta rápida
            for_home = request.args.get("for_home", "").strip().lower() in ("1", "true", "yes")
            if for_home:
                global _cache_home_opportunities, _cache_home_opportunities_ts
                now = time.time()
                if (_cache_home_opportunities is not None and
                        (now - _cache_home_opportunities_ts) < _CACHE_HOME_OPPORTUNITIES_TTL):
                    return jsonify(_serialize(_cache_home_opportunities))
                max_routes, max_per_route = 10, 3
                days_lookback_home = 7
                max_raw_rows = 2500  # cap para resposta rápida
            else:
                max_routes, max_per_route = 60, 10
                days_lookback_home = days
                max_raw_rows = None
            opportunities = generate_opportunities(
                db_config=main.DB_CONFIG,
                source=None,
                days_lookback=days_lookback_home,
                max_per_route=max_per_route,
                max_routes=max_routes,
                max_raw_rows=max_raw_rows,
                silent=True,
            )
            if for_home:
                _cache_home_opportunities = opportunities
                _cache_home_opportunities_ts = time.time()
        return jsonify(_serialize(opportunities))
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ---------- Alertas WhatsApp ----------
def _normalize_phone(phone):
    """Remove tudo que não for dígito; garante código do país (55 Brasil) se tiver 10-11 dígitos."""
    digits = "".join(c for c in (phone or "") if c.isdigit())
    if len(digits) == 10 or len(digits) == 11:
        digits = "55" + digits
    return digits or None


def _send_whatsapp(to_phone: str, body: str) -> bool:
    """Delega para whatsapp_sender (Evolution ou Twilio)."""
    try:
        from whatsapp_sender import send_whatsapp
        return send_whatsapp(to_phone, body)
    except Exception as e:
        print(">>> [web_app] WhatsApp send error:", e, file=sys.stderr)
        return False


def _parse_preferred_date(val) -> Optional[str]:
    """Retorna YYYY-MM-DD ou None."""
    if val is None or (isinstance(val, str) and not val.strip()):
        return None
    s = (val or "").strip()[:10]
    if len(s) == 10 and s[4] == "-" and s[7] == "-":
        return s
    return None


def _parse_preferred_month(val) -> Optional[str]:
    """Retorna YYYY-MM ou None."""
    if val is None or (isinstance(val, str) and not val.strip()):
        return None
    s = (val or "").strip()[:7]
    if len(s) == 7 and s[4] == "-":
        return s
    return None


@app.route("/api/alert-subscriptions", methods=["GET"])
def api_alert_subscriptions_list():
    """Lista inscrições por telefone. Query: ?phone=5511999999999"""
    phone = _normalize_phone(request.args.get("phone"))
    if not phone:
        return jsonify({"error": "Parâmetro phone é obrigatório"}), 400
    conn = psycopg2.connect(**main.DB_CONFIG)
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                "SELECT id, phone, origin, destination, preferred_date, preferred_month, active, created_at FROM alert_subscriptions WHERE phone = %s AND active = true ORDER BY created_at DESC",
                (phone,),
            )
            rows = cur.fetchall()
        return jsonify(_serialize([dict(r) for r in rows]))
    finally:
        conn.close()


@app.route("/api/alert-subscriptions", methods=["POST"])
def api_alert_subscriptions_create():
    """Cadastra alerta WhatsApp: body JSON { phone, origin, destination, preferred_date?, preferred_month? }."""
    data = request.get_json() or {}
    phone = _normalize_phone(data.get("phone"))
    origin = (data.get("origin") or "").strip().upper()[:10] or None
    destination = (data.get("destination") or "").strip().upper()[:10] or None
    preferred_date = _parse_preferred_date(data.get("preferred_date"))
    preferred_month = _parse_preferred_month(data.get("preferred_month"))
    if preferred_date and preferred_month:
        preferred_month = None
    if not phone or not origin or not destination:
        return jsonify({"error": "Preencha phone, origin e destination"}), 400
    conn = psycopg2.connect(**main.DB_CONFIG)
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            try:
                cur.execute(
                    """INSERT INTO alert_subscriptions (phone, origin, destination, preferred_date, preferred_month)
                       VALUES (%s, %s, %s, %s, %s)
                       ON CONFLICT (phone, origin, destination) DO UPDATE SET
                         active = true, preferred_date = EXCLUDED.preferred_date, preferred_month = EXCLUDED.preferred_month
                       RETURNING id, phone, origin, destination, preferred_date, preferred_month, active, created_at""",
                    (phone, origin, destination, preferred_date, preferred_month),
                )
                row = cur.fetchone()
                conn.commit()
            except psycopg2.IntegrityError:
                conn.rollback()
                cur.execute(
                    "SELECT id, phone, origin, destination, preferred_date, preferred_month, active, created_at FROM alert_subscriptions WHERE phone = %s AND origin = %s AND destination = %s",
                    (phone, origin, destination),
                )
                row = cur.fetchone()
                if row:
                    cur.execute(
                        "UPDATE alert_subscriptions SET active = true, preferred_date = %s, preferred_month = %s WHERE id = %s",
                        (preferred_date, preferred_month, row["id"]),
                    )
                    conn.commit()
                    row = dict(row)
                    row["preferred_date"] = preferred_date
                    row["preferred_month"] = preferred_month
        if not row:
            return jsonify({"error": "Falha ao salvar inscrição"}), 500
        out = dict(row)
        period = ""
        if preferred_date:
            period = f" na data {preferred_date}"
        elif preferred_month:
            period = f" no mês {preferred_month}"
        msg = f"Voa Lá: Você se inscreveu para alertas {origin} → {destination}{period}. Enviaremos ofertas por aqui."
        if _send_whatsapp(phone, msg):
            out["whatsapp_sent"] = True
        return jsonify(_serialize(out)), 201
    finally:
        conn.close()


@app.route("/api/alert-subscriptions/<int:sub_id>", methods=["DELETE"])
def api_alert_subscriptions_delete(sub_id):
    """Desativa uma inscrição (soft delete)."""
    conn = psycopg2.connect(**main.DB_CONFIG)
    try:
        with conn.cursor() as cur:
            cur.execute("UPDATE alert_subscriptions SET active = false WHERE id = %s", (sub_id,))
            conn.commit()
            if cur.rowcount == 0:
                return jsonify({"error": "Inscrição não encontrada"}), 404
        return jsonify({"ok": True})
    finally:
        conn.close()


# ---------- Admin (requer X-Admin-Token = ADMIN_TOKEN) ----------
def _require_admin():
    token = request.headers.get("X-Admin-Token") or request.args.get("admin_token")
    expected = os.environ.get("ADMIN_TOKEN")
    if not expected or token != expected:
        return jsonify({"error": "Acesso negado"}), 403
    return None


@app.route("/api/admin/alert-subscriptions", methods=["GET"])
def api_admin_alert_subscriptions_list():
    """Lista todas as inscrições (admin). Query: ?active_only=1&phone=&origin=&destination="""
    err = _require_admin()
    if err:
        return err
    active_only = request.args.get("active_only", "").strip() in ("1", "true", "yes")
    phone = (request.args.get("phone") or "").strip() or None
    origin = (request.args.get("origin") or "").strip().upper() or None
    destination = (request.args.get("destination") or "").strip().upper() or None
    conn = psycopg2.connect(**main.DB_CONFIG)
    try:
        where = ["1=1"]
        params = []
        if active_only:
            where.append("active = true")
        if phone:
            where.append("phone = %s")
            params.append(_normalize_phone(phone) or phone)
        if origin:
            where.append("origin = %s")
            params.append(origin)
        if destination:
            where.append("destination = %s")
            params.append(destination)
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                "SELECT id, phone, origin, destination, preferred_date, preferred_month, active, created_at FROM alert_subscriptions WHERE "
                + " AND ".join(where) + " ORDER BY created_at DESC",
                tuple(params),
            )
            rows = cur.fetchall()
        return jsonify(_serialize([dict(r) for r in rows]))
    finally:
        conn.close()


@app.route("/api/admin/send-alerts", methods=["POST"])
def api_admin_send_alerts():
    """Dispara o motor de envio (respeitando data/mês preferido de cada inscrição)."""
    err = _require_admin()
    if err:
        return err
    days_recent = int(os.environ.get("ALERTS_DAYS_RECENT", "3"))
    try:
        from alerts_engine import run_send_alerts
        sent = run_send_alerts(main.DB_CONFIG, days_recent=days_recent, send_func=_send_whatsapp)
        return jsonify({"sent": sent, "message": f"Enviados {sent} alertas."})
    except Exception as e:
        print(">>> [web_app] send-alerts error:", e, file=sys.stderr)
        return jsonify({"error": str(e), "sent": 0}), 500


@app.route("/")
def index():
    if _HAS_BUILD:
        return send_from_directory(app.static_folder, "index.html")
    return Response(_HTML_BUILD_FIRST, mimetype="text/html; charset=utf-8")


@app.route("/favicon.ico")
def favicon():
    """Evita 404 quando o navegador pede favicon.ico."""
    return "", 204


@app.route("/<path:path>")
def static_files(path):
    if not _HAS_BUILD:
        return Response(_HTML_BUILD_FIRST, mimetype="text/html; charset=utf-8")
    # SPA: rotas como /alertas não são arquivos; servir index.html para o React Router
    if not path or "." not in path.split("/")[-1]:
        return send_from_directory(app.static_folder, "index.html")
    try:
        return send_from_directory(app.static_folder, path)
    except Exception:
        return send_from_directory(app.static_folder, "index.html")


if __name__ == "__main__":
    print(">>> ScrapeAero – API + frontend (Vite + React)")
    print(">>> http://localhost:5000")
    if not _HAS_BUILD:
        print(">>> AVISO: frontend/dist não encontrado. Rode: cd frontend && npm install && npm run build")
    app.run(host="0.0.0.0", port=5000, debug=True)
