# Runbook

Where to look first: the Prefect UI (task logs), the `pipeline_runs` table (one row per load: status, rows, duration, error), and the Lark alert if one was sent.

| Symptom | Likely cause | What to do |
|---------|--------------|-----------|
| `dashboard` task fails with 401/403 or login errors | Aeolus session or MFA expired | Re-run once (the downloader already re-logs in once). If it still fails, log in interactively once so the browser profile under `data/` is refreshed. |
| Error "export hit the 1000000 row limit" | A window returned more rows than the export allows; the file was deleted on purpose | Shorten the window (`weeks_back` in the config) or backfill with `--chunk week`. |
| Load fails with "would shrink" | The new file has far fewer rows than the window it replaces, usually a partial download | Look at the file. If the data really shrank, re-run with a higher `LOAD_MAX_SHRINK_RATIO`. The table was not changed. |
| Load fails with "rows fall outside the downloaded window" or "no valid date" | The report's date field changed or the placeholder date appeared | Check the report definition in `configs/dashboard/sources/` and the `date_column` in `configs/database/sources/`. The table was not changed. |
| Load fails with "Schema mismatch" | A column was added, removed or renamed in the export | Compare the CSV header with the table. Add the column (or rebuild the table) and re-run `--action init` then `load`. |
| `monitor` reports `stale` | The source was not refreshed, or the report returned no recent rows | Check the last `pipeline_runs` rows for that source, then the dashboard stage log. |
| `monitor` reports `missing_table` | New source never initialised | `python main.py --module database --action init --source <name>` |
| `recon_mart_matches_staging` fails | Incremental facts are stale (a backfill touched old dates) or a model changed | `dbt build --full-refresh` |
| `recon_dropped_rows` fails | More than 1% of raw rows are dropped in staging | Query the raw table for rows with an empty key or date; usually an upstream change. |
| Dashboard shows no data | marts not built | `dbt build`, then reload the page (results are cached for 5 minutes). |

## Re-running safely

- Every stage can be re-run: incremental loads replace the same window, so running twice gives the same result.
- A failed backfill is resumed by running the same command again; finished chunks are skipped (`data/backfill_state.json`).
- To redo a chunk, delete its entry from `data/backfill_state.json` and run again.

## Incident checklist (numbers look wrong)

1. Is the data fresh? `python main.py --module monitor`
2. Do raw and marts agree? `dbt test --select tag:reconciliation` (or `dbt test --select path:tests/reconciliation`)
3. Compare one metric for one day against the source dashboard.
4. Check `pipeline_runs` for that source around the day in question (row counts, errors).
5. If the cause is a changed definition upstream, fix the staging model, then `dbt build --full-refresh`.
