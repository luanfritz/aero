# -*- coding: utf-8 -*-
"""
Processo separado: desativa ofertas antigas para manter promoções voláteis sob controle.

- Garante a coluna scraped_at em flight_prices_raw (DEFAULT now()).
- Remove registros em flight_prices_raw com mais de N dias (padrão 3).
- Pode ser agendado via cron/tarefa agendada.

Uso:
  python deactivate_old_offers.py
  python deactivate_old_offers.py --days 5
  DAYS_OFFER_ACTIVE=7 python deactivate_old_offers.py
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import psycopg2

try:
    import main
    DB_CONFIG = main.DB_CONFIG
except ImportError:
    DB_CONFIG = {
        "host": os.environ.get("PGHOST", "localhost"),
        "port": int(os.environ.get("PGPORT", "5432")),
        "dbname": os.environ.get("PGDATABASE", "postgres"),
        "user": os.environ.get("PGUSER", "postgres"),
        "password": os.environ.get("PGPASSWORD", ""),
    }

# Quantos dias uma oferta permanece ativa antes de ser removida (padrão 3)
DEFAULT_DAYS = 3
ENV_DAYS = "DAYS_OFFER_ACTIVE"
RAW_TIMESTAMP_COLUMN = "scraped_at"


def ensure_scraped_at_column(conn):
    """Cria a coluna scraped_at em flight_prices_raw se não existir (DEFAULT now())."""
    with conn.cursor() as cur:
        cur.execute("""
            SELECT 1 FROM information_schema.columns
            WHERE table_name = 'flight_prices_raw' AND column_name = %s
        """, (RAW_TIMESTAMP_COLUMN,))
        if cur.fetchone():
            return
        cur.execute("""
            ALTER TABLE flight_prices_raw
            ADD COLUMN IF NOT EXISTS scraped_at timestamptz DEFAULT now()
        """)
        conn.commit()
        print(">>> Coluna scraped_at criada/ajustada em flight_prices_raw (DEFAULT now()).")


def backfill_scraped_at_null(conn):
    """Preenche scraped_at = now() onde for NULL (evita apagar tudo no primeiro run)."""
    with conn.cursor() as cur:
        cur.execute("""
            UPDATE flight_prices_raw
            SET scraped_at = now()
            WHERE scraped_at IS NULL
        """)
        n = cur.rowcount
        conn.commit()
        if n:
            print(f">>> Backfill: {n} registro(s) com scraped_at definido como now().")


def delete_older_than_days(conn, days: int):
    """Remove de flight_prices_raw registros com scraped_at anterior a `days` dias."""
    with conn.cursor() as cur:
        cur.execute("""
            DELETE FROM flight_prices_raw
            WHERE scraped_at < now() - (%s * interval '1 day')
        """, (days,))
        n = cur.rowcount
        conn.commit()
        return n


def run(days: int = DEFAULT_DAYS, skip_backfill: bool = False, dry_run: bool = False):
    conn = psycopg2.connect(**DB_CONFIG)
    try:
        ensure_scraped_at_column(conn)
        if not skip_backfill:
            backfill_scraped_at_null(conn)
        if dry_run:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT COUNT(*) FROM flight_prices_raw
                    WHERE scraped_at < now() - (%s * interval '1 day')
                """, (days,))
                count = cur.fetchone()[0]
            print(f">>> [DRY-RUN] Seriam removidos {count} registro(s) com mais de {days} dia(s).")
            return count
        deleted = delete_older_than_days(conn, days)
        print(f">>> Removidos {deleted} registro(s) de flight_prices_raw com mais de {days} dia(s).")
        return deleted
    finally:
        conn.close()


def main_cli():
    parser = argparse.ArgumentParser(description="Desativa ofertas antigas em flight_prices_raw (por scraped_at).")
    parser.add_argument("--days", type=int, default=None,
                        help=f"Dias após os quais as ofertas são removidas (padrão: {DEFAULT_DAYS} ou env {ENV_DAYS})")
    parser.add_argument("--skip-backfill", action="store_true",
                        help="Não preencher scraped_at NULL com now() (use se já tiver dados com data)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Apenas mostrar quantos registros seriam removidos")
    args = parser.parse_args()
    days = args.days if args.days is not None else int(os.environ.get(ENV_DAYS, DEFAULT_DAYS))
    if days < 1:
        print(">>> --days deve ser >= 1.")
        sys.exit(1)
    print(f">>> Desativar ofertas com mais de {days} dia(s) (flight_prices_raw.scraped_at)")
    run(days=days, skip_backfill=args.skip_backfill, dry_run=args.dry_run)


if __name__ == "__main__":
    main_cli()
