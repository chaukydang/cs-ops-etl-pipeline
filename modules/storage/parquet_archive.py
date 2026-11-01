"""Write pipeline CSV output to date-partitioned Parquet files.

Layout:  <root>/<source>/dt=YYYY-MM-DD/<source>.parquet

All columns are stored as strings. The database loader works on text too,
so type decisions stay in one place (the target table), and the archive
is a faithful copy of what was downloaded.
"""

from __future__ import annotations

import csv
import logging
import os
from datetime import date
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

LOGGER = logging.getLogger("ParquetArchive")

CHUNK_ROWS = 100_000


def make_unique(headers: list[str]) -> list[str]:
    seen: dict[str, int] = {}
    result = []
    for header in headers:
        name = str(header).strip() or "column"
        seen[name] = seen.get(name, 0) + 1
        result.append(name if seen[name] == 1 else f"{name}_{seen[name]}")
    return result


def partition_path(root: Path, source: str, run_date: date) -> Path:
    return root / source / f"dt={run_date.isoformat()}" / f"{source}.parquet"


def csv_to_parquet(csv_file: Path, parquet_file: Path) -> int:
    """Convert a CSV to Parquet in chunks. Returns the number of data rows."""
    parquet_file.parent.mkdir(parents=True, exist_ok=True)
    temp_file = parquet_file.with_suffix(".parquet.tmp")
    writer: pq.ParquetWriter | None = None
    total = 0

    try:
        with csv_file.open("r", encoding="utf-8-sig", newline="") as handle:
            header = next(csv.reader(handle), None)
        if not header:
            raise ValueError(f"CSV has no header: {csv_file}")
        columns = make_unique(header)

        # header is read separately so pandas does not rename duplicate columns
        reader = pd.read_csv(
            csv_file,
            dtype=str,
            keep_default_na=False,
            encoding="utf-8-sig",
            header=None,
            names=columns,
            skiprows=1,
            chunksize=CHUNK_ROWS,
        )

        for chunk in reader:
            if chunk.empty:
                continue
            table = pa.Table.from_pandas(chunk, preserve_index=False)
            if writer is None:
                writer = pq.ParquetWriter(temp_file, table.schema, compression="snappy")
            writer.write_table(table)
            total += len(chunk)

        if writer is None:
            raise ValueError(f"CSV has no data rows: {csv_file}")
    finally:
        if writer is not None:
            writer.close()
        elif temp_file.exists():
            temp_file.unlink()

    temp_file.replace(parquet_file)
    return total


def parquet_row_count(parquet_file: Path) -> int:
    return pq.ParquetFile(parquet_file).metadata.num_rows


def previous_row_count(root: Path, source: str, before: date) -> int | None:
    """Row count of the most recent archived partition older than `before`."""
    source_dir = root / source
    if not source_dir.exists():
        return None

    candidates = []
    for part in source_dir.glob("dt=*"):
        try:
            part_date = date.fromisoformat(part.name.split("=", 1)[1])
        except ValueError:
            continue
        file = part / f"{source}.parquet"
        if part_date < before and file.exists():
            candidates.append((part_date, file))

    if not candidates:
        return None
    return parquet_row_count(max(candidates)[1])


def upload_to_s3(parquet_file: Path, root: Path) -> str | None:
    """Upload to S3/MinIO when ARCHIVE_S3_BUCKET is set. Returns the key."""
    bucket = os.getenv("ARCHIVE_S3_BUCKET", "").strip()
    if not bucket:
        return None

    import boto3

    client = boto3.client(
        "s3",
        endpoint_url=os.getenv("ARCHIVE_S3_ENDPOINT") or None,
        aws_access_key_id=os.getenv("ARCHIVE_S3_ACCESS_KEY") or None,
        aws_secret_access_key=os.getenv("ARCHIVE_S3_SECRET_KEY") or None,
    )
    key = parquet_file.relative_to(root).as_posix()
    client.upload_file(str(parquet_file), bucket, key)
    LOGGER.info("Uploaded to s3://%s/%s", bucket, key)
    return key
