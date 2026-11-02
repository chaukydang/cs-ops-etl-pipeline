# Workflow

How data moves through the pipeline, from the source systems to the dashboard. All diagrams are Mermaid and render on GitHub.

## 1. End to end

```mermaid
flowchart LR
    subgraph Sources
        A[Aeolus BI dashboard<br/>8 report exports]
        L[Lark Sheets and Base<br/>productivity, backlog, roster]
    end

    subgraph Ingest
        D[dashboard stage<br/>browser login, token, download CSV]
        K[lark stage<br/>Open API, raw CSV, transforms]
    end

    Q{archive stage<br/>quality checks}
    P[(Parquet archive<br/>data/archive, optional S3/MinIO)]
    R[(BigQuery or PostgreSQL<br/>raw tables, all text)]
    S[dbt staging<br/>typed, cleaned, deduplicated]
    M[dbt marts<br/>dims and facts<br/>reconciliation tests]
    H[Spark job<br/>deduplicated history]
    B[Streamlit dashboard]
    O[monitor<br/>freshness and run history]
    N[[Lark webhook alerts]]

    A --> D --> Q
    L --> K --> Q
    Q -- pass --> P
    Q -- pass --> R
    Q -- fail --> N
    P --> H
    R --> S --> M --> B
    R --> O --> N
```

## 2. Daily schedule (Prefect flow, 07:00 Asia/Ho_Chi_Minh)

```mermaid
flowchart LR
    dashboard --> archive
    lark --> archive
    archive --> load_postgres --> dbt_build --> monitor
    archive --> spark_history
```

`dashboard` and `lark` run in parallel. A failed task retries twice (10 minute delay), then posts to the Lark webhook; tasks downstream of a failure do not run. The database load is skipped when an earlier stage failed, so a bad day never overwrites good data. The same stages can be run by hand with `python main.py --module <name>`.

## 3. How one dashboard report is loaded

```mermaid
flowchart TD
    A[Rolling window: last ~5 weeks] --> B[Download CSV from Aeolus]
    B --> C{Hit the 1,000,000<br/>row limit?}
    C -- yes --> X[Delete file, fail the source]
    C -- no --> D[Write sidecar .meta.json<br/>date_from, date_to]
    D --> E[Copy CSV into a temp table]
    E --> F{Guards pass?<br/>not empty, dates valid,<br/>inside window, no big shrink}
    F -- no --> Y[Abort, table untouched]
    F -- yes --> G[DELETE rows in the window]
    G --> H[INSERT rows from temp table]
    H --> I[COMMIT, write pipeline_runs row]
```

Everything from step E to the commit is one transaction. Rows older than the window are never touched, which is how years of history survive a daily run. Lark sources are full snapshots and use truncate and reload instead.

## 4. Backfill

```mermaid
flowchart TD
    A[--from / --to / --chunk] --> B[Split range into chunks]
    B --> C{Chunk already in<br/>backfill_state.json?}
    C -- yes --> Z[Skip]
    C -- no --> D[Download chunk]
    D --> E{Row limit hit?}
    E -- yes --> F[Split chunk in half] --> D
    E -- no --> G[Incremental load for that window]
    G --> H[Archive as Parquet]
    H --> I[Mark chunk done, delete CSV]
    I --> J{More chunks?}
    J -- yes --> C
    J -- no --> K[dbt build --full-refresh]
```

If a chunk fails (expired session, network), the run stops for that report. Running the same command again continues from the first unfinished chunk.

## 5. dbt layers

```mermaid
flowchart LR
    subgraph raw [schema Service]
        r1[productivity_daily]
        r2[tickets]
        r3[csat]
        r4[attendance]
        r5[backlog_daily]
        r6[forecast_actual]
    end
    subgraph staging [views]
        s1[stg_productivity]
        s2[stg_tickets]
        s3[stg_csat]
        s4[stg_attendance]
        s5[stg_backlog]
        s6[stg_forecast]
    end
    subgraph marts [tables]
        d1[dim_agent]
        d2[dim_date]
        f1[fct_productivity_daily]
        f2[fct_tickets_daily]
        f3[fct_csat_daily]
        f4[fct_attendance_daily]
        f5[fct_backlog_daily]
        f6[fct_forecast_vs_actual]
        w[mart_agent_weekly]
    end
    r1 --> s1 --> f1
    r2 --> s2 --> f2
    r3 --> s3 --> f3
    r4 --> s4 --> f4
    r5 --> s5 --> f5
    r6 --> s6 --> f6
    s1 --> d1
    f1 & f4 & s3 --> w
```
