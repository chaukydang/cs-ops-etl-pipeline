# Sample dashboard (no database)

The dashboard is a multi-tab operations report. The first tab is the daily report: KA and Non-KA tables with CPH, ConPD, occupancy, utilization, CSAT, FCR and 24h resolution over the last 7 days, four weeks and month to date, coloured by distance to an effective-dated target (`app/targets.py`). Then: KPI cards with change versus the previous period and targets, productivity (CPH, occupancy, tenure, tier, team), quality (CSAT, FCR, 24h resolution, first response), backlog and ageing, forecast versus actual with staffing, an agent scorecard and a data-freshness page. Weekly charts only show complete Sunday-to-Saturday weeks.

It runs without a database in **sample mode**: it loads the CSV files in `app/sample_data/` (synthetic marts produced by `scripts/make_demo_data.py` + dbt) into an in-memory DuckDB and runs the same queries it runs against PostgreSQL. Sample mode is used automatically when `DB_HOST` is not set, or when `SAMPLE_DATA=1`.

## Run it locally

```bash
pip install -r app/requirements.txt
streamlit run app/streamlit_app.py
```

## Put it online with Streamlit Community Cloud

Streamlit Community Cloud deploys an app straight from a GitHub repository.

**Option A: this repository as it is (simplest)**

1. Open <https://share.streamlit.io>, sign in with GitHub and allow access to the repository (a private repository works once you grant access).
2. *Create app*: repository `chaukydang/cs-ops-etl-pipeline`, branch `main`, main file `streamlit_app.py` (the default), Python 3.12 or newer. Deploy.

That is all: `streamlit_app.py` at the repository root starts the dashboard, `requirements.txt` at the root installs what it needs, and the sample data is in the repository. Do not add any secrets; without `DB_HOST` the app stays in sample mode. This was tested from a clean checkout of the repository in a fresh virtual environment with only the root `requirements.txt` installed.

Streamlit Community Cloud only runs the dashboard. The pipeline itself (the browser login to the BI dashboard, PostgreSQL or BigQuery, dbt, the Prefect schedule) needs a machine of its own, so on Streamlit the report always runs on the bundled sample data.

**Option B: a small separate repository (for a public link that exposes nothing else)**

```bash
scripts/export_demo_app.sh ../cs-ops-dashboard-demo
cd ../cs-ops-dashboard-demo && git init && git add . && git commit -m "Demo dashboard"
# create an empty repository on GitHub, push, then create the app with main file streamlit_app.py
```

This repository contains only the dashboard and synthetic data, so it can be public without exposing anything about the pipeline's configs. The exported folder was tested on its own in a clean environment with only `requirements.txt` installed.

## Refreshing the sample data

```bash
python scripts/make_demo_data.py --days 84 --agents 45
# load into a local PostgreSQL and run dbt build (README, "Try it without real data")
python scripts/export_sample_data.py --i-know-this-is-demo-data
```

The generator follows the patterns of a support operation (weekday volume, promotion spikes that build a backlog which then clears, slower new agents, a forecast that misses promotion days), so the report behaves like a real one. The exporter refuses to run without that flag, because the sample is published with the repository and must never contain real data.

## Notes

- Every figure in sample mode is synthetic. The page footer says so (`Source: sample dataset (synthetic)`); keep that line, readers should know what they are looking at.
- Agent ids in the sample are hashes of fake e-mails (addresses like `name.family12@example.com`, generated).
- Streamlit Community Cloud puts apps to sleep after a period without visitors; the first visit afterwards takes a few seconds to wake it.
