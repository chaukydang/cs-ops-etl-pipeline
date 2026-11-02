{#
  Remove duplicates from a raw table.

  business key  : keep the most recently loaded row per key (late corrections win)
  row hash      : drop exact copies of the same row (same _row_hash)

  Raw tables carry _loaded_at, _source_row_number and _row_hash from the loader.
#}
{% macro dedupe_by_key(relation, key_expr) -%}
    (
        select *
        from (
            select
                raw.*,
                row_number() over (
                    partition by {{ key_expr }}
                    order by _loaded_at desc, _source_row_number desc
                ) as _dedupe_rn
            from {{ relation }} as raw
        ) ranked
        where _dedupe_rn = 1
    )
{%- endmacro %}

{% macro dedupe_exact(relation) -%}
    (
        select *
        from (
            select
                raw.*,
                row_number() over (
                    partition by _row_hash
                    order by _loaded_at desc, _source_row_number desc
                ) as _dedupe_rn
            from {{ relation }} as raw
        ) ranked
        where _dedupe_rn = 1
    )
{%- endmacro %}
