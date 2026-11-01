from __future__ import annotations

import csv
import glob
import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

from psycopg import sql


@dataclass(frozen=True)
class CsvDefinition:
    name: str
    table_name: str
    file_pattern: str
    enabled: bool = True
    recursive: bool = True


@dataclass(frozen=True)
class CsvProfile:
    file_path: Path
    original_headers: list
    database_headers: list
    row_count: int


class CsvDatabaseLoader:
    LOAD_METADATA_COLUMNS = [
        "_source_file",
        "_source_row_number",
        "_row_hash",
    ]

    ALL_METADATA_COLUMNS = [
        "_id",
        "_source_file",
        "_source_row_number",
        "_loaded_at",
        "_row_hash",
    ]

    def __init__(self, connection, project_root, schema_name):
        self.connection = connection
        self.project_root = Path(project_root).resolve()
        self.schema_name = str(schema_name).strip()
        if not self.schema_name:
            raise ValueError("schema_name cannot be empty")

    def initialize_table(self, source):
        file_path = self.find_latest_file(source)
        profile = self.profile_csv(file_path)

        try:
            with self.connection.cursor() as cursor:
                if self.table_exists(cursor, source.table_name):
                    table_columns = self.get_table_source_columns(
                        cursor,
                        source.table_name,
                    )
                    self.validate_columns(
                        source,
                        profile.database_headers,
                        table_columns,
                    )
                    self.connection.commit()
                    return {
                        "status": "already_exists",
                        "source": source.name,
                        "table": source.table_name,
                        "file": str(file_path),
                        "columns": len(profile.database_headers),
                    }

                system_columns = [
                    sql.SQL("{} BIGSERIAL PRIMARY KEY").format(
                        sql.Identifier("_id")
                    ),
                    sql.SQL("{} TEXT NOT NULL").format(
                        sql.Identifier("_source_file")
                    ),
                    sql.SQL("{} BIGINT NOT NULL").format(
                        sql.Identifier("_source_row_number")
                    ),
                    sql.SQL("{} TIMESTAMPTZ NOT NULL DEFAULT NOW()").format(
                        sql.Identifier("_loaded_at")
                    ),
                    sql.SQL("{} TEXT NOT NULL").format(
                        sql.Identifier("_row_hash")
                    ),
                ]

                source_columns = [
                    sql.SQL("{} TEXT").format(sql.Identifier(column_name))
                    for column_name in profile.database_headers
                ]

                cursor.execute(
                    sql.SQL("CREATE TABLE {}.{} ({})").format(
                        sql.Identifier(self.schema_name),
                        sql.Identifier(source.table_name),
                        sql.SQL(", ").join(system_columns + source_columns),
                    )
                )

                index_name = self.make_identifier(
                    "ix_{}_row_hash".format(source.table_name),
                    max_length=63,
                )
                cursor.execute(
                    sql.SQL("CREATE INDEX {} ON {}.{} ({})").format(
                        sql.Identifier(index_name),
                        sql.Identifier(self.schema_name),
                        sql.Identifier(source.table_name),
                        sql.Identifier("_row_hash"),
                    )
                )

            self.connection.commit()
        except Exception:
            self.connection.rollback()
            raise

        return {
            "status": "created",
            "source": source.name,
            "table": source.table_name,
            "file": str(file_path),
            "columns": len(profile.database_headers),
        }

    def load_table(self, source):
        file_path = self.find_latest_file(source)
        profile = self.profile_csv(file_path)

        try:
            with self.connection.cursor() as cursor:
                if not self.table_exists(cursor, source.table_name):
                    raise RuntimeError(
                        'Table "{}"."{}" does not exist. Run init first.'.format(
                            self.schema_name,
                            source.table_name,
                        )
                    )

                table_columns = self.get_table_source_columns(
                    cursor,
                    source.table_name,
                )
                self.validate_columns(
                    source,
                    profile.database_headers,
                    table_columns,
                )

                temp_table = self.make_identifier(
                    "tmp_{}".format(source.table_name),
                    max_length=63,
                )
                cursor.execute(
                    sql.SQL(
                        "CREATE TEMP TABLE {} "
                        "(LIKE {}.{} INCLUDING DEFAULTS) ON COMMIT DROP"
                    ).format(
                        sql.Identifier(temp_table),
                        sql.Identifier(self.schema_name),
                        sql.Identifier(source.table_name),
                    )
                )

                self.copy_csv_to_temp(cursor, source, profile, temp_table)
                temp_count = self.count_rows(cursor, temp_table, temporary=True)
                if temp_count != profile.row_count:
                    raise RuntimeError(
                        "Temporary count mismatch for {}: CSV={}, DB={}".format(
                            source.name,
                            profile.row_count,
                            temp_count,
                        )
                    )

                cursor.execute(
                    sql.SQL("TRUNCATE TABLE {}.{} RESTART IDENTITY").format(
                        sql.Identifier(self.schema_name),
                        sql.Identifier(source.table_name),
                    )
                )

                insert_columns = (
                    profile.database_headers + self.LOAD_METADATA_COLUMNS
                )
                cursor.execute(
                    sql.SQL(
                        "INSERT INTO {}.{} ({}) SELECT {} FROM {}"
                    ).format(
                        sql.Identifier(self.schema_name),
                        sql.Identifier(source.table_name),
                        sql.SQL(", ").join(
                            [sql.Identifier(name) for name in insert_columns]
                        ),
                        sql.SQL(", ").join(
                            [sql.Identifier(name) for name in insert_columns]
                        ),
                        sql.Identifier(temp_table),
                    )
                )

                final_count = self.count_rows(
                    cursor,
                    source.table_name,
                    temporary=False,
                )
                if final_count != profile.row_count:
                    raise RuntimeError(
                        "Final count mismatch for {}: CSV={}, DB={}".format(
                            source.name,
                            profile.row_count,
                            final_count,
                        )
                    )

            self.connection.commit()
        except Exception:
            self.connection.rollback()
            raise

        return {
            "status": "loaded",
            "source": source.name,
            "table": source.table_name,
            "file": str(file_path),
            "rows": profile.row_count,
            "columns": len(profile.database_headers),
        }

    def copy_csv_to_temp(self, cursor, source, profile, temp_table):
        copy_columns = profile.database_headers + self.LOAD_METADATA_COLUMNS
        copy_statement = sql.SQL("COPY {} ({}) FROM STDIN").format(
            sql.Identifier(temp_table),
            sql.SQL(", ").join(
                [sql.Identifier(name) for name in copy_columns]
            ),
        )

        with profile.file_path.open(
            "r",
            encoding="utf-8-sig",
            newline="",
        ) as file:
            reader = csv.reader(file)
            next(reader, None)

            with cursor.copy(copy_statement) as copy:
                for row_number, row in enumerate(reader, start=2):
                    values = self.normalize_row(
                        row,
                        len(profile.database_headers),
                        source,
                        row_number,
                    )
                    copy.write_row(
                        values
                        + [
                            profile.file_path.name,
                            row_number,
                            self.hash_row(values),
                        ]
                    )

    def find_latest_file(self, source):
        configured = Path(source.file_pattern)
        pattern = configured if configured.is_absolute() else self.project_root / configured
        candidates = [
            Path(file_name).resolve()
            for file_name in glob.glob(
                str(pattern),
                recursive=source.recursive,
            )
            if Path(file_name).is_file()
        ]
        if not candidates:
            raise FileNotFoundError(
                "No CSV found for {}: {}".format(
                    source.name,
                    source.file_pattern,
                )
            )
        return max(candidates, key=lambda path: path.stat().st_mtime)

    def profile_csv(self, file_path):
        with file_path.open(
            "r",
            encoding="utf-8-sig",
            newline="",
        ) as file:
            reader = csv.reader(file)
            original_headers = next(reader, None)
            if original_headers is None:
                raise ValueError("CSV has no header: {}".format(file_path))
            database_headers = self.normalize_headers(original_headers)
            row_count = sum(1 for _ in reader)

        return CsvProfile(
            file_path=file_path,
            original_headers=original_headers,
            database_headers=database_headers,
            row_count=row_count,
        )

    def table_exists(self, cursor, table_name):
        cursor.execute(
            """
            SELECT EXISTS (
                SELECT 1
                FROM information_schema.tables
                WHERE table_schema = %s
                  AND table_name = %s
            )
            """,
            (self.schema_name, table_name),
        )
        result = cursor.fetchone()
        return bool(result and result[0])

    def get_table_source_columns(self, cursor, table_name):
        cursor.execute(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = %s
              AND table_name = %s
            ORDER BY ordinal_position
            """,
            (self.schema_name, table_name),
        )
        columns = [str(row[0]) for row in cursor.fetchall()]
        return [
            name for name in columns if name not in self.ALL_METADATA_COLUMNS
        ]

    def count_rows(self, cursor, table_name, temporary):
        if temporary:
            statement = sql.SQL("SELECT COUNT(*) FROM {}").format(
                sql.Identifier(table_name)
            )
        else:
            statement = sql.SQL("SELECT COUNT(*) FROM {}.{}").format(
                sql.Identifier(self.schema_name),
                sql.Identifier(table_name),
            )
        cursor.execute(statement)
        result = cursor.fetchone()
        if result is None:
            raise RuntimeError("Cannot count table: {}".format(table_name))
        return int(result[0])

    @staticmethod
    def validate_columns(source, csv_columns, table_columns):
        if csv_columns != table_columns:
            raise ValueError(
                "Schema mismatch for {}. CSV={}, Table={}".format(
                    source.name,
                    csv_columns,
                    table_columns,
                )
            )

    @staticmethod
    def normalize_headers(headers):
        result = []
        counts = {}

        for index, header in enumerate(headers, start=1):
            base_name = CsvDatabaseLoader.make_identifier(
                header,
                fallback="column_{}".format(index),
                max_length=55,
            )
            counts[base_name] = counts.get(base_name, 0) + 1
            count = counts[base_name]
            final_name = (
                base_name
                if count == 1
                else CsvDatabaseLoader.make_identifier(
                    "{}_{}".format(base_name, count),
                    max_length=63,
                )
            )
            result.append(final_name)

        return result

    @staticmethod
    def make_identifier(value, fallback="column", max_length=63):
        text = str(value or "").strip().lower()
        text = re.sub(r"[^a-z0-9]+", "_", text)
        text = re.sub(r"_+", "_", text).strip("_")
        text = text or fallback
        if text[0].isdigit():
            text = "col_{}".format(text)
        return text[:max_length].rstrip("_")

    @staticmethod
    def normalize_row(row, expected_columns, source, row_number):
        if len(row) > expected_columns:
            raise ValueError(
                "{} row {} has {} columns; expected {}".format(
                    source.name,
                    row_number,
                    len(row),
                    expected_columns,
                )
            )
        if len(row) < expected_columns:
            row = row + [""] * (expected_columns - len(row))
        return [str(value) for value in row]

    @staticmethod
    def hash_row(row):
        payload = "\x1f".join(row).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()
