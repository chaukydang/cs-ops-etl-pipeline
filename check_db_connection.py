from __future__ import annotations

import os
from pathlib import Path

import psycopg

from modules.core.env_loader import load_env_file

BASE_DIR = Path(__file__).resolve().parent
ENV_FILE = BASE_DIR / ".env"


def main() -> None:
    load_env_file(ENV_FILE)

    schema_name = os.getenv(
        "DB_SCHEMA",
        "Service",
    )

    with psycopg.connect(
        host=os.environ["DB_HOST"],
        port=int(
            os.getenv(
                "DB_PORT",
                "5432",
            )
        ),
        dbname=os.environ["DB_NAME"],
        user=os.environ["DB_USER"],
        password=os.environ["DB_PASSWORD"],
        sslmode=os.getenv(
            "DB_SSLMODE",
            "prefer",
        ),
        connect_timeout=15,
    ) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    current_database(),
                    current_user,
                    NOW(),
                    has_schema_privilege(
                        current_user,
                        %s,
                        'USAGE'
                    ),
                    has_schema_privilege(
                        current_user,
                        %s,
                        'CREATE'
                    )
                """,
                (
                    schema_name,
                    schema_name,
                ),
            )

            result = cursor.fetchone()

            if result is None:
                raise RuntimeError(
                    "Database không trả kết quả"
                )

            (
                database_name,
                user_name,
                server_time,
                can_use_schema,
                can_create_table,
            ) = result

            print(
                "================================"
            )
            print(
                "DATABASE CONNECTION SUCCESS"
            )
            print(
                "================================"
            )
            print(
                f"Database: {database_name}"
            )
            print(
                f"User: {user_name}"
            )
            print(
                f"Server time: {server_time}"
            )
            print(
                f"Schema: {schema_name}"
            )
            print(
                f"Can use schema: "
                f"{can_use_schema}"
            )
            print(
                f"Can create table: "
                f"{can_create_table}"
            )
            print(
                "================================"
            )


if __name__ == "__main__":
    main()