# -*- coding: utf-8 -*-
"""
Monitor Passagens Imperdíveis: lista todas as promoções, abre cada link,
expande os acordeões e extrai ofertas de voo (ida/volta, preço), cadastrando
na base com fonte "passagens_imperdiveis".

Modo serviço: varredura a cada SCAN_INTERVAL_MINUTES; ignora promoções já al
cadastradas (com registros em flight_prices_raw para essa promo_url).
"""
import json
import os
import re
import sys
import time
from datetime import date
from typing import Any, Dict, List, Optional, Set
from urllib.parse import urljoin

import psycopg2
from playwright.sync_api import sync_playwright

URL = "https://passagensimperdiveis.com.br/promocoes-recentes/"
BASE_URL = "https://passagensimperdiveis.com.br"

SOURCE_NAME = "passagens_imperdiveis"
CURRENCY = "BRL"

DB_CONFIG = {
    "host": "localhost",
    "port": 5432,
    "dbname": "postgres",
    "user": "postgres",
    "password": "290535",
}

# Intervalo entre varreduras (minutos). Pode sobrescrever com env MONITOR_PI_INTERVAL_MINUTES
SCAN_INTERVAL_MINUTES = int(os.environ.get("MONITOR_PI_INTERVAL_MINUTES", "10"))

# URL única para o serviço focar a cada varredura (modo teste). None = varredura normal na listagem.
# Defina MONITOR_PI_FOCUS_URL com a URL para focar só nela a cada ciclo.
FOCUS_URL: Optional[str] = (os.environ.get("MONITOR_PI_FOCUS_URL") or "").strip() or None

# Seletores (classes podem variar com build; usar * quando estável)
ACCORDION_BTN = "button.szh-accordion__item-btn"
FLIGHT_BLOCK = "[class*='produtoIdaVolta_div_sections']"
SECTION_DATA = "[class*='produtoIdaVolta_section_data']"
# Rota (ex.: VCP -> MCO) pode estar em span com idaVolta ou no texto do bloco
ROUTE_SPAN = "[class*='produtoIdaVolta_section_span_texto__idaVolta']"
PRICE_SPAN = "[class*='produtoIdaVolta_section_preco']"
# Header do item do acordeão (promos 2 em 1: origem + trechos 1. Lima, 2. Cusco + preço)
ACCORDION_HEADER_CITY = "[class*='detalhesPublicacao_ion_content_accordion_item_div_aeroportos_span_city']"
ACCORDION_HEADER_PRICE = "[class*='detalhesPublicacao_ion_content_accordion_item_div_aeroportos_span_valor']"

# Códigos que devem ser normalizados para IATA (ex.: RIO -> GIG)
AIRPORT_CODE_NORMALIZE = {"RIO": "GIG", "SAO": "GRU", "BHZ": "CNF", "MIL": "MXP", "NYC": "JFK"}

# Nomes de cidades (como aparecem no header do acordeão) -> IATA (promos 2 em 1 / múltiplos destinos)
CITY_TO_IATA = {
    "são paulo": "GRU", "sao paulo": "GRU", "são paulo ": "GRU",
    "rio de janeiro": "GIG", "rio": "GIG",
    "belo horizonte": "CNF", "bh": "CNF",
    "lima": "LIM", "cusco": "CUZ", "cusco ": "CUZ",
    "buenos aires": "EZE", "santiago": "SCL", "santiago ": "SCL",
    "cartagena": "CTG", "bogotá": "BOG", "bogota": "BOG", "medellin": "MDE", "medellín": "MDE",
    "san andres": "ADZ", "santa marta": "SMR",
    "cancún": "CUN", "cancun": "CUN", "cancún ": "CUN",
    "punta cana": "PUJ", "kingston": "KIN", "jamaica": "KIN",
    "aruba": "AUA", "oranjestad": "AUA",
    "lisboa": "LIS", "lisboa ": "LIS", "portugal": "LIS",
    "madri": "MAD", "madrid": "MAD",
    "milão": "MXP", "milao": "MXP", "milão ": "MXP", "veneza": "VCE", "venezia": "VCE",
    "genebra": "GVA", "zurique": "ZRH", "zurique ": "ZRH", "suíça": "GVA",
    "toronto": "YYZ", "canadá": "YYZ", "canada": "YYZ",
    "bariloche": "BRC", "mendoza": "MDZ", "cordoba": "COR", "córdoba": "COR",
    "el calafate": "FTE", "ushuaia": "USH", "salta": "SLA", "rosario": "ROS", "jujuy": "JUJ", "mendo": "MDZ",
}


