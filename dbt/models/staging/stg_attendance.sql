-- The export contains "Sum" roll-up rows per day with no agent; they are
-- dropped here so the fact table stays at agent x day grain.
select
    {{ to_date('schedule_date_local_timezone') }}      as schedule_date,
    {{ clean_text('department_latest') }}              as department,
    lower({{ clean_text('agent_email') }})             as agent_email,
    coalesce({{ to_num('attendance_count') }}, 0)      as attendance_count,
    coalesce({{ to_num('late_count') }}, 0)            as late_count
from {{ dedupe_exact(source('raw', 'attendance')) }} as a
where {{ clean_text('agent_email') }} is not null
  and {{ clean_text('department_latest') }} is distinct from 'Sum'
  and {{ to_date('schedule_date_local_timezone') }} is not null
