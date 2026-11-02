{# Small cross-database helpers used by the marts. #}

{% macro hash_key(expr) -%}
    {{ return(adapter.dispatch('hash_key', 'cs_ops')(expr)) }}
{%- endmacro %}
{% macro default__hash_key(expr) -%}md5({{ expr }}){%- endmacro %}
{% macro bigquery__hash_key(expr) -%}to_hex(md5({{ expr }})){%- endmacro %}

{% macro as_text(expr) -%}
    {{ return(adapter.dispatch('as_text', 'cs_ops')(expr)) }}
{%- endmacro %}
{% macro default__as_text(expr) -%}({{ expr }})::text{%- endmacro %}
{% macro bigquery__as_text(expr) -%}cast({{ expr }} as string){%- endmacro %}

{# count rows matching a condition #}
{% macro count_if(cond) -%}
    {{ return(adapter.dispatch('count_if', 'cs_ops')(cond)) }}
{%- endmacro %}
{% macro default__count_if(cond) -%}count(*) filter (where {{ cond }}){%- endmacro %}
{% macro bigquery__count_if(cond) -%}countif({{ cond }}){%- endmacro %}

{# num / den as a decimal, NULL when den is 0 or NULL #}
{% macro ratio(num, den) -%}
    {{ return(adapter.dispatch('ratio', 'cs_ops')(num, den)) }}
{%- endmacro %}
{% macro default__ratio(num, den) -%}(({{ num }})::numeric / nullif({{ den }}, 0)){%- endmacro %}
{% macro bigquery__ratio(num, den) -%}safe_divide({{ num }}, {{ den }}){%- endmacro %}

{% macro date_minus_days(date_expr, days) -%}
    {{ return(adapter.dispatch('date_minus_days', 'cs_ops')(date_expr, days)) }}
{%- endmacro %}
{% macro default__date_minus_days(date_expr, days) -%}({{ date_expr }} - {{ days }}){%- endmacro %}
{% macro bigquery__date_minus_days(date_expr, days) -%}date_sub({{ date_expr }}, interval {{ days }} day){%- endmacro %}

{% macro month_start(date_expr) -%}
    {{ return(adapter.dispatch('month_start', 'cs_ops')(date_expr)) }}
{%- endmacro %}
{% macro default__month_start(date_expr) -%}date_trunc('month', {{ date_expr }})::date{%- endmacro %}
{% macro bigquery__month_start(date_expr) -%}date_trunc({{ date_expr }}, month){%- endmacro %}

{# 0 = Sunday ... 6 = Saturday #}
{% macro day_of_week(date_expr) -%}
    {{ return(adapter.dispatch('day_of_week', 'cs_ops')(date_expr)) }}
{%- endmacro %}
{% macro default__day_of_week(date_expr) -%}extract(dow from {{ date_expr }}){%- endmacro %}
{% macro bigquery__day_of_week(date_expr) -%}(extract(dayofweek from {{ date_expr }}) - 1){%- endmacro %}

{% macro iso_week(date_expr) -%}
    {{ return(adapter.dispatch('iso_week', 'cs_ops')(date_expr)) }}
{%- endmacro %}
{% macro default__iso_week(date_expr) -%}extract(week from {{ date_expr }}){%- endmacro %}
{% macro bigquery__iso_week(date_expr) -%}extract(isoweek from {{ date_expr }}){%- endmacro %}

{% macro day_name(date_expr) -%}
    {{ return(adapter.dispatch('day_name', 'cs_ops')(date_expr)) }}
{%- endmacro %}
{% macro default__day_name(date_expr) -%}to_char({{ date_expr }}, 'Dy'){%- endmacro %}
{% macro bigquery__day_name(date_expr) -%}format_date('%a', {{ date_expr }}){%- endmacro %}

{# a from-item exposing one column `d` with every day from first to last #}
{% macro date_series(first_day, last_day) -%}
    {{ return(adapter.dispatch('date_series', 'cs_ops')(first_day, last_day)) }}
{%- endmacro %}
{% macro default__date_series(first_day, last_day) -%}
    generate_series({{ first_day }}, {{ last_day }}, interval '1 day') as series(d)
{%- endmacro %}
{% macro bigquery__date_series(first_day, last_day) -%}
    unnest(generate_date_array({{ first_day }}, {{ last_day }})) as d
{%- endmacro %}

{# Incremental strategy. BigQuery has no delete+insert; insert_overwrite replaces whole
   date partitions, which avoids scanning the full target table the way a merge would. #}
{% macro incremental_strategy() -%}
    {{ return('insert_overwrite' if target.type == 'bigquery' else 'delete+insert') }}
{%- endmacro %}

{% macro as_int(expr) -%}
    {{ return(adapter.dispatch('as_int', 'cs_ops')(expr)) }}
{%- endmacro %}
{% macro default__as_int(expr) -%}({{ expr }})::int{%- endmacro %}
{% macro bigquery__as_int(expr) -%}cast({{ expr }} as int64){%- endmacro %}

{% macro as_date(expr) -%}
    {{ return(adapter.dispatch('as_date', 'cs_ops')(expr)) }}
{%- endmacro %}
{% macro default__as_date(expr) -%}({{ expr }})::date{%- endmacro %}
{% macro bigquery__as_date(expr) -%}{{ expr }}{%- endmacro %}

{# Key-account split used by the daily report: KAS skill groups are KA (SPG), the rest Non-KA (SPS). #}
{% macro ka_group(skill_expr) -%}
    case when {{ skill_expr }} like '%-KAS-%' then 'KA' else 'Non-KA' end
{%- endmacro %}
