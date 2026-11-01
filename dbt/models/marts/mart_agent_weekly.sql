-- Weekly agent scorecard: productivity + attendance + CSAT, Sunday-based weeks.
with prod as (
    select
        agent_key,
        {{ week_start_sunday('business_date') }} as week_start,
        sum(closed)            as closed,
        sum(paid_hours)        as paid_hours,
        sum(productivity_hrs)  as productivity_hrs,
        sum(online_hrs)        as online_hrs,
        sum(busy_hrs)          as busy_hrs
    from {{ ref('fct_productivity_daily') }}
    group by 1, 2
),
att as (
    select
        agent_key,
        {{ week_start_sunday('schedule_date') }} as week_start,
        sum(attendance_count)  as shifts,
        sum(late_count)        as late_shifts
    from {{ ref('fct_attendance_daily') }}
    group by 1, 2
),
csat as (
    select
        md5(agent_email)       as agent_key,
        {{ week_start_sunday('survey_date') }} as week_start,
        count(*)               as csat_responses,
        count(*) filter (where score >= 4) as csat_satisfied
    from {{ ref('stg_csat') }}
    where agent_email is not null
    group by 1, 2
)
select
    prod.agent_key,
    prod.week_start,
    prod.closed,
    prod.paid_hours,
    prod.closed / nullif(prod.productivity_hrs, 0)   as cph,
    prod.online_hrs / nullif(prod.paid_hours, 0)     as online_rate,
    prod.busy_hrs / nullif(prod.online_hrs, 0)       as occupancy,
    att.shifts,
    att.late_shifts,
    1 - att.late_shifts / nullif(att.shifts, 0)      as on_time_rate,
    csat.csat_responses,
    csat.csat_satisfied / nullif(csat.csat_responses, 0)::numeric as csat_pct
from prod
left join att  using (agent_key, week_start)
left join csat using (agent_key, week_start)
