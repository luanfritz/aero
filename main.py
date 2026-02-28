import asyncio
import json
import random
import re
from datetime import date, datetime, timedelta
from typing import Optional, Tuple, List

import psycopg2
from playwright.async_api import async_playwright, Page
from playwright.async_api import TimeoutError as PlaywrightTimeoutError


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

MAX_ROUTES_PER_RUN = 10
MAX_OFFERS_PER_ROUTE = 25
DELAY_MS_BETWEEN_ROUTES = (2500, 6000)

# cooldown por status (ajuste se quiser)
COOLDOWN_HOURS_NO_RESULTS = 24
COOLDOWN_HOURS_TIMEOUT = 6
COOLDOWN_HOURS_ERROR = 12

# textos comuns que indicam “sem resultados”
NO_RESULTS_TEXTS = [
    "nenhum voo", "nenhum resultado", "não encontramos", "nao encontramos",
    "não há voos", "nao ha voos", "sem resultados", "sem voos"
]

PT_MONTHS = {
    "jan": 1, "fev": 2, "mar": 3, "abr": 4, "mai": 5, "jun": 6,
    "jul": 7, "ago": 8, "set": 9, "out": 10, "nov": 11, "dez": 12
}


# ==========================
# DB HELPERS
# ==========================
def get_routes(limit: int = MAX_ROUTES_PER_RUN) -> List[Tuple[str, str]]:
    """
    Pega rotas "tentáveis" (fora do cooldown) para essa fonte.
    """
    conn = psycopg2.connect(**DB_CONFIG)
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT r.origin, r.destination
                FROM routes r
                LEFT JOIN route_source_status s
                  ON s.source = %s
                 AND s.origin = r.origin
                 AND s.destination = r.destination
                WHERE s.next_retry_at IS NULL OR s.next_retry_at <= NOW()
                ORDER BY r.id
                LIMIT %s
                """,
                (SOURCE_NAME, limit)
            )
            return cur.fetchall()
    finally:
        conn.close()


def upsert_route_status(origin: str, destination: str, status: str, reason: Optional[str]) -> None:
    """
    Atualiza status da rota para a fonte atual e define next_retry_at.
    """
    now = datetime.now()
    next_retry = None

    if status == "NO_RESULTS":
        next_retry = now + timedelta(hours=COOLDOWN_HOURS_NO_RESULTS)
    elif status == "TIMEOUT":
        next_retry = now + timedelta(hours=COOLDOWN_HOURS_TIMEOUT)
    elif status == "ERROR":
        next_retry = now + timedelta(hours=COOLDOWN_HOURS_ERROR)
    elif status == "OK":
        next_retry = now  # pode tentar de novo imediatamente (ou defina um intervalo)

    conn = psycopg2.connect(**DB_CONFIG)
    try:
        with conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO route_source_status
                  (source, origin, destination, status, reason, last_checked, next_retry_at)
                VALUES
                  (%s, %s, %s, %s, %s, NOW(), %s)
                ON CONFLICT (source, origin, destination)
                DO UPDATE SET
                  status = EXCLUDED.status,
                  reason = EXCLUDED.reason,
                  last_checked = NOW(),
                  next_retry_at = EXCLUDED.next_retry_at
                """,
                (SOURCE_NAME, origin, destination, status, reason, next_retry)
            )
    finally:
        conn.close()


def insert_raw(origin: str, destination: str, dep: date, ret: Optional[date], price_brl: int, payload: dict) -> None:
    """
    Insere em flight_prices_raw com anti-duplicação.
    Requer o índice unique: ux_flight_raw_dedup
    """
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
# PARSERS / BUILDERS
# ==========================
def build_viajanet_url(origin: str, destination: str) -> str:
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
# PAGE WAIT LOGIC
# ==========================
async def wait_for_results_or_fail(page: Page) -> Tuple[str, str]:
    """
    Retorna:
      ("OK", "cards_found")         se cards aparecerem
      ("NO_RESULTS", reason)       se identificar texto de sem resultados
      ("TIMEOUT", reason)          se não encontrar nada dentro do tempo
    """
    try:
        await page.wait_for_selector(".favorite-card-pricebox-price-amount", timeout=20000)
        return "OK", "cards_found"
    except PlaywrightTimeoutError:
        html = (await page.content()).lower()
        if any(t in html for t in NO_RESULTS_TEXTS):
            return "NO_RESULTS", "no_results_text_found"
        return "TIMEOUT", "no_cards_timeout"


