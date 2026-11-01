from __future__ import annotations

import csv
import glob
import hashlib
import json
import os
import re
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

from psycopg import sql


@dataclass(frozen=True)
class CsvDefinition:
    name: str
    table_name: str
    file_pattern: str
    enabled: bool = True
    recursive: bool = True
    # "replace": truncate and reload (full snapshots, e.g. Lark sheets)
    # "incremental": delete the downloaded date window, insert the new rows,
    #                keep everything older (rolling dashboard exports)
    load_mode: str = "replace"
    date_column: str | None = None


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

    def initialize_table(self, source, file_path=None):
        file_path = Path(file_path).resolve() if file_path else self.find_latest_file(source)
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

    def load_table(self, source, file_path=None, window=None):
        """Load one CSV into the source's table.

        file_path: load this file instead of the newest match (used by backfill).
        window:    (date_from, date_to) as dates; overrides the sidecar file.
        """
        if source.load_mode not in ("replace", "incremental"):
            raise ValueError(
                "{}: unknown load_mode {!r}".format(source.name, source.load_mode)
            )
        if source.load_mode == "incremental" and not source.date_column:
            raise ValueError("{}: incremental load needs date_column".format(source.name))

        file_path = Path(file_path).resolve() if file_path else self.find_latest_file(source)
        profile = self.profile_csv(file_path)
        stats = {}

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

                if source.load_mode == "incremental":
                    stats = self._replace_window(
                        cursor, source, profile, temp_table, window
                    )
                else:
                    cursor.execute(
                        sql.SQL("TRUNCATE TABLE {}.{} RESTART IDENTITY").format(
                            sql.Identifier(self.schema_name),
                            sql.Identifier(source.table_name),
                        )
                    )
                    self._insert_from_temp(cursor, source, profile, temp_table)

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
            "mode": source.load_mode,
            **stats,
        }

    def _insert_from_temp(self, cursor, source, profile, temp_table):
        insert_columns = profile.database_headers + self.LOAD_METADATA_COLUMNS
        names = sql.SQL(", ").join([sql.Identifier(name) for name in insert_columns])
        cursor.execute(
            sql.SQL("INSERT INTO {}.{} ({}) SELECT {} FROM {}").format(
                sql.Identifier(self.schema_name),
                sql.Identifier(source.table_name),
                names,
                names,
                sql.Identifier(temp_table),
            )
        )
        return cursor.rowcount

    # ISO dates sort the same as text, so the window can be compared as text
    # and a plain btree index on the column is usable.
    ISO_DATE_REGEX = r"^[0-9]{4}-[0-9]{2}-[0-9]{2}"

    def _replace_window(self, cursor, source, profile, temp_table, window):
        column = sql.Identifier(source.date_column)
        if source.date_column not in profile.database_headers:
            raise ValueError(
                "{}: date_column {!r} is not in the CSV".format(
                    source.name, source.date_column
                )
            )
        if profile.row_count == 0:
            raise ValueError(
                "{}: CSV has no rows; refusing to clear the date window".format(source.name)
            )

        cursor.execute(
            sql.SQL(
                "SELECT count(*) FILTER (WHERE {c} IS NULL OR {c} !~ %(rx)s), "
                "min(left({c}, 10)) FILTER (WHERE {c} ~ %(rx)s), "
                "max(left({c}, 10)) FILTER (WHERE {c} ~ %(rx)s) FROM {t}"
            ).format(c=column, t=sql.Identifier(temp_table)),
            {"rx": self.ISO_DATE_REGEX},
        )
        invalid, csv_min, csv_max = cursor.fetchone()
        if invalid:
            raise ValueError(
                "{}: {} rows have no valid date in {}".format(
                    source.name, invalid, source.date_column
                )
            )

        date_from, date_to = self.resolve_window(profile.file_path, window, csv_min, csv_max)
        if csv_min < date_from.isoformat() or csv_max > date_to.isoformat():
            raise ValueError(
                "{}: rows fall outside the downloaded window {}..{} (CSV has {}..{})".format(
                    source.name, date_from, date_to, csv_min, csv_max
                )
            )

        self.ensure_date_index(cursor, source)

        cursor.execute(
            sql.SQL("DELETE FROM {}.{} WHERE {} >= %s AND {} < %s").format(
                sql.Identifier(self.schema_name),
                sql.Identifier(source.table_name),
                column,
                column,
            ),
            (date_from.isoformat(), (date_to + timedelta(days=1)).isoformat()),
        )
        deleted = cursor.rowcount

        inserted = self._insert_from_temp(cursor, source, profile, temp_table)
        if inserted != profile.row_count:
            raise RuntimeError(
                "Insert count mismatch for {}: CSV={}, inserted={}".format(
                    source.name, profile.row_count, inserted
                )
            )

        # A window that suddenly shrinks usually means a partial download.
        max_shrink = float(os.getenv("LOAD_MAX_SHRINK_RATIO", "0.5"))
        if deleted >= 100 and inserted < deleted * (1 - max_shrink):
            raise ValueError(
                "{}: window {}..{} would shrink from {} to {} rows; "
                "set LOAD_MAX_SHRINK_RATIO to allow it".format(
                    source.name, date_from, date_to, deleted, inserted
                )
            )

        return {
            "window": [date_from.isoformat(), date_to.isoformat()],
            "deleted": deleted,
            "inserted": inserted,
        }

    @staticmethod
    def resolve_window(file_path, window, csv_min, csv_max):
        """Window precedence: explicit argument, sidecar from the downloader, CSV range."""
        if window:
            return window

        sidecar = Path(str(file_path) + ".meta.json")
        if sidecar.exists():
            meta = json.loads(sidecar.read_text(encoding="utf-8"))
            return (date.fromisoformat(meta["date_from"]), date.fromisoformat(meta["date_to"]))

        return (date.fromisoformat(csv_min), date.fromisoformat(csv_max))

    def ensure_date_index(self, cursor, source):
        index_name = self.make_identifier(
            "ix_{}_{}".format(source.table_name, source.date_column), max_length=63
        )
        cursor.execute(
            sql.SQL("CREATE INDEX IF NOT EXISTS {} ON {}.{} ({})").format(
                sql.Identifier(index_name),
                sql.Identifier(self.schema_name),
                sql.Identifier(source.table_name),
                sql.Identifier(source.date_column),
            )
        )

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
