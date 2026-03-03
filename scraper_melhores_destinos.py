# -*- coding: utf-8 -*-
"""
Motor de scraping Melhores Destinos (melhoresdestinos.com.br).

Fluxo:
  1) Página inicial: extrai todos os cards (li.post-card-destaque) da página.
  2) Para cada link de promo: abre a página e extrai trechos em #trechos-promo (.ls-trechos-linha).
  3) Para cada trecho: clica em "ver datas" (.lt3) e extrai voos em .lista-datas-item.

Salva em flight_prices_raw com source='melhores_destinos'.
"""
import json
import re
import sys
import time
from datetime import date
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin

import psycopg2
from playwright.sync_api import sync_playwright

BASE_URL = "https://www.melhoresdestinos.com.br"
HOME_URL = BASE_URL + "/"

SOURCE_NAME = "melhores_destinos"
CURRENCY = "BRL"

DB_CONFIG = {
    "host": "localhost",
    "port": 5432,
    "dbname": "postgres",
    "user": "postgres",
    "password": "290535",
}

# Timeouts e pausas
PAGE_LOAD_TIMEOUT = 30000
WAIT_AFTER_CLICK_MS = 1500
WAIT_VER_DATAS_MS = 2500

# Códigos do site que devem ser normalizados para IATA (ex.: Melhores Destinos usa BHZ = CNF, RIO = GIG, SAO = GRU)
AIRPORT_CODE_NORMALIZE = {"BHZ": "CNF", "RIO": "GIG", "SAO": "GRU"}

# Nomes/labels que indicam aeroporto quando o site mostra código ou só o nome
NAME_TO_CODE_HINTS = [
    ("BELO HORIZONTE", "CNF"),
    ("BHZ", "CNF"),
    ("CONFINS", "CNF"),
    ("RIO DE JANEIRO", "GIG"),
    ("SÃO PAULO", "GRU"),
    ("SAO PAULO", "GRU"),
    ("GUARULHOS", "GRU"),
]


def normalize_airport_code(code: str) -> str:
    """Retorna o código IATA normalizado (ex.: BHZ -> CNF)."""
    if not code or not (code := code.strip()):
        return code
    return AIRPORT_CODE_NORMALIZE.get(code.upper(), code.upper())


def code_from_name_or_code(name_or_code: str) -> str:
    """Se name_or_code for BHZ ou contiver 'Belo Horizonte' etc., retorna CNF; senão normaliza como código."""
    if not name_or_code or not (s := name_or_code.strip().upper()):
        return ""
    if s in AIRPORT_CODE_NORMALIZE:
        return AIRPORT_CODE_NORMALIZE[s]
    for hint, code in NAME_TO_CODE_HINTS:
        if hint in s:
            return code
    return s if len(s) == 3 else ""


def parse_price_brl(s: str) -> int:
    """Extrai valor inteiro de 'R$ 4.517' ou 'R$ 3.843'."""
    if not s:
        return 0
    digits = re.sub(r"[^\d]", "", s)
    return int(digits) if digits else 0


def parse_date_dd_mm(s: str, year: Optional[int] = None) -> Optional[date]:
    """Converte '11/3' ou '21/3' em date. Usa year atual se não informado."""
    if not s or not s.strip():
        return None
    s = re.sub(r"\s+", " ", s.strip()).split()[0]
    m = re.match(r"(\d{1,2})/(\d{1,2})", s)
    if not m:
        return None
    d, mo = int(m.group(1)), int(m.group(2))
    y = year or date.today().year
    try:
        return date(y, mo, d)
    except ValueError:
        return None


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


# ---------------------------------------------------------------------------
# 1) Cards da página inicial
# ---------------------------------------------------------------------------
def extract_home_cards(page) -> List[Dict[str, str]]:
    """Extrai todos os cards de ofertas da homepage (li.post-card-destaque em qualquer lista)."""
    print("    Carregando homepage...")
    page.goto(HOME_URL, wait_until="domcontentloaded", timeout=PAGE_LOAD_TIMEOUT)
    print("    Aguardando conteúdo (2s)...")
    page.wait_for_timeout(2000)

    cards = []
    # Busca todos os li.post-card-destaque da página (destaques principais + outros cards)
    all_cards = page.query_selector_all("li.post-card-destaque")
    print(f"    Encontrados {len(all_cards)} elemento(s) li.post-card-destaque na página.")
    for i, li in enumerate(all_cards):
        try:
            a = li.query_selector("a[href]")
            if not a:
                print(f"    Card {i+1}: sem link, ignorado.")
                continue
            href = (a.get_attribute("href") or "").strip()
            if not href:
                print(f"    Card {i+1}: href vazio, ignorado.")
                continue
            url = urljoin(BASE_URL, href) if not href.startswith("http") else href

            img = li.query_selector("img.imagedestaque")
            img_src = (img.get_attribute("src") or "").strip() if img else ""
            if img_src and not img_src.startswith("http"):
                img_src = urljoin(BASE_URL, img_src)

            h2 = li.query_selector("h2")
            title = (h2.inner_text().strip() if h2 else "") or url

            cards.append({"url": url, "title": title, "image": img_src})
            print(f"    Card {i+1}: {title[:50]}...")
        except Exception as ex:
            print(f"    Card {i+1}: erro ao extrair - {ex}")
            continue
    return cards


