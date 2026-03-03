import asyncio
import json
import random
import re
from datetime import date
from urllib.parse import urlparse
from typing import Optional, Tuple, List

import psycopg2
from playwright.async_api import async_playwright, Page, TimeoutError as PlaywrightTimeoutError

from opportunities_engine import generate_opportunities

from opportunities_engine import generate_opportunities

from opportunities_engine import generate_opportunities

from opportunities_engine import generate_opportunities


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

MAX_ROUTES_PER_RUN = None        # None = todas as rotas elegíveis do DB
MAX_OFFERS_PER_ROUTE = 25        # limita quantos cards por rota (pra não demorar demais)
DELAY_MS_BETWEEN_ROUTES = (2500, 6000)  # pausa aleatória (min, max)
ROUTE_TIMEOUT_S = 120  # evita travamento em rota problemática

# Debug temporário: focar em uma rota até estabilizar o scraper
FOCUS_ROUTE_ONLY = True
FOCUS_ROUTE = ("BSB", "REC")
NAVIGATION_ATTEMPTS = 3
ROUTE_SOURCE_STATUS_IGNORE = ("INACTIVE", "BLOCKED")
BROWSER_HEADLESS = False  # False abre navegador visível para depuração


PT_MONTHS = {
    "jan": 1, "fev": 2, "mar": 3, "abr": 4, "mai": 5, "jun": 6,
    "jul": 7, "ago": 8, "set": 9, "out": 10, "nov": 11, "dez": 12
}

PRICE_SELECTORS = [
    ".favorite-card-pricebox-price-amount",
    ".pricebox-price-amount",
    "[class*='pricebox-price-amount']",
]


# ==========================
# DB HELPERS
# ==========================
def has_column(table_name: str, column_name: str) -> bool:
    conn = psycopg2.connect(**DB_CONFIG)
    try:
        with conn.cursor() as cur:
            sql = """
                SELECT r.origin, r.destination
                FROM routes r
                LEFT JOIN route_source_status rss
                  ON rss.origin = r.origin AND rss.destination = r.destination AND rss.source = %s
                LEFT JOIN (
                    SELECT origin, destination, source, MAX(created_at) AS last_scrape
                    FROM flight_prices_raw
                    WHERE source = %s
                    GROUP BY origin, destination, source
                ) last ON last.origin = r.origin AND last.destination = r.destination AND last.source = %s
                WHERE (rss.origin IS NULL OR rss.status IS NULL OR rss.status NOT IN %s)
                  AND (last.last_scrape IS NULL OR last.last_scrape < now() - (%s * interval '1 hour'))
                ORDER BY r.id
                """
            params: tuple = (
                SOURCE_NAME,
                SOURCE_NAME,
                SOURCE_NAME,
                ROUTE_SOURCE_STATUS_IGNORE,
                MIN_HOURS_SINCE_LAST_SCRAPE,
            )
            if effective_limit is not None:
                sql += " LIMIT %s"
                params = params + (effective_limit,)
            cur.execute(sql, params)
            return cur.fetchall()
    finally:
        conn.close()


