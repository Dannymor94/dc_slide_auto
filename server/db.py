import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

import psycopg
from models import CREATE_TABLES_SQL

DATABASE_URL = os.environ["DATABASE_URL"]


def get_conn():
    return psycopg.connect(DATABASE_URL)


def init_db():
    with get_conn() as conn:
        conn.execute(CREATE_TABLES_SQL)
        conn.commit()
