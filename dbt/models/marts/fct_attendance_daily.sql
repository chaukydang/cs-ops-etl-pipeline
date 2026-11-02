{{ config(
    materialized='incremental',
    unique_key='row_key',
    incremental_strategy=incremental_strategy(),
    partition_by={'field': 'schedule_date', 'data_type': 'date'},
    cluster_by=['agent_key']
) }}

select
    {{ hash_key("agent_email || '|' || " ~ as_text('schedule_date')) }} as row_key,
    {{ hash_key('agent_email') }} as agent_key,
    schedule_date,
    sum(attendance_count)         as attendance_count,
    sum(late_count)               as late_count,
    1 - sum(late_count) / nullif(sum(attendance_count), 0) as on_time_rate
from {{ ref('stg_attendance') }}
where 1 = 1 {{ recent_window('schedule_date') }}
group by 1, 2, 3
