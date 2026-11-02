{{ config(
    materialized='incremental',
    unique_key='row_key',
    incremental_strategy=incremental_strategy(),
    partition_by={'field': 'create_date', 'data_type': 'date'},
    cluster_by=['skill_group']
) }}

select
    {{ hash_key(as_text('create_date') ~ " || '|' || coalesce(skill_group, '') || '|' || coalesce(user_type, '') || '|' || coalesce(channel, '')") }} as row_key,
    create_date,
    skill_group,
    user_type,
    channel,
    count(*)                                          as tickets,
    count(close_date)                                 as closed_tickets,
    {{ count_if('is_fcr') }}                          as fcr_tickets,
    {{ count_if('is_resolved_24h') }}                 as resolved_24h_tickets,
    avg(first_response_hrs)                           as avg_first_response_hrs,
    avg(resolution_hrs)                               as avg_resolution_hrs,
    {{ ratio(count_if('is_fcr'), 'count(*)') }}       as fcr_rate
from {{ ref('stg_tickets') }}
where 1 = 1 {{ recent_window('create_date') }}
group by 1, 2, 3, 4, 5
