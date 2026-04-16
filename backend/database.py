import logging
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import psycopg2

from backend.config import DATABASE_URL

logger = logging.getLogger(__name__)


def _postgres_dsn(db_url: str) -> str:
    parsed = urlparse(db_url)
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    query.setdefault("sslmode", "require")
    return urlunparse(parsed._replace(query=urlencode(query)))


def get_db():
    return psycopg2.connect(_postgres_dsn(DATABASE_URL))


def rows_to_dicts(cursor, rows):
    cols = [col[0] for col in cursor.description]
    return [dict(zip(cols, row)) for row in rows]


def prepare_sql(conn, query: str) -> str:
    return query


def init_db():
    logger.info("PostgreSQL-only mode enabled; skipping local DB init.")
