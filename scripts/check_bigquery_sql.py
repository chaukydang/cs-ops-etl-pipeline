"""Render the dbt project for BigQuery without any connection and sanity-check the SQL.

It cannot prove the SQL runs (that needs a real project), but it catches the
common portability mistakes: PostgreSQL-only syntax leaking into BigQuery
output, macros that fail to dispatch, and SQL that does not parse.

    python scripts/check_bigquery_sql.py

Needs dbt-bigquery, sqlglot and cryptography. No network and no credentials:
a throw-away key is generated just so the adapter can be constructed.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import sqlglot
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from sqlglot.errors import ParseError

ROOT = Path(__file__).resolve().parents[1]

POSTGRES_ONLY = re.compile(
    r"::|filter \(where|generate_series|to_char\(|extract\(dow|interval '|date_trunc\('|\s~\s"
)


def fake_profile(folder: Path) -> None:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()
    (folder / "sa.json").write_text(
        json.dumps({
            "type": "service_account", "project_id": "demo-project", "private_key_id": "x",
            "private_key": pem, "client_email": "x@demo-project.iam.gserviceaccount.com",
            "client_id": "1", "token_uri": "https://oauth2.googleapis.com/token",
        })
    )
    (folder / "profiles.yml").write_text(
        "cs_ops:\n  target: bq\n  outputs:\n    bq:\n      type: bigquery\n"
        "      method: service-account\n      project: demo-project\n      dataset: analytics\n"
        f"      keyfile: {folder / 'sa.json'}\n      threads: 2\n"
    )


def compile_variant(work: Path, incremental: bool) -> list[Path]:
    project = work / f"dbt_{incremental}"
    shutil.copytree(ROOT / "dbt", project, ignore=shutil.ignore_patterns("target", "logs"))
    # is_incremental() needs a live lookup; force each branch so both get rendered
    (project / "macros" / "zz_override.sql").write_text(
        "{% macro is_incremental() %}{{ return(" + str(incremental).lower() + ") }}{% endmacro %}\n"
    )
    env = {**os.environ, "BQ_DATASET": "raw", "DBT_SEND_ANONYMOUS_USAGE_STATS": "false"}
    result = subprocess.run(
        ["dbt", "compile", "--profiles-dir", str(work), "--project-dir", str(project),
         "--no-introspect", "--no-populate-cache", "--full-refresh"],
        capture_output=True, text=True, env=env, timeout=300,
    )
    if result.returncode != 0:
        print(result.stdout[-2000:], result.stderr[-1000:])
        raise SystemExit(f"dbt compile failed (is_incremental={incremental})")
    return sorted((project / "target" / "compiled").rglob("*.sql"))


def main() -> int:
    problems = []
    with tempfile.TemporaryDirectory() as folder:
        work = Path(folder)
        fake_profile(work)
        for incremental in (False, True):
            files = compile_variant(work, incremental)
            print(f"is_incremental={incremental}: {len(files)} compiled files")
            for path in files:
                sql = path.read_text(encoding="utf-8")
                name = f"{path.name} (is_incremental={incremental})"
                if match := POSTGRES_ONLY.search(sql):
                    problems.append(f"{name}: PostgreSQL syntax {match.group(0)!r}")
                for hashed in re.finditer(r"(?<!to_hex\()md5\(", sql):
                    problems.append(f"{name}: md5() without to_hex() at {hashed.start()}")
                try:
                    sqlglot.parse_one(sql, read="bigquery")
                except ParseError as error:
                    problems.append(f"{name}: does not parse: {str(error)[:150]}")

    for problem in problems:
        print("PROBLEM", problem)
    print("OK" if not problems else f"{len(problems)} problem(s)")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
