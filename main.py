import asyncio
import json
import random
import re
from datetime import date
from urllib.parse import urlparse
from typing import Optional, Tuple, List

import psycopg2
from playwright.async_api import async_playwright, Page, TimeoutError as PlaywrightTimeoutError


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
FOCUS_ROUTE_ONLY = False
FOCUS_ROUTE = ("BSB", "REC")

# ViajaNet detecta headless e retorna página vazia; usar headed para carregar o Angular
HEADLESS = False

# Só refazer rotas cuja última coleta foi há mais de 6 horas (exige coluna de timestamp em flight_prices_raw)
MIN_HOURS_SINCE_LAST_SCRAPE = 6
# Nome da coluna de data/hora em flight_prices_raw (ex.: "inserted_at", "scraped_at"). None = desativa o filtro de 6h
FLIGHT_PRICES_RAW_TIMESTAMP_COLUMN: Optional[str] = "scraped_at"


PT_MONTHS = {
    "jan": 1, "fev": 2, "mar": 3, "abr": 4, "mai": 5, "jun": 6,
    "jul": 7, "ago": 8, "set": 9, "out": 10, "nov": 11, "dez": 12
}

PRICE_SELECTORS = [
    ".favorite-card-pricebox-price-amount",
    ".offer-card-pricebox-price-current",
    ".pricebox-price-amount",
    "[class*='pricebox-price-amount']",
    "[class*='favorite-card-pricebox-price']",
]

CARD_SELECTORS = [
    "flights-card",
    "favorite-card-flight-itinerary",
    ".eva-3-card",
]


# Status em route_source_status que indicam "não buscar esta rota nesta fonte"
ROUTE_SOURCE_STATUS_IGNORE = ("not_found", "invalid", "error", "unavailable")


