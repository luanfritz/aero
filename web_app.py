# -*- coding: utf-8 -*-
"""
API e frontend para consulta de voos e promoções (flight_prices_raw).
Frontend: Vite + React (frontend/). Build em frontend/dist.
Rode: python web_app.py  ->  http://localhost:5000
"""
import json
import os
import sys
from datetime import date, datetime

# Garante que o diretório do projeto está no path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from flask import Flask, jsonify, send_from_directory, Response
from flask_cors import CORS
import psycopg2

import main
from opportunities_engine import generate_opportunities, build_search_url

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
    """Retorna listas de origens e destinos para autocomplete."""
    try:
        data = _get_origins_destinations()
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


@app.route("/api/opportunities")
def api_opportunities():
    """Retorna oportunidades de TODAS as fontes (flight_prices_raw), sem filtrar por source."""
    try:
        days = int(os.environ.get("OPPORTUNITIES_DAYS", "60"))
        opportunities = generate_opportunities(
            db_config=main.DB_CONFIG,
            source=None,
            days_lookback=days,
            max_per_route=10,
            silent=True,
        )
        return jsonify(_serialize(opportunities))
    except Exception as e:
        return jsonify({"error": str(e)}), 500


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
    if _HAS_BUILD:
        return send_from_directory(app.static_folder, path)
    return Response(_HTML_BUILD_FIRST, mimetype="text/html; charset=utf-8")


if __name__ == "__main__":
    print(">>> ScrapeAero – API + frontend (Vite + React)")
    print(">>> http://localhost:5000")
    if not _HAS_BUILD:
        print(">>> AVISO: frontend/dist não encontrado. Rode: cd frontend && npm install && npm run build")
    app.run(host="0.0.0.0", port=5000, debug=True)
