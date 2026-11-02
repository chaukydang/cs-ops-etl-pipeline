# BigQuery

Set `WAREHOUSE=bigquery` to load into BigQuery instead of PostgreSQL. Everything else (download, archive, backfill, monitor, dbt) works the same way.

## Setup

```bash
gcloud auth application-default login          # or set GOOGLE_APPLICATION_CREDENTIALS
export WAREHOUSE=bigquery BQ_PROJECT=my-project BQ_DATASET=raw BQ_LOCATION=asia-southeast1

python main.py --module database --action init     # creates partitioned tables
python main.py --module database --action load
```

For dbt add a `bigquery` output to `dbt/profiles.yml` (project, dataset `analytics`, location, auth method) and run `dbt build --target bigquery`. Sources read the dataset in `BQ_DATASET`.

## How the load works

1. The CSV is rewritten with BigQuery-safe column names plus metadata columns and loaded into a temporary staging table.
2. The same guards as PostgreSQL run against the staging table (row count equals the CSV, valid dates, rows inside the window, no large shrink).
3. One multi-statement transaction replaces the window: `DELETE` the partitions in the window, `INSERT` from staging, commit.
4. The staging table is dropped, also when something fails.

Replace-mode sources (Lark sheets) are rebuilt with `CREATE OR REPLACE TABLE`.

## Cost and performance

- Incremental raw tables are partitioned by `_partition_date` (parsed from the source's date column) and optionally clustered (`cluster_by` in `configs/database/sources/*.json`), so replacing a window only touches those partitions.
- dbt facts are partitioned by their date column and clustered; the incremental strategy is `insert_overwrite`, which replaces whole partitions instead of scanning the table like a merge would.
- Raw columns are STRING, so staging views cast every column when they are read. For large tables this is the main cost; if it becomes noticeable, materialise staging as tables or add a filter on `_partition_date`.
- `BQ_MAX_BYTES_BILLED` caps each query; the window DELETE is dry-run and its estimate is logged.

## What has and has not been tested

- Tested: the loader against a recording fake client (SQL order, guards, cleanup, schema, byte cap, run log), and every dbt model rendered for BigQuery offline and checked for PostgreSQL-only syntax and parse errors (`scripts/check_bigquery_sql.py`, also in CI).
- Not tested: a run against a real BigQuery project. The first run should use a small window and a low `BQ_MAX_BYTES_BILLED`.
