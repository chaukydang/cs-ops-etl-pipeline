# Data model

## Layers

| Layer | Where | What |
|-------|-------|------|
| raw | PostgreSQL schema `Service` / BigQuery dataset `raw` | One table per source, every column TEXT/STRING exactly as exported, plus loader metadata (`_source_file`, `_source_row_number`, `_row_hash`, `_loaded_at`; BigQuery also `_partition_date`). |
| staging | `staging` (views) | Typed and cleaned: `''` / `'NULL'` become NULL, the `1970-01-01` placeholder becomes NULL, `Sum` roll-up rows are dropped, duplicates are removed. |
| marts | `marts` (tables) | Dimensions and facts used by the dashboard. |

Keeping raw as text means a load never fails on a bad value, and the original export can always be reproduced. Typing happens once, in dbt.

## Grain and keys

| Model | Grain | Key |
|-------|-------|-----|
| `dim_date` | one day | `date_day` |
| `dim_agent` | one agent (latest tier, tenure, team) | `agent_key` = hash of lower-cased e-mail |
| `fct_productivity_daily` | agent x day x segment x skill group | `row_key` |
| `fct_attendance_daily` | agent x day | `row_key` |
| `fct_tickets_daily` | create date x skill group x user type x channel | `row_key` |
| `fct_csat_daily` | survey date x skill group x channel | `row_key` |
| `fct_backlog_daily` | day x user type | `row_key` |
| `fct_forecast_vs_actual` | day x skill group | `row_key` |
| `mart_agent_weekly` | agent x week (Sunday start) | `row_key` |

`row_key` is a hash of the grain columns. Facts join to `dim_agent` on `agent_key`, so the e-mail only lives in raw and `dim_agent`.

## Metric definitions

| Metric | Definition |
|--------|------------|
| CPH | tickets closed / productivity hours |
| Occupancy | busy hours / online hours |
| Online rate | online hours / paid hours |
| CSAT | share of survey responses scoring 4 or 5 (5-point scale) |
| FCR | tickets marked first-contact-resolved / tickets created |
| On-time rate | 1 - late shifts / shifts |

These are the definitions used in the models; confirm them against your team's before reporting numbers externally.

## Duplicates

Duplicates are handled in staging, not by deleting raw rows:

- tickets: one row per `ticket_id`, the most recently loaded row wins (late corrections replace earlier values);
- CSAT: one row per ticket and survey date, latest load wins;
- productivity, attendance, backlog, forecast: exact copies of a row (same `_row_hash`) are collapsed.

The loader itself cannot create duplicates for dashboard sources: it replaces the whole downloaded date window inside one transaction. `recon_duplicates_in_raw` reports how many duplicates existed so that a sudden increase is noticed.

## Reconciliation

dbt tests in `dbt/tests/reconciliation/`, run on every `dbt build`:

| Test | Fails when |
|------|-----------|
| `recon_mart_matches_staging` | a fact's total differs from staging (stale incremental facts, a bug in an aggregation) |
| `recon_dropped_rows` | more than 1% of raw rows disappear between raw and staging |
| `recon_duplicates_in_raw` | (warning) duplicates found in raw |

Source freshness (`dbt source freshness`) warns after 2 days and fails after 4 days without a load. The loader additionally checks that the number of rows inserted equals the number of rows in the CSV.
