-- CSAT % = share of responses scoring 4 or 5 (5-point survey).
select
    survey_date,
    skill_group,
    channel,
    count(*)                                          as responses,
    avg(score)                                        as avg_score,
    count(*) filter (where score >= 4)                as satisfied,
    count(*) filter (where score >= 4) / nullif(count(*), 0)::numeric as csat_pct
from {{ ref('stg_csat') }}
group by 1, 2, 3
