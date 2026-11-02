FROM python:3.12-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends chromium chromium-driver openjdk-17-jre-headless \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /opt/pipeline

# dbt and Spark get their own virtualenvs so their dependency pins stay out of the main one
COPY requirements-dbt.txt requirements-spark.txt ./
RUN python -m venv /opt/venvs/dbt   && /opt/venvs/dbt/bin/pip install --no-cache-dir -r requirements-dbt.txt \
    && python -m venv /opt/venvs/spark && /opt/venvs/spark/bin/pip install --no-cache-dir -r requirements-spark.txt

COPY requirements.txt requirements-prefect.txt requirements-bigquery.txt ./
RUN pip install --no-cache-dir -r requirements.txt -r requirements-prefect.txt -r requirements-bigquery.txt

COPY . .

ENV PIPELINE_HOME=/opt/pipeline \
    DBT_BIN=/opt/venvs/dbt/bin/dbt \
    SPARK_PYTHON=/opt/venvs/spark/bin/python \
    AEOLUS_HEADLESS=true \
    AEOLUS_CHROME_DRIVER_PATH=/usr/bin/chromedriver

# serves the flow and runs it daily at 07:00 (Asia/Ho_Chi_Minh)
CMD ["python", "-m", "flows.cs_ops_etl"]