# ---------------------------------------------------------------------------
# 2) Trechos na página da promo (#trechos-promo)
# ---------------------------------------------------------------------------
def extract_trechos_from_promo_page(page) -> List[Dict[str, Any]]:
    """
    Na página da promoção, extrai todos os div.ls-trechos-linha dentro de #trechos-promo.
    Retorna lista de dicts com from, to, from_name, to_name, price_text, price.
    Não guarda referência ao elemento (para não ficar stale após navegação).
    """
    trechos = []
    container = page.query_selector("#trechos-promo")
    if not container:
        print("    #trechos-promo não encontrado nesta página.")
        return trechos

    rows = container.query_selector_all("div.ls-trechos-linha")
    print(f"    Encontrados {len(rows)} trecho(s) na promo.")
    for el in rows:
        try:
            from_name = (el.get_attribute("from_name") or "").strip()
            to_name = (el.get_attribute("to_name") or "").strip()
            # Site pode usar "from"/"to" ou data-from/data-to; fallback: inferir do nome (ex.: Belo Horizonte/BHZ -> CNF)
            raw_from = (
                (el.get_attribute("from") or "")
                or (el.get_attribute("data-from") or "")
                or (el.get_attribute("data-origin") or "")
            ).strip()
            raw_to = (
                (el.get_attribute("to") or "")
                or (el.get_attribute("data-to") or "")
                or (el.get_attribute("data-destination") or "")
            ).strip()
            from_code = normalize_airport_code(raw_from) if raw_from else code_from_name_or_code(from_name)
            to_code = normalize_airport_code(raw_to) if raw_to else code_from_name_or_code(to_name)

            lt2 = el.query_selector(".lt2")
            price_text = (lt2.inner_text().strip() if lt2 else "") or ""
            price = parse_price_brl(price_text)

            trechos.append({
                "from": from_code,
                "to": to_code,
                "from_name": from_name,
                "to_name": to_name,
                "price_text": price_text,
                "price": price,
            })
        except Exception:
            continue
    return trechos


def get_lt3_for_trecho_index(page, index: int):
    """Retorna o elemento .lt3 do trecho no índice dado (para clicar em 'ver datas')."""
    container = page.query_selector("#trechos-promo")
    if not container:
        return None
    rows = container.query_selector_all("div.ls-trechos-linha")
    if index < 0 or index >= len(rows):
        return None
    return rows[index].query_selector(".lt3")


# ---------------------------------------------------------------------------
# 3) Clicar em "ver datas" e extrair .lista-datas-item
# ---------------------------------------------------------------------------
def extract_datas_items_from_page(page) -> List[Dict[str, Any]]:
    """Extrai todos os .lista-datas-item da página atual."""
    items = []
    for el in page.query_selector_all("div.lista-datas-item"):
        try:
            mc3 = el.query_selector(".mc3")
            mc4 = el.query_selector(".mc4")
            mc5 = el.query_selector(".mc5")
            mc6_img = el.query_selector(".mc6 img")
            mc7 = el.query_selector(".mc7")
            mc8 = el.query_selector(".mc8")

            dep_text = (mc3.inner_text().strip() if mc3 else "") or ""
            ret_text = (mc4.inner_text().strip() if mc4 else "") or ""
            days_text = (mc5.inner_text().strip() if mc5 else "") or ""
            airline_src = (mc6_img.get_attribute("src") or "") if mc6_img else ""
            price_text = (mc7.inner_text().strip() if mc7 else "") or ""
            ver_voos_link = None
            if mc8:
                try:
                    ver_voos_link = mc8.evaluate(
                        "el => { const a = el.querySelector('a') || el.closest('a'); return a ? a.href : null; }"
                    )
                except Exception:
                    pass

            dep_date = parse_date_dd_mm(dep_text)
            ret_date = parse_date_dd_mm(ret_text)
            price = parse_price_brl(price_text)

            items.append({
                "departure_date": dep_date,
                "return_date": ret_date,
                "dep_text": dep_text.strip(),
                "ret_text": ret_text.strip(),
                "days": days_text.strip(),
                "airline_src": airline_src,
                "price": price,
                "price_text": price_text,
                "ver_voos_url": ver_voos_link,
            })
        except Exception:
            continue
    return items


