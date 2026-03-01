# -*- coding: utf-8 -*-
"""
Cria as views daily_best_deals e daily_best_deals_ranked no banco.
Execute uma vez: python create_views.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import psycopg2

import main

SQL_FILE = os.path.join(os.path.dirname(__file__), "sql", "views_daily_best_deals.sql")


def main_run():
    with open(SQL_FILE, "r", encoding="utf-8") as f:
        sql = f.read()
    conn = psycopg2.connect(**main.DB_CONFIG)
    try:
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute(sql)
        print(">>> Views daily_best_deals e daily_best_deals_ranked criadas com sucesso.")
    finally:
        conn.close()


if __name__ == "__main__":
    main_run()