# ==========================
# DB HELPERS
# ==========================
def get_routes(limit: Optional[int] = None) -> List[Tuple[str, str]]:
    """Retorna rotas que não estão em route_source_status como ignoradas.
    Se FLIGHT_PRICES_RAW_TIMESTAMP_COLUMN estiver definido, só inclui rotas nunca scrapadas
    ou cuja última coleta foi há mais de MIN_HOURS_SINCE_LAST_SCRAPE horas.
    """
    effective_limit = limit if limit is not None else MAX_ROUTES_PER_RUN
    use_time_filter = FLIGHT_PRICES_RAW_TIMESTAMP_COLUMN and MIN_HOURS_SINCE_LAST_SCRAPE > 0
    conn = psycopg2.connect(**DB_CONFIG)
    try:
        with conn.cursor() as cur:
            if use_time_filter:
                ts_col = FLIGHT_PRICES_RAW_TIMESTAMP_COLUMN
                sql = f"""
                    SELECT r.origin, r.destination
                    FROM routes r
                    LEFT JOIN route_source_status rss
                      ON rss.origin = r.origin AND rss.destination = r.destination AND rss.source = %s
                    LEFT JOIN (
                        SELECT fp.origin, fp.destination, fp.source, MAX(fp.{ts_col}) AS last_scrape
                        FROM flight_prices_raw fp
                        WHERE fp.source = %s
                        GROUP BY fp.origin, fp.destination, fp.source
                    ) last ON last.origin = r.origin AND last.destination = r.destination AND last.source = %s
                    WHERE (rss.origin IS NULL OR rss.status IS NULL OR rss.status NOT IN %s)
                      AND (last.last_scrape IS NULL OR last.last_scrape < now() - (%s * interval '1 hour'))
                    ORDER BY r.id
                    """
                params = (
                    SOURCE_NAME,
                    SOURCE_NAME,
                    SOURCE_NAME,
                    ROUTE_SOURCE_STATUS_IGNORE,
                    MIN_HOURS_SINCE_LAST_SCRAPE,
                )
            else:
                sql = """
                    SELECT r.origin, r.destination
                    FROM routes r
                    LEFT JOIN route_source_status rss
                      ON rss.origin = r.origin AND rss.destination = r.destination AND rss.source = %s
                    WHERE (rss.origin IS NULL OR rss.status IS NULL OR rss.status NOT IN %s)
                    ORDER BY r.id
                    """
                params = (SOURCE_NAME, ROUTE_SOURCE_STATUS_IGNORE)
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
                INSERT INTO route_source_status (source, origin, destination, status, reason, last_checked)
                VALUES (%s, %s, %s, %s, %s, now())
                ON CONFLICT (source, origin, destination)
                DO UPDATE SET status = EXCLUDED.status, reason = EXCLUDED.reason, last_checked = now()
                """,
                (SOURCE_NAME, origin, destination, status, reason),
            )
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
    query = "?from=SB&di=1&reSearch=true"
    return [
        f"{base}/{query}",
        f"{base}{query}",
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
        for selector in CARD_SELECTORS:
            if await page.locator(selector).count() > 0:
                return True

        for selector in PRICE_SELECTORS:
            if await page.locator(selector).count() > 0:
                return True

        if elapsed > 0 and elapsed % 10000 == 0:
            print(f"⏳ Aguardando resultados... {elapsed // 1000}s")

        # Ajuda quando a página só renderiza cards após interações/scroll.
        try:
            await page.evaluate("window.scrollBy(0, 1200)")
        except Exception:
            pass

        await page.wait_for_timeout(interval)
        elapsed += interval

    return False


def extract_offers_from_html(html: str):
    """
    Fallback quando web-components não são materializados no query_selector_all.
    Tenta:
      1) parsing por bloco <flights-card> ou <user-favorite-card>
      2) parsing global por listas de rota/data/preço
    """
    offers = []
    html = html or ""

    # 1) Melhor cenário: extrair cada card inteiro (ViajaNet usa flights-card).
    cards = re.findall(r"<flights-card[\s\S]*?</flights-card>", html, flags=re.I)
    if not cards:
        cards = re.findall(r"<user-favorite-card[\s\S]*?</user-favorite-card>", html, flags=re.I)
    for card in cards:
        route_m = re.search(r'class="route-from-to"[^>]*>\s*([A-Z]{3}\s*-\s*[A-Z]{3})\s*<', card)
        date_m = re.search(r'class="date"[^>]*>\s*([^<]+)\s*<', card)
        price_m = re.search(r'class="[^"]*price[^"]*amount[^"]*"[^>]*>\s*([\d\.,]+)\s*<', card)

        route_text = route_m.group(1).strip() if route_m else ""
        date_text = date_m.group(1).strip() if date_m else ""
        price_text = price_m.group(1).strip() if price_m else ""

        if route_text and date_text and price_text:
            offers.append((route_text, date_text, price_text))

    if offers:
        return offers

    # 2) Fallback global: alguns retornos não fecham/expõem bem os custom elements.
    routes = re.findall(r'class="route-from-to"[^>]*>\s*([A-Z]{3}\s*-\s*[A-Z]{3})\s*<', html)
    dates = re.findall(r'class="date"[^>]*>\s*([^<]+)\s*<', html)
    prices = re.findall(r'class="[^"]*price[^"]*amount[^"]*"[^>]*>\s*([\d\.,]+)\s*<', html)

    if not routes or not dates or not prices:
        return []

    # Em geral vem IDA/VOLTA (2 rotas, 2 datas) para cada preço.
    outbound_routes = routes[::2] if len(routes) > 1 else routes
    outbound_dates = dates[::2] if len(dates) > 1 else dates

    total = min(len(outbound_routes), len(outbound_dates), len(prices), MAX_OFFERS_PER_ROUTE)
    for i in range(total):
        route_text = outbound_routes[i].strip()
        date_text = outbound_dates[i].strip()
        price_text = prices[i].strip()
        if route_text and date_text and price_text:
            offers.append((route_text, date_text, price_text))

    return offers


async def extract_offers_from_visible_cards(page: Page):
    offers = []
    # ViajaNet usa flights-card; fallback para eva-3-card
    cards = page.locator("flights-card")
    card_count = await cards.count()
    if card_count == 0:
        cards = page.locator(".eva-3-card")
        card_count = await cards.count()
    total = min(card_count, MAX_OFFERS_PER_ROUTE)

    for i in range(total):
        text = await cards.nth(i).inner_text()
        route_m = re.search(r"([A-Z]{3}\s*-\s*[A-Z]{3})", text or "")
        date_m = re.search(r"(?:Seg|Ter|Qua|Qui|Sex|Sáb|Sab|Dom)\.\s*\d{1,2}\s+[a-zç]{3}\.\s+\d{4}", text or "", re.I)
        price_m = re.search(r"R\$\s*([\d\.]+)", text or "")

        route_text = route_m.group(1).strip() if route_m else ""
        date_text = date_m.group(0).strip() if date_m else ""
        price_text = price_m.group(1).strip() if price_m else ""

        if route_text and date_text and price_text:
            offers.append((route_text, date_text, price_text))

    return offers


def is_home_redirect(url: str) -> bool:
    parsed = urlparse(url or "")
    host = parsed.netloc.lower()
    path = (parsed.path or "/").rstrip("/")
    return host.endswith("viajanet.com.br") and path == ""


def is_valid_route_url(url: str, origin: str, destination: str) -> bool:
    parsed = urlparse(url or "")
    host = parsed.netloc.lower()
    path = (parsed.path or "").lower()
    expected_prefix = f"/passagens-aereas/{origin.lower()}/{destination.lower()}"
    return host.endswith("viajanet.com.br") and path.startswith(expected_prefix)


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

    url = urls[0]
    valid_navigation = False

    for candidate_url in urls:
        await page.goto(candidate_url, wait_until="load", timeout=60000)
        await page.wait_for_timeout(10000)

        current_url = page.url
        if is_home_redirect(current_url):
            print(f"⚠️ Redirect para home em {candidate_url}: {current_url}")
            continue

        if is_valid_route_url(current_url, origin_hint, destination_hint):
            url = current_url
            valid_navigation = True
            break

        html_len = len(await page.content())
        print(f"⚠️ URL inesperada ({current_url}) / HTML {html_len} em {candidate_url}, tentando variante...")

    if not valid_navigation:
        print("⚠️ Não foi possível carregar página válida da rota (home/URL inesperada).")
        try:
            upsert_route_source_status(
                origin_hint, destination_hint,
                status="not_found",
                reason="redirect_to_home",
            )
            print(f"   Registrado em route_source_status: {origin_hint}->{destination_hint} (status=not_found)")
        except Exception as e:
            print(f"   Erro ao registrar em route_source_status: {e}")
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
        await page.reload(wait_until="load", timeout=60000)
        await page.wait_for_timeout(10000)
        has_results = await wait_for_results(page, timeout_ms=30000)

    if not has_results:
        print("⚠️ Timeout aguardando cards/preço; seguindo para checagem final do DOM.")

    # ViajaNet: flights-card contém itinerary + pricebox; favorite-card-flight-itinerary também funciona
    itinerary_locator = page.locator("favorite-card-flight-itinerary")
    itinerary_count = await itinerary_locator.count()
    if itinerary_count == 0:
        itinerary_locator = page.locator("flights-card")
        itinerary_count = await itinerary_locator.count()
    if itinerary_count == 0:
        # fallback por cards visíveis renderizados
        fallback_offers = await extract_offers_from_visible_cards(page)
        if not fallback_offers:
            # fallback por HTML bruto (algumas execuções não materializam os custom elements no query_selector_all)
            html = await page.content()
            fallback_offers = extract_offers_from_html(html)
        if not fallback_offers:
            html = await page.content()
            html_size = len(html or "")
            print(f"⚠️ Nenhum card encontrado. HTML recebido: {html_size} chars")
            if html_size < 5000:
                try:
                    with open("debug_viajanet.html", "w", encoding="utf-8") as f:
                        f.write(html)
                    print("   (HTML salvo em debug_viajanet.html para inspeção)")
                except Exception:
                    pass
            return 0

        saved = 0
        for route_out, date_out_text, price_text in fallback_offers[:MAX_OFFERS_PER_ROUTE]:
            origin, destination = parse_route(route_out)
            dep_date = parse_ptbr_date(date_out_text)
            price_brl = parse_price_to_int(price_text)
            if not origin or not destination or not dep_date or price_brl <= 0:
                continue

            payload = {
                "airline": None,
                "route_out": route_out,
                "date_out_text": date_out_text,
                "return_date_text": None,
                "price_text": price_text,
                "url": url,
                "origin_hint": origin_hint,
                "destination_hint": destination_hint,
                "extraction_mode": "html_fallback",
            }
            insert_raw(origin, destination, dep_date, None, price_brl, payload)
            saved += 1

        print(f"✅ Salvos via fallback para {origin_hint}->{destination_hint}: {saved}")
        return saved

    total = min(itinerary_count, MAX_OFFERS_PER_ROUTE)
    print(f"Encontrados {itinerary_count} cards (processando {total})")

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
        routes = get_routes()
        if not routes:
            print("❌ Nenhuma rota na tabela routes.")
            return

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=HEADLESS,
            args=["--disable-blink-features=AutomationControlled", "--no-sandbox"],
        )
        context = await browser.new_context(
            locale="pt-BR",
            viewport={"width": 1920, "height": 1080},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
            java_script_enabled=True,
        )
        await context.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
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


if __name__ == "__main__":
    asyncio.run(run_batch())
