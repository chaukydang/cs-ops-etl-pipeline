{{ config(materialized='incremental', unique_key='row_key', incremental_strategy='delete+insert') }}

-- CSAT % = share of responses scoring 4 or 5 (5-point survey).
select
    md5(survey_date::text || '|' || coalesce(skill_group, '') || '|' || coalesce(channel, '')) as row_key,
    survey_date,
    skill_group,
    channel,
    count(*)                                          as responses,
    avg(score)                                        as avg_score,
    count(*) filter (where score >= 4)                as satisfied,
    count(*) filter (where score >= 4) / nullif(count(*), 0)::numeric as csat_pct
from {{ ref('stg_csat') }}
where 1 = 1 {{ recent_window('survey_date') }}
group by 1, 2, 3, 4
