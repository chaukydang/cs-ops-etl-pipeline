# Security

## In place

- Secrets are read from environment variables (`.env` locally, container environment elsewhere). `.env`, browser profile, downloads, logs and archives are git-ignored; `.env.example` has no values.
- The Lark notifier masks anything whose name contains token, cookie, password, secret, authorization or session before sending.
- Agent e-mails exist only in raw tables and `dim_agent`; facts use a hash (`agent_key`). The dashboard shows hashed ids unless `SHOW_AGENT_EMAIL=1`.
- BigQuery: `BQ_MAX_BYTES_BILLED` makes any query that would scan more than the cap fail instead of costing money. The DELETE of a window is dry-run first and its estimated bytes are logged.
- Loads are transactional and guarded (empty file, bad dates, rows outside the window, large shrink), so a bad download cannot overwrite good data.
- CI uses synthetic data only; there are no real credentials in the repository.

## Recommended when running it for real

- Keep secrets in a secret manager instead of `.env` files, and rotate the Lark, Outlook and database passwords.
- BigQuery, least privilege, three identities:
  - loader: `roles/bigquery.dataEditor` on the `raw` dataset and `roles/bigquery.jobUser` on the project;
  - dbt: `dataViewer` on `raw`, `dataEditor` on `staging` and `marts`, `jobUser`;
  - dashboard / analysts: `dataViewer` on `marts` only.
- Put the agent e-mail columns behind column-level security (policy tags) so analysts query `agent_key` and only a small group can see e-mails.
- Use workload identity or a service account attached to the runtime rather than key files.
- Add secret scanning (gitleaks) and dependency updates to the repository.
