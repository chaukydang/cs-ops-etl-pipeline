{{ config(
    materialized='incremental',
    unique_key='row_key',
    incremental_strategy=incremental_strategy(),
    partition_by={'field': 'survey_date', 'data_type': 'date'},
    cluster_by=['skill_group']
) }}

-- CSAT % = share of responses scoring 4 or 5 (5-point survey).
select
    {{ hash_key(as_text('survey_date') ~ " || '|' || coalesce(skill_group, '') || '|' || coalesce(channel, '')") }} as row_key,
    survey_date,
    skill_group,
    channel,
    count(*)                                          as responses,
    avg(score)                                        as avg_score,
    {{ count_if('score >= 4') }}                      as satisfied,
    {{ ratio(count_if('score >= 4'), 'count(*)') }}   as csat_pct
from {{ ref('stg_csat') }}
where 1 = 1 {{ recent_window('survey_date') }}
group by 1, 2, 3, 4
