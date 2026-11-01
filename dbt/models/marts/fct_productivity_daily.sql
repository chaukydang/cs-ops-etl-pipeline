{{ config(materialized='incremental', unique_key='row_key', incremental_strategy='delete+insert') }}

select
    md5(agent_email || '|' || business_date::text || '|'
        || coalesce(segment, '') || '|' || coalesce(skill_group, '')) as row_key,
    md5(agent_email)                                       as agent_key,
    business_date,
    segment,
    skill_group,
    sum(closed)                                            as closed,
    sum(contacts)                                          as contacts,
    sum(paid_hours)                                        as paid_hours,
    sum(online_hrs)                                        as online_hrs,
    sum(busy_hrs)                                          as busy_hrs,
    sum(productivity_hrs)                                  as productivity_hrs,
    sum(break_hrs + training_hrs + meeting_hrs + other_hrs) as non_production_hrs,
    sum(closed) / nullif(sum(productivity_hrs), 0)         as cph,
    sum(online_hrs) / nullif(sum(paid_hours), 0)           as online_rate,
    sum(busy_hrs) / nullif(sum(online_hrs), 0)             as occupancy
from {{ ref('stg_productivity') }}
where 1 = 1 {{ recent_window('business_date') }}
group by 1, 2, 3, 4, 5
