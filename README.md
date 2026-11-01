# cs-ops-etl-pipeline

Daily ETL for the customer service operations reports. It pulls data from three places, cleans it up, and loads it into PostgreSQL so the dashboards read from one database instead of a pile of exports.

```
 BI dashboard (Aeolus) --\
                          +--> CSV files --> transform --> PostgreSQL
 Lark Sheets / Lark Base -/
```

Four stages, each runnable on its own:

| Stage | What it does |
|-------|--------------|
| `dashboard` | Logs in with a real browser (Selenium) to capture the Open-Api-Token, then downloads 8 report CSVs through the export endpoint. Date filters are rewritten on every run to cover the last N weeks. |
| `lark` | Reads sheets and a Base table through the Lark Open API, dumps them to raw CSV, and applies the cleanup rules for the productivity and backlog sheets. |
| `archive` | Checks the newest CSV of every source (not empty, no sudden row-count drop versus the previous day), then writes it as date-partitioned Parquet (`data/archive/<source>/dt=YYYY-MM-DD/`). Optionally uploads to S3 / MinIO. |
| `database` | Loads the newest CSV for each source into its table. Data is loaded into a temp table first, row counts are checked, then the target is truncated and refilled inside one transaction. |

## Setup

Python 3.12+ and Chrome are required.

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env             # then fill it in
```

If `AEOLUS_CHROME_DRIVER_PATH` is empty or points to a driver that does not match your Chrome, Selenium Manager downloads a matching one.

The Lark source configs and the dashboard payloads in this repo have their IDs blanked out (`<SPREADSHEET_TOKEN>`, `reportId: 0`, ...). Put your own values in before running.

## Usage

```bash
# everything, in order: dashboard -> lark -> archive -> database
python main.py

# one stage
python main.py --module dashboard
python main.py --module lark
python main.py --module lark --type sheet_raw
python main.py --module lark --source ProductivityDataReportRaw
python main.py --module archive

# database: create missing tables once, then load
python main.py --module database --action init
python main.py --module database --action load
python main.py --module database --source ticket_details
```

With `--module all` the database load is skipped if any earlier stage failed (including a failed quality check), so a half-downloaded day never overwrites good data.

Check the database credentials without running anything else:

```bash
python check_db_connection.py
```

## Scheduling with Airflow

`dags/cs_ops_etl.py` runs the stages daily at 07:00 (Asia/Ho_Chi_Minh): `dashboard` and `lark` in parallel, then `archive`, then `load_postgres`. Each task just calls `python main.py --module ...`, so a failed task can be reproduced by hand.

A local stack (PostgreSQL, MinIO, Airflow) is defined in `docker-compose.yml`:

```bash
cp .env.example .env     # fill in the Aeolus / Lark / Outlook values
docker compose up --build
# Airflow UI: http://localhost:8080   MinIO console: http://localhost:9001
```

The Airflow image ships Chromium and runs the browser step headless (`AEOLUS_HEADLESS=true`). The first login may need an interactive session to get past MFA; after that the profile under `data/` keeps the session. The compose file has not been run end to end against the real Aeolus login, so expect to adjust that part.

## Configuration

Everything that changes between sources lives in JSON under `configs/`:

```
configs/
  dashboard/sources/   one file per report: endpoint, payload, output name, dynamic_date
  lark/sheets/         sheet_raw sources (spreadsheet token, tab, column range)
  lark/base/           Base table sources (app token, table, field list)
  lark/transforms/     raw CSV -> cleaned CSV
  database/sources/    CSV file pattern -> target table
  database/settings.json
```

Adding a report is mostly a new JSON file. For a dashboard report, export it once from the browser, copy the request payload into a new file in `configs/dashboard/sources/`, and set `dynamic_date.field_id` to the date field you want the pipeline to move forward each run. For the database, add a matching file in `configs/database/sources/` with the table name and a glob for the CSV.

Table names currently used: `tickets`, `tqm`, `csat`, `im`, `attendance`, `forecast_actual`, `productivity_daily`, `backlog_daily`, `productivity_hourly`, `backlog_hourly`, `roster`. They are created in the schema from `DB_SCHEMA` (default `Service`).

## Layout

```
main.py                     entry point / CLI
check_db_connection.py      connection and privilege check
modules/
  core/                     .env loader, config validation
  dashboard/                auth (Lark + Outlook OTP), browser session, downloader, notifier
  lark/                     API clients, raw download, transforms
  storage/                  quality checks, Parquet archive, S3 upload
  database/                 connection, CSV profiling and loading
dags/                       Airflow DAG
Dockerfile, docker-compose.yml
tests/                      pytest
```

## Notes

- Failures are reported to a Lark webhook if `LARK_WEBHOOK_URL` is set. Tokens, cookies and passwords are masked before anything is sent.
- Download retries use backoff, and a 401/403 triggers one re-login before giving up on that report.
- Logs go to `logs/dashboard_pipeline.log`; downloaded CSVs to `downloads/`. Both are git-ignored, since they contain employee data.
- The browser profile in `data/` keeps the login session between runs. Also ignored.

## Development

```bash
pip install -r requirements-dev.txt
ruff check .
pytest
```

The tests cover the pure helpers (env/config parsing, date-window calculation, header and identifier normalisation) and the Parquet archive and quality checks. The DAG structure test runs only when Airflow is installed. The download and database stages need real credentials and are not covered.

## License

MIT, see [LICENSE](LICENSE).
