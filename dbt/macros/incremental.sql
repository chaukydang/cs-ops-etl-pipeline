{#
  Facts are rebuilt only for the last `lookback_days` days (default 45, a bit
  more than the 5-week rolling download). Older history is left alone.
  After a backfill that touches older dates, run:  dbt build --full-refresh
#}
{% macro recent_window(date_col) -%}
    {%- if is_incremental() %}
    and {{ date_col }} >= (
        select coalesce(max({{ date_col }}), date '1900-01-01') from {{ this }}
    ) - {{ var('lookback_days', 45) }}
    {%- endif %}
{%- endmacro %}
