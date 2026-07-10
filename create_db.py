"""One-off: create market_lens database if it does not exist."""
import os
from pathlib import Path

from dotenv import load_dotenv
import psycopg2

load_dotenv(Path(__file__).resolve().parent / ".env")
url = os.getenv("DATABASE_URL", "")
base = url.rstrip("/").rsplit("/", 1)[0]
conn = psycopg2.connect(base + "/postgres")
conn.autocommit = True
cur = conn.cursor()
cur.execute("SELECT 1 FROM pg_database WHERE datname = 'market_lens'")
if cur.fetchone() is None:
    cur.execute("CREATE DATABASE market_lens")
    print("Created database market_lens")
else:
    print("Database market_lens already exists")
cur.close()
conn.close()