# ==========================
# SCRAPER
# ==========================
async def scrape_route(page: Page, origin_hint: str, destination_hint: str) -> int:
    url = build_viajanet_url(origin_hint, destination_hint)
    print(f"\n🔎 Rota: {origin_hint}->{destination_hint}")
    print(f"URL: {url}")

    await page.goto(url, wait_until="load", timeout=60000)

    status, reason = await wait_for_results_or_fail(page)
    if status == "TIMEOUT":
        await page.reload(wait_until="load")
        status, reason = await wait_for_results_or_fail(page)

    if status != "OK":
        print(f"⚠️ {origin_hint}->{destination_hint} sem cards ({status}/{reason})")
        upsert_route_status(origin_hint, destination_hint, status, reason)
        return 0

    itineraries = await page.query_selector_all("favorite-card-flight-itinerary")
    total = min(len(itineraries), MAX_OFFERS_PER_ROUTE)
    print(f"Encontrados {len(itineraries)} cards (processando {total})")

    saved = 0
    for i in range(total):
        it = itineraries[i]
        container = await it.evaluate_handle("el => el.parentElement.parentElement")

        airline_el = await container.query_selector(".airline-name")
        airline = (await airline_el.inner_text()).strip() if airline_el else None

        route_els = await container.query_selector_all(".route-from-to")
        date_els = await container.query_selector_all(".date")

        price_el = await container.query_selector(".favorite-card-pricebox-price-amount")
        if not price_el:
            # às vezes preço demora; tenta esperar um pouco dentro do card
            try:
                await container.wait_for_selector(".favorite-card-pricebox-price-amount", timeout=5000)
                price_el = await container.query_selector(".favorite-card-pricebox-price-amount")
            except:
                continue

        price_text = (await price_el.inner_text()).strip()
        price_brl = parse_price_to_int(price_text)
        if price_brl <= 0:
            continue

        route_out = (await route_els[0].inner_text()).strip() if len(route_els) >= 1 else ""
        date_out_text = (await date_els[0].inner_text()).strip() if len(date_els) >= 1 else ""
        origin, destination = parse_route(route_out)
        dep_date = parse_ptbr_date(date_out_text)

        ret_date = None
        ret_date_text = None
        if len(date_els) >= 2:
            ret_date_text = (await date_els[1].inner_text()).strip()
            ret_date = parse_ptbr_date(ret_date_text)

        if not origin or not destination or not dep_date:
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

    upsert_route_status(origin_hint, destination_hint, "OK", f"saved={saved}")
    print(f"✅ Salvos (raw) para {origin_hint}->{destination_hint}: {saved}")
    return saved

async def run_batch():
    async def run_batch():
        routes = get_routes(MAX_ROUTES_PER_RUN)
        if not routes:
            print("❌ Nenhuma rota disponível.")
            return

        async with async_playwright() as p:
            # 1) headless normal
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(locale="pt-BR", timezone_id="America/Sao_Paulo")
            page = await context.new_page()

            total_saved = 0

            for origin, destination in routes:
                saved = 0
                try:
                    saved = await scrape_route(page, origin, destination, allow_debug=True)
                    total_saved += saved
                except Exception as e:
                    print(f"❌ Erro em {origin}->{destination}: {e}")
                    upsert_route_status(origin, destination, "ERROR", str(e))

                # 2) fallback headful se não salvou nada e foi TIMEOUT
                if saved == 0:
                    # olha o status atual pra decidir
                    # (se quiser, simplifica e sempre tenta headful quando saved==0)
                    print(f"↩️ Fallback headful para {origin}->{destination}...")
                    try:
                        await browser.close()
                        browser2 = await p.chromium.launch(headless=False)
                        ctx2 = await browser2.new_context(locale="pt-BR", timezone_id="America/Sao_Paulo")
                        page2 = await ctx2.new_page()

                        total_saved += await scrape_route(page2, origin, destination, allow_debug=True)

                        await browser2.close()
                        # reabre headless para continuar o batch
                        browser = await p.chromium.launch(headless=True)
                        context = await browser.new_context(locale="pt-BR", timezone_id="America/Sao_Paulo")
                        page = await context.new_page()
                    except Exception as e:
                        print(f"❌ Fallback headful falhou em {origin}->{destination}: {e}")
                        upsert_route_status(origin, destination, "ERROR", f"headful_fallback:{e}")

                await page.wait_for_timeout(random.randint(*DELAY_MS_BETWEEN_ROUTES))

            await browser.close()

        print(f"\n🎉 Total salvo nesta execução: {total_saved}")


if __name__ == "__main__":
    asyncio.run(run_batch())