# Demo dashboard

The dashboard runs without a database in **demo mode**: it loads the CSV files in `app/sample_data/` (synthetic marts produced by `scripts/make_demo_data.py` + dbt) into an in-memory DuckDB and runs the same queries it runs against PostgreSQL. Demo mode is used automatically when `DB_HOST` is not set, or when `SAMPLE_DATA=1`.

## Run it locally

```bash
pip install -r app/requirements.txt
streamlit run app/streamlit_app.py
```

## Put it online with Streamlit Community Cloud

Streamlit Community Cloud deploys an app straight from a GitHub repository.

**Option A: this repository**

1. Open <https://share.streamlit.io>, sign in with GitHub and allow access to the repository (a private repository works once you grant access).
2. *Create app*: repository `chaukydang/cs-ops-etl-pipeline`, branch `main`, main file `app/streamlit_app.py`.
3. In *Advanced settings* pick Python 3.12. Dependencies are read from `app/requirements.txt`; if the build installs the root `requirements.txt` instead (it pulls in Selenium and others), use option B.
4. Do not add any secrets. Without `DB_HOST` the app stays in demo mode.

**Option B: a small separate repository (recommended for a public link)**

```bash
scripts/export_demo_app.sh ../cs-ops-dashboard-demo
cd ../cs-ops-dashboard-demo && git init && git add . && git commit -m "Demo dashboard"
# create an empty repository on GitHub, push, then create the app with main file streamlit_app.py
```

This repository contains only the dashboard and synthetic data, so it can be public without exposing anything about the pipeline's configs. The exported folder was tested on its own in a clean environment with only `requirements.txt` installed.

## Refreshing the sample data

```bash
python scripts/make_demo_data.py --days 56 --agents 40
# load into a local PostgreSQL and run dbt build (README, "Try it without real data")
python scripts/export_sample_data.py --i-know-this-is-demo-data
```

The exporter refuses to run without that flag, because the sample is published with the repository and must never contain real data.

## Notes

- Every figure in demo mode is synthetic. The page says so at the top.
- Agent ids in the sample are hashes of fake e-mails (`agentNNN@example.com`).
- Streamlit Community Cloud puts apps to sleep after a period without visitors; the first visit afterwards takes a few seconds to wake it.
