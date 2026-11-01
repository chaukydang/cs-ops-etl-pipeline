FROM apache/airflow:2.10.5-python3.12

USER root
RUN apt-get update \
    && apt-get install -y --no-install-recommends chromium chromium-driver \
    && rm -rf /var/lib/apt/lists/*

USER airflow
COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

COPY requirements-dbt.txt /tmp/requirements-dbt.txt
RUN python -m venv /home/airflow/dbt-venv \
    && /home/airflow/dbt-venv/bin/pip install --no-cache-dir -r /tmp/requirements-dbt.txt

COPY --chown=airflow:root . /opt/airflow/pipeline
ENV PIPELINE_HOME=/opt/airflow/pipeline \
    AIRFLOW__CORE__DAGS_FOLDER=/opt/airflow/pipeline/dags \
    AIRFLOW__CORE__LOAD_EXAMPLES=False \
    AEOLUS_HEADLESS=true \
    AEOLUS_CHROME_DRIVER_PATH=/usr/bin/chromedriver
