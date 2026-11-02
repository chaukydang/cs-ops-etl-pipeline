{#
  Rows lost between the raw tables and staging (duplicates, missing keys, invalid
  dates). A few are normal; more than 1% means something upstream changed.
  The attendance export contains per-day "Sum" roll-up rows on purpose, so they
  are not counted as lost.
#}
with counts as (
    select
        'tickets' as source_name,
        (select count(*) from {{ source('raw', 'tickets') }}) as raw_rows,
        (select count(*) from {{ ref('stg_tickets') }}) as stg_rows
    union all
    select
        'csat',
        (select count(*) from {{ source('raw', 'csat') }}),
        (select count(*) from {{ ref('stg_csat') }})
    union all
    select
        'productivity_daily',
        (select count(*) from {{ source('raw', 'productivity_daily') }}),
        (select count(*) from {{ ref('stg_productivity') }})
    union all
    select
        'attendance',
        (select count(*) from {{ source('raw', 'attendance') }}
          where {{ clean_text('department_latest') }} is distinct from 'Sum'),
        (select count(*) from {{ ref('stg_attendance') }})
)
select
    source_name,
    raw_rows,
    stg_rows,
    (raw_rows - stg_rows) * 1.0 / raw_rows as dropped_ratio
from counts
where raw_rows > 0
  -- * 1.0: PostgreSQL would otherwise do integer division and always get 0
  and (raw_rows - stg_rows) * 1.0 / raw_rows > 0.01