def upsert_route_source_status(origin: str, destination: str, status: str, reason: Optional[str] = None) -> None:
    """Registra rota em route_source_status quando não existe na fonte (ex: redirect para home)."""
    conn = psycopg2.connect(**DB_CONFIG)
    try:
        with conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT 1
                FROM information_schema.columns
                WHERE table_schema = 'public'
                  AND table_name = %s
                  AND column_name = %s
                LIMIT 1
                """,
                (table_name, column_name),
            )
            return cur.fetchone() is not None
    finally:
        conn.close()


def get_routes(limit: int = MAX_ROUTES_PER_RUN) -> List[Tuple[str, str]]:
    conn = psycopg2.connect(**DB_CONFIG)
    try:
        with conn.cursor() as cur:
            if has_column("routes", "source_status"):
                cur.execute(
                    """
                    SELECT origin, destination
                    FROM routes
                    WHERE COALESCE(source_status, '') <> ALL(%s)
                    ORDER BY id
                    LIMIT %s
                    """,
                    (list(ROUTE_SOURCE_STATUS_IGNORE), limit),
                )
            else:
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


def build_viajanet_url_variants(origin: str, destination: str) -> List[str]:
    base = f"https://www.viajanet.com.br/passagens-aereas/{origin.lower()}/{destination.lower()}"
    return [
        f"{base}/?from=SB&di=1&reSearch=true",
        f"{base}?from=SB&di=1&reSearch=true",
        f"{base}/?from=HOME&di=1&reSearch=true",
    ]


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




async def wait_for_results(page: Page, timeout_ms: int) -> bool:
    elapsed = 0
    interval = 2000

    while elapsed < timeout_ms:
        itineraries = await page.query_selector_all("favorite-card-flight-itinerary")
        if itineraries:
            return True

        for selector in PRICE_SELECTORS:
            if await page.query_selector(selector):
                return True

        # Ajuda quando a página só renderiza cards após interações/scroll.
        try:
            await page.evaluate("window.scrollBy(0, 1200)")
        except Exception:
            pass

        await page.wait_for_timeout(interval)
        elapsed += interval

    return False


# ==========================
# SCRAPER CORE
# ==========================
async def scrape_route(page: Page, origin_hint: str, destination_hint: str) -> int:
    """
    origin_hint/destination_hint: vindo da tabela routes.
    A página pode renderizar CNF/BPS etc. A gente usa o que extrair do card.
    """
    urls = build_viajanet_url_variants(origin_hint, destination_hint)
    print(f"\n🔎 Rota: {origin_hint}->{destination_hint}")
    print(f"URL: {urls[0]}")

    url = await load_route_with_retries(page, origin_hint, destination_hint)
    if not url:
        print("⚠️ Não foi possível carregar página válida da rota após retries.")
        return 0
    # Alguns cenários abrem banner/overlay que atrapalha a renderização dos cards.
    # Tentamos fechar de forma defensiva sem quebrar a execução.
    close_button = page.get_by_role("button", name=re.compile(r"aceitar|entendi|fechar", re.I)).first
    try:
        if await close_button.is_visible(timeout=2500):
            await close_button.click()
    except Exception:
        pass

    # Em algumas rotas o className do preço muda e o carregamento é irregular.
    # Faz polling por cards/preço e tenta um reload quando necessário.
    has_results = await wait_for_results(page, timeout_ms=60000)
    if not has_results:
        # Viajanet eventualmente carrega estado incompleto; um reload costuma resolver.
        await page.reload(wait_until="domcontentloaded")
        has_results = await wait_for_results(page, timeout_ms=30000)

    if not has_results:
        print("⚠️ Timeout aguardando cards/preço; seguindo para checagem final do DOM.")

    itineraries = await page.query_selector_all("favorite-card-flight-itinerary")
    if not itineraries:
        print("⚠️ Nenhum card encontrado.")
        return 0

    total = min(len(itineraries), MAX_OFFERS_PER_ROUTE)
    print(f"Encontrados {len(itineraries)} cards (processando {total})")

    saved = 0

    for i in range(total):
        it = await itinerary_locator.nth(i).element_handle()
        if not it:
            continue

        # ViajaNet: flights-card é o container raiz; subir até ele para ver itinerary + pricebox
        container = await it.evaluate_handle(
            "el => el.closest && el.closest('flights-card') || el.parentElement?.parentElement?.parentElement || el.parentElement?.parentElement || el"
        )

        airline_el = await container.query_selector(".airline-name")
        airline = (await airline_el.inner_text()).strip() if airline_el else None

        route_els = await container.query_selector_all(".route-from-to")
        date_els = await container.query_selector_all(".date")

        price_el = None
        for selector in PRICE_SELECTORS:
            price_el = await container.query_selector(selector)
            if price_el:
                break
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
    if FOCUS_ROUTE_ONLY:
        routes = [FOCUS_ROUTE]
        print(f"🎯 Modo foco ativo: processando apenas {FOCUS_ROUTE[0]}->{FOCUS_ROUTE[1]}")
    else:
        routes = get_routes(MAX_ROUTES_PER_RUN)
        if not routes:
            print("❌ Nenhuma rota na tabela routes.")
            return

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=BROWSER_HEADLESS)
        context = await browser.new_context()
        page = await context.new_page()
        page.set_default_timeout(30000)

        total_saved = 0

        for (origin, destination) in routes:
            try:
                total_saved += await asyncio.wait_for(
                    scrape_route(page, origin, destination),
                    timeout=ROUTE_TIMEOUT_S,
                )
            except asyncio.TimeoutError:
                print(f"❌ Timeout geral na rota {origin}->{destination} após {ROUTE_TIMEOUT_S}s")
            except Exception as e:
                print(f"❌ Erro em {origin}->{destination}: {e}")

            # pausa aleatória entre rotas
            await page.wait_for_timeout(random.randint(*DELAY_MS_BETWEEN_ROUTES))

        await browser.close()

    print(f"\n🎉 Total salvo nesta execução: {total_saved}")

    opportunities = generate_opportunities()
    print(f"🚨 Oportunidades novas geradas: {opportunities}")

if __name__ == "__main__":
    asyncio.run(run_batch())