def normalize_airport_code(code: str) -> str:
    """Retorna o código IATA normalizado (ex.: RIO -> GIG)."""
    if not code or not (code := (code or "").strip().upper()):
        return code or ""
    return AIRPORT_CODE_NORMALIZE.get(code, code)


def city_name_to_iata(name: str) -> str:
    """Converte nome de cidade (ex.: 'Lima', 'São Paulo') em código IATA para promos 2 em 1."""
    if not name or not (s := (name or "").strip().lower()):
        return ""
    # Remove prefixos "1." "2." etc.
    s = re.sub(r"^\d+\.\s*", "", s).strip()
    return CITY_TO_IATA.get(s, s.upper() if len(s) == 3 else "")


def insert_raw(
    origin: str,
    destination: str,
    dep: date,
    ret: Optional[date],
    price_brl: int,
    payload: dict,
) -> None:
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
                ),
            )
    finally:
        conn.close()


def get_already_scanned_promo_urls() -> Set[str]:
    """Retorna o conjunto de URLs de promoção que já têm registros em flight_prices_raw."""
    conn = psycopg2.connect(**DB_CONFIG)
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT DISTINCT payload->>'promo_url' AS promo_url
                FROM flight_prices_raw
                WHERE source = %s AND payload->>'promo_url' IS NOT NULL AND payload->>'promo_url' != ''
                """,
                (SOURCE_NAME,),
            )
            return {row[0] for row in cur.fetchall() if row[0]}
    finally:
        conn.close()


def parse_date_dd_mm_yy(s: str) -> Optional[date]:
    """Converte '30/05/26' em date."""
    if not s or not s.strip():
        return None
    s = s.strip()
    m = re.match(r"(\d{1,2})/(\d{1,2})/(\d{2,4})", s)
    if not m:
        return None
    d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
    if y < 100:
        y += 2000
    try:
        return date(y, mo, d)
    except ValueError:
        return None


def parse_price_brl(s: str) -> int:
    """Extrai valor inteiro de 'R$ 2.394' ou 'R$ 2.394 +'."""
    if not s:
        return 0
    digits = re.sub(r"[^\d]", "", s)
    return int(digits) if digits else 0


def parse_origin_destination(text: str) -> tuple:
    """Extrai códigos IATA do texto (ex.: 'VCP ... MCO' -> ('VCP','MCO'))."""
    if not text:
        return ("", "")
    codes = re.findall(r"\b[A-Z]{3}\b", text.upper())
    if len(codes) >= 2:
        return (codes[0], codes[1])
    if len(codes) == 1:
        return (codes[0], "")
    return ("", "")


def extract_promo_links(page) -> List[Dict[str, str]]:
    """
    Na página de listagem, extrai todas as promoções dos cards do grid.
    Suporta grid "Últimas Publicações" (cardsUltimasPublicacoes) e "Promo" (cardsPromo).
    Inclui links /promocao-... e /passagens-...
    """
    page.goto(URL, wait_until="domcontentloaded", timeout=60000)
    # Grid de cards: página usa cardsUltimasPublicacoes_container_grid (e _grid_item)
    page.wait_for_selector('[class*="cardsUltimasPublicacoes_container_grid"]', timeout=60000)
    page.wait_for_timeout(2000)

    items = []
    seen_urls: Set[str] = set()
    # Cada card: class cardsUltimasPublicacoes_container_grid_item__vPPpq
    card_items = page.query_selector_all('[class*="cardsUltimasPublicacoes_container_grid_item"]')
    if not card_items:
        # Fallback se a página usar o grid "cardsPromo" em outro build
        card_items = page.query_selector_all('[class*="cardsPromo_gridContainer_grid_item"]')
    for card in card_items:
        a = card.query_selector('a[href^="/"]')
        if not a:
            continue
        href = (a.get_attribute("href") or "").strip()
        if not href or not href.startswith("/"):
            continue
        url = urljoin(BASE_URL, href)
        if url in seen_urls:
            continue
        seen_urls.add(url)
        title_el = a.query_selector("h5")
        title = (title_el.inner_text() if title_el else "").strip()
        items.append({"title": title or url, "url": url})
    return items


def _extract_flights_from_blocks(blocks, promo_url: str, promo_title: str) -> List[Dict[str, Any]]:
    """Extrai lista de voos a partir de uma lista de elementos (blocos produtoIdaVolta)."""
    flights = []
    for block in blocks:
        try:
            # Datas: primeiro = ida, segundo = volta
            date_els = block.query_selector_all(SECTION_DATA)
            dep_date = None
            ret_date = None
            if len(date_els) >= 1:
                dep_date = parse_date_dd_mm_yy(date_els[0].inner_text())
            if len(date_els) >= 2:
                ret_date = parse_date_dd_mm_yy(date_els[1].inner_text())

            # Rota: span com idaVolta (VCP MCO) ou todo o texto do bloco
            route_el = block.query_selector(ROUTE_SPAN)
            route_text = (route_el.inner_text() if route_el else "").strip()
            if not route_text:
                route_text = (block.inner_text() or "").strip()
            origin, destination = parse_origin_destination(route_text)

            # Preço
            price_el = block.query_selector(PRICE_SPAN)
            price_text = (price_el.inner_text() if price_el else "").strip()
            price_brl = parse_price_brl(price_text)

            if origin and destination and dep_date and price_brl > 0:
                flights.append({
                    "origin": origin,
                    "destination": destination,
                    "departure_date": dep_date,
                    "return_date": ret_date,
                    "price": price_brl,
                    "price_text": price_text,
                    "promo_url": promo_url,
                    "promo_title": promo_title,
                })
        except Exception as e:
            continue
    return flights


def _extract_flights_from_accordion_header(
    item, promo_url: str, promo_title: str
) -> List[Dict[str, Any]]:
    """
    Quando o item do acordeão não tem blocos produtoIdaVolta (promo 2 em 1 com
    Trechos: 1. Lima, 2. Cusco), extrai origem, destinos e preço do próprio header.
    """
    flights = []
    try:
        btn = item.query_selector(ACCORDION_BTN)
        if not btn:
            return []
        city_els = btn.query_selector_all(ACCORDION_HEADER_CITY)
        if len(city_els) < 2:
            return []
        # Primeiro span = origem; demais = destinos (podem ter "1. Lima", "2. Cusco")
        origin_text = (city_els[0].inner_text() or "").strip()
        origin = city_name_to_iata(origin_text)
        if not origin and len(origin_text) == 3:
            origin = normalize_airport_code(origin_text.upper())
        if not origin:
            return []

        price_el = btn.query_selector(ACCORDION_HEADER_PRICE)
        price_text = (price_el.inner_text() if price_el else "").strip()
        price_brl = parse_price_brl(price_text)
        if price_brl <= 0:
            return []

        # Placeholder quando a data não vem no header (promo "a partir de")
        placeholder_date = date(2026, 1, 1)

        for i in range(1, len(city_els)):
            dest_text = (city_els[i].inner_text() or "").strip()
            dest = city_name_to_iata(dest_text)
            if not dest and len(dest_text) == 3:
                dest = normalize_airport_code(dest_text.upper())
            if not dest:
                continue
            flights.append({
                "origin": origin,
                "destination": dest,
                "departure_date": placeholder_date,
                "return_date": None,
                "price": price_brl,
                "price_text": price_text,
                "promo_url": promo_url,
                "promo_title": promo_title,
            })
    except Exception:
        pass
    return flights


def expand_accordions_and_extract_flights(page, promo_url: str, promo_title: str) -> List[Dict[str, Any]]:
    """
    Abre a página da promoção. Para cada item do acordeão (cada origem→destino),
    expande o painel, espera o conteúdo e extrai todos os blocos produtoIdaVolta.
    """
    page.goto(promo_url, wait_until="domcontentloaded", timeout=30000)
    page.wait_for_timeout(2000)

    # Container do acordeão (vários itens: São Paulo→Punta Cana, Rio→Punta Cana, etc.)
    accordion = page.query_selector("#accordionElement")
    if not accordion:
        accordion = page.query_selector("[data-szh-adn]")
    if not accordion:
        return []

    all_flights = []
    # Cada item do acordeão é uma rota (origem → destino)
    items = accordion.query_selector_all(".szh-accordion__item")
    for idx, item in enumerate(items):
        try:
            btn = item.query_selector(ACCORDION_BTN)
            if not btn:
                continue
            btn.scroll_into_view_if_needed()
            page.wait_for_timeout(200)
            btn.click()
            # Conteúdo do painel pode carregar após o click
            page.wait_for_timeout(1000)
            # Buscar blocos de voo apenas dentro deste item
            blocks = item.query_selector_all(FLIGHT_BLOCK)
            if blocks:
                all_flights.extend(_extract_flights_from_blocks(blocks, promo_url, promo_title))
            else:
                # Promo 2 em 1: sem blocos produtoIdaVolta; extrair do header (origem + trechos 1. Lima, 2. Cusco)
                all_flights.extend(_extract_flights_from_accordion_header(item, promo_url, promo_title))
        except Exception:
            continue

    return all_flights


def run_once(page) -> int:
    """
    Uma varredura: busca promoções na listagem, filtra as já cadastradas,
    processa só as novas e retorna quantas ofertas foram salvas.
    """
    print(">>> Buscando lista de promoções...")
    promos = extract_promo_links(page)
    print(f">>> Total na página: {len(promos)}")

    already = get_already_scanned_promo_urls()
    to_scan = [p for p in promos if p["url"] not in already]
    print(f">>> Já cadastradas (ignoradas): {len(promos) - len(to_scan)} | Novas a varrer: {len(to_scan)}")

    if not to_scan:
        return 0

    total_saved = 0
    for i, promo in enumerate(to_scan):
        url = promo["url"]
        title = promo["title"]
        print(f"\n>>> [{i+1}/{len(to_scan)}] Abrindo: {title[:50]}...")
        try:
            flights = expand_accordions_and_extract_flights(page, url, title)
            for f in flights:
                payload = {
                    "promo_url": url,
                    "promo_title": title,
                    "price_text": f.get("price_text", ""),
                    "source": SOURCE_NAME,
                }
                origin_n = normalize_airport_code(f["origin"])
                dest_n = normalize_airport_code(f["destination"])
                insert_raw(
                    origin_n,
                    dest_n,
                    f["departure_date"],
                    f.get("return_date"),
                    f["price"],
                    payload,
                )
                total_saved += 1
            if flights:
                print(f"    -> {len(flights)} oferta(s) extraída(s) e salva(s).")
        except Exception as e:
            print(f"    !! Erro: {e}")

    return total_saved


def _parse_single_url_arg() -> Optional[str]:
    """Retorna a URL passada em --url <url>, ou None."""
    argv = sys.argv
    if "--url" not in argv:
        return None
    i = argv.index("--url")
    if i + 1 < len(argv):
        return argv[i + 1].strip()
    return None


def run_once_single_url(page, url: str) -> int:
    """
    Executa uma única varredura na URL informada (sem listagem).
    Útil para repassar uma promo que não trouxe todos os voos.
    """
    if not url or not url.startswith("http"):
        print(">>> URL inválida.")
        return 0
    print(f">>> Varrendo apenas: {url[:70]}...")
    title = "Promo (URL única)"
    flights = expand_accordions_and_extract_flights(page, url, title)
    total_saved = 0
    for f in flights:
        payload = {
            "promo_url": url,
            "promo_title": title,
            "price_text": f.get("price_text", ""),
            "source": SOURCE_NAME,
        }
        origin_n = normalize_airport_code(f["origin"])
        dest_n = normalize_airport_code(f["destination"])
        insert_raw(
            origin_n,
            dest_n,
            f["departure_date"],
            f.get("return_date"),
            f["price"],
            payload,
        )
        total_saved += 1
    print(f">>> Ofertas extraídas e salvas: {total_saved}")
    return total_saved


def main():
    single_url = _parse_single_url_arg()
    run_as_service = "--once" not in sys.argv and not single_url

    print("======================================")
    if single_url:
        print(">>> Monitor Passagens Imperdíveis (uma URL)")
        print("======================================")
    elif run_as_service:
        print(">>> Monitor Passagens Imperdíveis (modo serviço)")
        print("======================================")
        print(f">>> Intervalo entre varreduras: {SCAN_INTERVAL_MINUTES} min")
        if FOCUS_URL:
            print(f">>> Modo teste: varredura apenas em {FOCUS_URL[:60]}...")
        print(">>> Ctrl+C para encerrar.\n")
    else:
        print(">>> Monitor Passagens Imperdíveis (uma varredura)")
        print("======================================")

    while True:
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                page = browser.new_page()
                page.set_default_timeout(30000)
                try:
                    if single_url:
                        saved = run_once_single_url(page, single_url)
                    elif run_as_service and FOCUS_URL:
                        saved = run_once_single_url(page, FOCUS_URL)
                    else:
                        saved = run_once(page)
                    print(f"\n>>> Varredura concluída. Total cadastrado: {saved}")
                finally:
                    browser.close()
        except KeyboardInterrupt:
            print("\n>>> Encerrando serviço (Ctrl+C).")
            break
        except Exception as e:
            print(f">>> Erro na varredura: {e}")

        if not run_as_service:
            break

        print(f">>> Próxima varredura em {SCAN_INTERVAL_MINUTES} min...")
        try:
            time.sleep(SCAN_INTERVAL_MINUTES * 60)
        except KeyboardInterrupt:
            print("\n>>> Encerrando serviço (Ctrl+C).")
            break

    print(">>> Script finalizado.")


if __name__ == "__main__":
    main()
