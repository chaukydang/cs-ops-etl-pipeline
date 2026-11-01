select
    md5(agent_email)              as agent_key,
    schedule_date,
    sum(attendance_count)         as attendance_count,
    sum(late_count)               as late_count,
    1 - sum(late_count) / nullif(sum(attendance_count), 0) as on_time_rate
from {{ ref('stg_attendance') }}
group by 1, 2
