{{ config(materialized='incremental', unique_key='row_key', incremental_strategy='delete+insert') }}

select
    md5(agent_email || '|' || schedule_date::text)  as row_key,
    md5(agent_email)              as agent_key,
    schedule_date,
    sum(attendance_count)         as attendance_count,
    sum(late_count)               as late_count,
    1 - sum(late_count) / nullif(sum(attendance_count), 0) as on_time_rate
from {{ ref('stg_attendance') }}
where 1 = 1 {{ recent_window('schedule_date') }}
group by 1, 2, 3
