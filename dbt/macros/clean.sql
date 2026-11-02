{# Raw tables are all text and use '' and 'NULL' for missing values. Every macro that
   differs between PostgreSQL and BigQuery is dispatched on the adapter. #}

{% macro clean_text(col) -%}
    nullif(nullif(trim({{ col }}), ''), 'NULL')
{%- endmacro %}

{# ---- numbers ---- #}
{% macro to_num(col) -%}
    {{ return(adapter.dispatch('to_num', 'cs_ops')(col)) }}
{%- endmacro %}

{% macro default__to_num(col) -%}
    (case
        when trim({{ col }}) ~ '^-?[0-9]+(\.[0-9]+)?([eE][-+]?[0-9]+)?$'
        then trim({{ col }})::numeric
    end)
{%- endmacro %}

{# FLOAT64, not NUMERIC: the exports carry 16+ decimal digits #}
{% macro bigquery__to_num(col) -%}
    safe_cast(trim({{ col }}) as float64)
{%- endmacro %}

{# ---- dates ---- #}
{# 1970-01-01 is the exports' placeholder for "no date" #}
{% macro to_date(col) -%}
    {{ return(adapter.dispatch('to_date', 'cs_ops')(col)) }}
{%- endmacro %}

{% macro default__to_date(col) -%}
    (case
        when trim({{ col }}) ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}'
             and left(trim({{ col }}), 10) <> '1970-01-01'
        then left(trim({{ col }}), 10)::date
    end)
{%- endmacro %}

{% macro bigquery__to_date(col) -%}
    (case
        when left(trim({{ col }}), 10) <> '1970-01-01'
        then safe_cast(left(trim({{ col }}), 10) as date)
    end)
{%- endmacro %}

{% macro to_ts(col) -%}
    {{ return(adapter.dispatch('to_ts', 'cs_ops')(col)) }}
{%- endmacro %}

{% macro default__to_ts(col) -%}
    (case
        when trim({{ col }}) ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2} [0-9]{2}:[0-9]{2}:[0-9]{2}'
             and left(trim({{ col }}), 10) <> '1970-01-01'
        then left(trim({{ col }}), 19)::timestamp
    end)
{%- endmacro %}

{% macro bigquery__to_ts(col) -%}
    (case
        when left(trim({{ col }}), 10) <> '1970-01-01'
        then safe_cast(left(trim({{ col }}), 19) as datetime)
    end)
{%- endmacro %}

{# Sunday-based week start, same convention as the downloader's date window #}
{% macro week_start_sunday(date_col) -%}
    {{ return(adapter.dispatch('week_start_sunday', 'cs_ops')(date_col)) }}
{%- endmacro %}

{% macro default__week_start_sunday(date_col) -%}
    ({{ date_col }} - extract(dow from {{ date_col }})::int)
{%- endmacro %}

{% macro bigquery__week_start_sunday(date_col) -%}
    date_sub({{ date_col }}, interval (extract(dayofweek from {{ date_col }}) - 1) day)
{%- endmacro %}
