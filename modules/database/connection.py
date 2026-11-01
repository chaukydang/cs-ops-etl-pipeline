from __future__ import annotations

import os

import psycopg


class DatabaseConnectionFactory:
    @staticmethod
    def connect():
        required = ["DB_HOST", "DB_NAME", "DB_USER", "DB_PASSWORD"]
        missing = [name for name in required if not os.getenv(name, "").strip()]
        if missing:
            raise ValueError("Missing database variables: " + ", ".join(missing))

        return psycopg.connect(
            host=os.environ["DB_HOST"],
            port=int(os.getenv("DB_PORT", "5432")),
            dbname=os.environ["DB_NAME"],
            user=os.environ["DB_USER"],
            password=os.environ["DB_PASSWORD"],
            sslmode=os.getenv("DB_SSLMODE", "prefer"),
            connect_timeout=int(os.getenv("DB_CONNECT_TIMEOUT", "15")),
        )
