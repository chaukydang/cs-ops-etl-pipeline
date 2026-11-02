{#
  Totals in the facts must equal the totals in staging. A difference means the
  incremental facts are stale (for example after a backfill): run
  `dbt build --full-refresh`.
#}
with checks as (
    select
        'productivity.closed' as check_name,
        (select coalesce(sum(closed), 0) from {{ ref('stg_productivity') }}) as expected,
        (select coalesce(sum(closed), 0) from {{ ref('fct_productivity_daily') }}) as actual
    union all
    select
        'productivity.paid_hours',
        (select coalesce(sum(paid_hours), 0) from {{ ref('stg_productivity') }}),
        (select coalesce(sum(paid_hours), 0) from {{ ref('fct_productivity_daily') }})
    union all
    select
        'tickets.count',
        (select count(*) from {{ ref('stg_tickets') }}),
        (select coalesce(sum(tickets), 0) from {{ ref('fct_tickets_daily') }})
    union all
    select
        'csat.responses',
        (select count(*) from {{ ref('stg_csat') }}),
        (select coalesce(sum(responses), 0) from {{ ref('fct_csat_daily') }})
    union all
    select
        'attendance.shifts',
        (select coalesce(sum(attendance_count), 0) from {{ ref('stg_attendance') }}),
        (select coalesce(sum(attendance_count), 0) from {{ ref('fct_attendance_daily') }})
)
select check_name, expected, actual
from checks
where abs(expected - actual) > 0.0001