def extract_datas_items_after_click(page, trecho_lt3, _promo_url: str, trecho_label: str = "") -> List[Dict[str, Any]]:
    """
    Clica no .lt3 (ver datas) do trecho. Se a página navegar (segundo link), extrai
    .lista-datas-item na nova página e volta. Se não navegar (modal/inline), extrai na própria página.
    """
    items = []
    if not trecho_lt3:
        print(f"      [ver datas] elemento .lt3 não encontrado.")
        return items

    url_before = page.url
    try:
        trecho_lt3.scroll_into_view_if_needed()
        page.wait_for_timeout(300)
        print(f"      Clicando em 'ver datas' {trecho_label}...")
        trecho_lt3.click()
    except Exception as ex:
        print(f"      Erro ao clicar em ver datas: {ex}")
    print(f"      Aguardando carregamento ({WAIT_VER_DATAS_MS}ms)...")
    page.wait_for_timeout(WAIT_VER_DATAS_MS)

    items = extract_datas_items_from_page(page)
    print(f"      Extraídos {len(items)} item(ns) de datas/voos.")

    if page.url != url_before:
        print("      Voltando à página da promo...")
        page.go_back(wait_until="domcontentloaded", timeout=PAGE_LOAD_TIMEOUT)
        page.wait_for_timeout(1000)

    return items


def extract_sublinks_from_conteudo_post(page) -> List[str]:
    """
    Se a página não tem #trechos-promo, pode ser um post com links no .conteudo-post.
    Extrai URLs de promo (href que contém /promocao/) para abrir depois.
    """
    urls = []
    conteudo = page.query_selector(".conteudo-post")
    if not conteudo:
        return urls
    for a in conteudo.query_selector_all('a[href*="/promocao/"]'):
        try:
            href = (a.get_attribute("href") or "").strip()
            if not href:
                continue
            full = urljoin(BASE_URL, href) if not href.startswith("http") else href
            if full not in urls and "melhoresdestinos.com.br" in full and "/promocao/" in full:
                urls.append(full)
        except Exception:
            continue
    return urls


def process_page_with_trechos(
    page, promo_url: str, promo_title: str, promo_image: str
) -> int:
    """
    Assume que a página atual já tem #trechos-promo. Extrai trechos, clica em
    'ver datas' em cada um, extrai voos e insere no banco. Retorna total salvo.
    """
    trechos = extract_trechos_from_promo_page(page)
    if not trechos:
        return 0

    saved = 0
    for idx, t in enumerate(trechos):
        origin = normalize_airport_code((t.get("from") or "").strip())
        destination = normalize_airport_code((t.get("to") or "").strip())
        if not origin or not destination:
            print(f"    Trecho {idx+1}: origem/destino vazio, pulando.")
            continue

        trecho_label = f"({origin} → {destination})"
        print(f"    Trecho {idx+1}/{len(trechos)}: {origin} → {destination} ...")
        lt3 = get_lt3_for_trecho_index(page, idx)
        datas_items = extract_datas_items_after_click(page, lt3, promo_url, trecho_label)

        inserted_this_trecho = 0
        insert_errors = 0
        for item in datas_items:
            dep = item.get("departure_date")
            ret = item.get("return_date")
            price = item.get("price") or 0
            if not dep or price <= 0:
                continue
            payload = {
                "promo_url": promo_url,
                "promo_title": promo_title,
                "promo_image": promo_image,
                "from_name": t.get("from_name"),
                "to_name": t.get("to_name"),
                "dep_text": item.get("dep_text"),
                "ret_text": item.get("ret_text"),
                "days": item.get("days"),
                "airline_src": item.get("airline_src"),
                "ver_voos_url": item.get("ver_voos_url"),
                "source": SOURCE_NAME,
            }
            try:
                insert_raw(origin, destination, dep, ret, price, payload)
                saved += 1
                inserted_this_trecho += 1
            except Exception as e:
                insert_errors += 1
                print(f"      !! Erro ao inserir oferta (origem={origin}, dest={destination}, dep={dep}, preço={price}): {e}")
        if inserted_this_trecho:
            print(f"      Inseridas {inserted_this_trecho} oferta(s) no banco para este trecho.")
        if insert_errors:
            print(f"      Alerta: {insert_errors} oferta(s) não puderam ser inseridas (ver erros acima).")

        # Se abriu modal, fechar para o próximo trecho (tentar ESC ou clicar fora)
        page.wait_for_timeout(500)
        try:
            page.keyboard.press("Escape")
            page.wait_for_timeout(300)
        except Exception:
            pass

    return saved


