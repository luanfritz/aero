# -*- coding: utf-8 -*-
"""
API e frontend para consulta de voos e promoções (flight_prices_raw).
Rode: python web_app.py  ->  http://localhost:5000
"""
import json
import os
import sys
from datetime import date, datetime

# Garante que o diretório do projeto está no path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from flask import Flask, jsonify, send_from_directory
from flask_cors import CORS
import psycopg2

import main
from opportunities_engine import generate_opportunities, build_search_url

app = Flask(__name__, static_folder="web", static_url_path="")
CORS(app)


def _serialize(obj):
    if isinstance(obj, (date, datetime)):
        return obj.isoformat()
    if isinstance(obj, dict):
        return {k: _serialize(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_serialize(x) for x in obj]
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


def _get_deals(deal_day=None, date_from=None, date_to=None, origin=None, destination=None, limit=50):
    """Lista promoções a partir da view daily_best_deals_ranked. Filtra por origin/destination quando informados."""
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
            where_parts.append("origin = %s")
            params.append(origin)
        if destination:
            where_parts.append("destination = %s")
            params.append(destination)
        params.append(limit)
        where_sql = " AND ".join(where_parts)
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT source, origin, destination, departure_date, return_date,
                       airline, price, currency, baseline_avg_30d, baseline_min_30d,
                       drop_pct, score, payload, deal_day, global_rank, route_rank
                FROM daily_best_deals_ranked
                WHERE """ + where_sql + """
                ORDER BY global_rank
                LIMIT %s
                """,
                params,
            )
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
            )
        return jsonify(_serialize(deals))
    except Exception as e:
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
    return send_from_directory(app.static_folder, "index.html")


@app.route("/favicon.ico")
def favicon():
    """Evita 404 quando o navegador pede favicon.ico."""
    return "", 204


@app.route("/<path:path>")
def static_files(path):
    return send_from_directory(app.static_folder, path)


if __name__ == "__main__":
    print(">>> Frontend: http://localhost:5000")
    app.run(host="0.0.0.0", port=5000, debug=True)
