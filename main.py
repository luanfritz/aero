import asyncio
import json
import random
import re
from datetime import date
from typing import Optional, Tuple, List

import psycopg2
from playwright.async_api import async_playwright, Page


# ==========================
# CONFIG
# ==========================
DB_CONFIG = {
    "host": "localhost",
    "port": 5432,
    "dbname": "postgres",
    "user": "postgres",
    "password": "290535",

}

SOURCE_NAME = "viajanet"
CURRENCY = "BRL"

MAX_ROUTES_PER_RUN = 10          # quantas rotas você quer por execução
MAX_OFFERS_PER_ROUTE = 25        # limita quantos cards por rota (pra não demorar demais)
DELAY_MS_BETWEEN_ROUTES = (2500, 6000)  # pausa aleatória (min, max)


PT_MONTHS = {
    "jan": 1, "fev": 2, "mar": 3, "abr": 4, "mai": 5, "jun": 6,
    "jul": 7, "ago": 8, "set": 9, "out": 10, "nov": 11, "dez": 12
}


# ==========================
# DB HELPERS
# ==========================
def get_routes(limit: int = MAX_ROUTES_PER_RUN) -> List[Tuple[str, str]]:
    conn = psycopg2.connect(**DB_CONFIG)
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT origin, destination
                FROM routes
                ORDER BY id
                LIMIT %s
                """,
                (limit,)
            )
            return cur.fetchall()
    finally:
        conn.close()


def insert_raw(origin: str, destination: str, dep: date, ret: Optional[date], price_brl: int, payload: dict) -> None:
    conn = psycopg2.connect(**DB_CONFIG)
    try:
        with conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO flight_prices_raw
                    (origin, destination, departure_date, return_date, price, currency, source, payload)
                VALUES
                    (%s, %s, %s, %s, %s, %s, %s, %s::jsonb)
                ON CONFLICT (origin, destination, departure_date, return_date, price, source)
                DO NOTHING
                """,
                (
                    origin,
                    destination,
                    dep,
                    ret,
                    price_brl,
                    CURRENCY,
                    SOURCE_NAME,
                    json.dumps(payload, ensure_ascii=False),
                )
            )
    finally:
        conn.close()


# ==========================
# PARSERS
# ==========================
def build_viajanet_url(origin: str, destination: str) -> str:
    # padrão simples e estável (SEO)
    return (
        f"https://www.viajanet.com.br/passagens-aereas/"
        f"{origin.lower()}/{destination.lower()}/"
        f"?from=SB&di=1&reSearch=true"
    )


def parse_price_to_int(price_text: str) -> int:
    digits = re.sub(r"[^\d]", "", price_text or "")
    return int(digits) if digits else 0


def parse_route(route_text: str) -> Tuple[Optional[str], Optional[str]]:
    m = re.search(r"\b([A-Z]{3})\s*-\s*([A-Z]{3})\b", route_text or "")
    if not m:
        return None, None
    return m.group(1), m.group(2)


def parse_ptbr_date(text: str) -> Optional[date]:
    if not text:
        return None
    t = text.lower()
    m = re.search(r"(\d{1,2})\s+([a-zç]{3})\.?\s+(\d{4})", t)
    if not m:
        return None
    day = int(m.group(1))
    mon = PT_MONTHS.get(m.group(2))
    year = int(m.group(3))
    if not mon:
        return None
    return date(year, mon, day)


# ==========================
# SCRAPER CORE
# ==========================
async def scrape_route(page: Page, origin_hint: str, destination_hint: str) -> int:
    """
    origin_hint/destination_hint: vindo da tabela routes.
    A página pode renderizar CNF/BPS etc. A gente usa o que extrair do card.
    """
    url = build_viajanet_url(origin_hint, destination_hint)
    print(f"\n🔎 Rota: {origin_hint}->{destination_hint}")
    print(f"URL: {url}")

    await page.goto(url, wait_until="domcontentloaded")

    # não usar networkidle aqui; esperar pelo preço
    await page.wait_for_selector(".favorite-card-pricebox-price-amount", timeout=60000)

    itineraries = await page.query_selector_all("favorite-card-flight-itinerary")
    if not itineraries:
        print("⚠️ Nenhum card encontrado.")
        return 0

    total = min(len(itineraries), MAX_OFFERS_PER_ROUTE)
    print(f"Encontrados {len(itineraries)} cards (processando {total})")

    saved = 0

    for i in range(total):
        it = itineraries[i]

        # O que funcionou contigo: subir para um container que enxerga o pricebox
        container = await it.evaluate_handle("el => el.parentElement.parentElement")

        airline_el = await container.query_selector(".airline-name")
        airline = (await airline_el.inner_text()).strip() if airline_el else None

        route_els = await container.query_selector_all(".route-from-to")
        date_els = await container.query_selector_all(".date")

        price_el = await container.query_selector(".favorite-card-pricebox-price-amount")
        if not price_el:
            continue

        price_text = (await price_el.inner_text()).strip()
        price_brl = parse_price_to_int(price_text)
        if price_brl <= 0:
            continue

        # ida (primeira rota/data)
        route_out = (await route_els[0].inner_text()).strip() if len(route_els) >= 1 else ""
        date_out_text = (await date_els[0].inner_text()).strip() if len(date_els) >= 1 else ""
        origin, destination = parse_route(route_out)
        dep_date = parse_ptbr_date(date_out_text)

        # volta (se existir)
        ret_date = None
        ret_date_text = None
        if len(date_els) >= 2:
            ret_date_text = (await date_els[1].inner_text()).strip()
            ret_date = parse_ptbr_date(ret_date_text)

        if not origin or not destination or not dep_date:
            # se não parseou, pula (log útil)
            print("SKIP: parse falhou",
                  {"route_out": route_out, "date_out": date_out_text, "price": price_text, "airline": airline})
            continue

        payload = {
            "airline": airline,
            "route_out": route_out,
            "date_out_text": date_out_text,
            "return_date_text": ret_date_text,
            "price_text": price_text,
            "url": url,
            "origin_hint": origin_hint,
            "destination_hint": destination_hint,
        }

        insert_raw(origin, destination, dep_date, ret_date, price_brl, payload)
        saved += 1

    print(f"✅ Salvos (raw) para {origin_hint}->{destination_hint}: {saved}")
    return saved


async def run_batch():
    routes = get_routes(MAX_ROUTES_PER_RUN)
    if not routes:
        print("❌ Nenhuma rota na tabela routes.")
        return

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context()
        page = await context.new_page()

        total_saved = 0

        for (origin, destination) in routes:
            try:
                total_saved += await scrape_route(page, origin, destination)
            except Exception as e:
                print(f"❌ Erro em {origin}->{destination}: {e}")

            # pausa aleatória entre rotas
            await page.wait_for_timeout(random.randint(*DELAY_MS_BETWEEN_ROUTES))

        await browser.close()

    print(f"\n🎉 Total salvo nesta execução: {total_saved}")


if __name__ == "__main__":
    asyncio.run(run_batch())