def process_promo_page(page, promo_url: str, promo_title: str, promo_image: str) -> int:
    """
    Abre a página da promo. Se tiver #trechos-promo, processa direto. Se não,
    procura links no .conteudo-post e abre cada um para processar trechos + ver datas.
    Retorna quantidade de ofertas salvas.
    """
    print("    Abrindo página da promo...")
    page.goto(promo_url, wait_until="domcontentloaded", timeout=PAGE_LOAD_TIMEOUT)
    print("    Aguardando página (2s)...")
    page.wait_for_timeout(2000)

    # Página tem trechos diretos?
    container = page.query_selector("#trechos-promo")
    if container:
        print("    Página com trechos diretos. Processando...")
        return process_page_with_trechos(page, promo_url, promo_title, promo_image)

    # Senão, pode ser post com links para outras promos
    sublinks = extract_sublinks_from_conteudo_post(page)
    if not sublinks:
        print("    Nenhum trecho nem links de promo no post, pulando.")
        return 0

    print(f"    Post com {len(sublinks)} link(s) de promo. Abrindo cada um...")
    total_saved = 0
    for i, sub_url in enumerate(sublinks):
        print(f"    [{i+1}/{len(sublinks)}] Abrindo link do post: {sub_url[:60]}...")
        try:
            page.goto(sub_url, wait_until="domcontentloaded", timeout=PAGE_LOAD_TIMEOUT)
            page.wait_for_timeout(2000)
            n = process_page_with_trechos(page, sub_url, promo_title or sub_url, promo_image)
            total_saved += n
            if n:
                print(f"        -> {n} oferta(s) salva(s) neste link.")
        except Exception as e:
            print(f"        !! Erro ao processar link: {e}")
    return total_saved


def run_once(page, max_promos: Optional[int] = None) -> int:
    """
    Uma varredura: homepage -> cards -> para cada promo abre e extrai trechos + ver datas.
    max_promos: limita quantas promoções processar (None = todas).
    """
    print(">>> Buscando cards na homepage Melhores Destinos...")
    cards = extract_home_cards(page)
    print(f">>> Total de cards extraídos: {len(cards)}")

    if not cards:
        print(">>> Nenhum card encontrado. Verifique se a página carregou corretamente.")
        return 0

    if max_promos is not None:
        cards = cards[:max_promos]
        print(f">>> Processando no máximo {max_promos} promoção(ões).")

    total_saved = 0
    for i, card in enumerate(cards):
        url = card.get("url") or ""
        title = (card.get("title") or "")[:60]
        img = card.get("image") or ""
        print(f"\n>>> [{i+1}/{len(cards)}] Promo: {title}...")
        print(f"    URL: {url[:70]}...")
        try:
            n = process_promo_page(page, url, title, img)
            total_saved += n
            if n:
                print(f"    -> {n} oferta(s) salva(s).")
            else:
                print("    -> Nenhuma oferta nova salva (já existentes ou sem dados).")
        except Exception as e:
            print(f"    !! Erro: {e}")

    return total_saved


def main():
    max_promos = None
    if "--max" in sys.argv:
        try:
            i = sys.argv.index("--max")
            if i + 1 < len(sys.argv):
                max_promos = int(sys.argv[i + 1])
        except (ValueError, IndexError):
            pass

    print("======================================")
    print(">>> Motor Melhores Destinos")
    print("======================================")
    if max_promos:
        print(f">>> Limite: {max_promos} promoções")
    print(">>> Use --max N para limitar a N promoções.\n")

    with sync_playwright() as p:
        print(">>> Iniciando browser...")
        browser = p.chromium.launch(headless=False)
        page = browser.new_page()
        page.set_default_timeout(PAGE_LOAD_TIMEOUT)
        try:
            saved = run_once(page, max_promos=max_promos)
            print(f"\n>>> Total de ofertas salvas nesta varredura: {saved}")
            if saved == 0:
                print(">>> Alerta: Nenhuma oferta foi inserida. Verifique erros acima, conexão com o banco ou se a página extraiu dados.")
        finally:
            print(">>> Fechando browser...")
            browser.close()

    print(">>> Script finalizado.")


if __name__ == "__main__":
    main()
