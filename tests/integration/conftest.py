"""Integration tests need a real PostgreSQL; they are skipped unless DB_HOST is set."""

import os
import uuid

import pytest

psycopg = pytest.importorskip("psycopg")


@pytest.fixture()
def connection():
    if not os.getenv("DB_HOST"):
        pytest.skip("DB_HOST not set")

    conn = psycopg.connect(
        host=os.environ["DB_HOST"],
        port=int(os.getenv("DB_PORT", "5432")),
        dbname=os.environ["DB_NAME"],
        user=os.environ["DB_USER"],
        password=os.environ["DB_PASSWORD"],
        sslmode=os.getenv("DB_SSLMODE", "prefer"),
    )
    yield conn
    conn.rollback()
    conn.close()


@pytest.fixture()
def schema(connection):
    name = "it_" + uuid.uuid4().hex[:8]
    with connection.cursor() as cur:
        cur.execute(f'CREATE SCHEMA "{name}"')
    connection.commit()
    yield name
    with connection.cursor() as cur:
        cur.execute(f'DROP SCHEMA "{name}" CASCADE')
    connection.commit()
