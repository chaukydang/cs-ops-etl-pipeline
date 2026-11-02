{{ config(
    materialized='incremental',
    unique_key='row_key',
    incremental_strategy=incremental_strategy(),
    partition_by={'field': 'business_date', 'data_type': 'date'},
    cluster_by=['agent_key']
) }}

select
    {{ hash_key("agent_email || '|' || " ~ as_text('business_date') ~ " || '|' || coalesce(segment, '') || '|' || coalesce(skill_group, '')") }} as row_key,
    {{ hash_key('agent_email') }}                          as agent_key,
    business_date,
    segment,
    skill_group,
    {{ ka_group('skill_group') }}                          as ka_group,
    sum(closed)                                            as closed,
    sum(contacts)                                          as contacts,
    sum(paid_hours)                                        as paid_hours,
    sum(online_hrs)                                        as online_hrs,
    sum(busy_hrs)                                          as busy_hrs,
    sum(idle_hrs)                                          as idle_hrs,
    sum(abnormal_hrs)                                      as abnormal_hrs,
    sum(productivity_hrs)                                  as productivity_hrs,
    sum(break_hrs + training_hrs + meeting_hrs + other_hrs) as non_production_hrs,
    sum(closed) / nullif(sum(productivity_hrs), 0)         as cph,
    -- Occupancy = productive hours / hours the agent was available to work;
    -- Utilization = available hours / paid hours (same definitions as the BI report).
    sum(productivity_hrs) / nullif(sum(online_hrs + busy_hrs + idle_hrs + abnormal_hrs), 0) as occupancy,
    sum(online_hrs + busy_hrs + idle_hrs + abnormal_hrs) / nullif(sum(paid_hours), 0)      as utilization
from {{ ref('stg_productivity') }}
where 1 = 1 {{ recent_window('business_date') }}
group by 1, 2, 3, 4, 5, 6
