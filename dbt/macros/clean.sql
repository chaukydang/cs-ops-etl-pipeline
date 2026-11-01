{# Raw tables are all TEXT and use '' and 'NULL' for missing values. #}

{% macro clean_text(col) -%}
    nullif(nullif(trim({{ col }}), ''), 'NULL')
{%- endmacro %}

{% macro to_num(col) -%}
    (case
        when trim({{ col }}) ~ '^-?[0-9]+(\.[0-9]+)?([eE][-+]?[0-9]+)?$'
        then trim({{ col }})::numeric
    end)
{%- endmacro %}

{# 1970-01-01 is the exports' placeholder for "no date" #}
{% macro to_date(col) -%}
    (case
        when trim({{ col }}) ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}'
             and left(trim({{ col }}), 10) <> '1970-01-01'
        then left(trim({{ col }}), 10)::date
    end)
{%- endmacro %}

{% macro to_ts(col) -%}
    (case
        when trim({{ col }}) ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2} [0-9]{2}:[0-9]{2}:[0-9]{2}'
             and left(trim({{ col }}), 10) <> '1970-01-01'
        then left(trim({{ col }}), 19)::timestamp
    end)
{%- endmacro %}

{# Sunday-based week start, same convention as the downloader's date window #}
{% macro week_start_sunday(date_col) -%}
    ({{ date_col }} - extract(dow from {{ date_col }})::int)
{%- endmacro %}
