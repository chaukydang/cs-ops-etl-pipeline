with bounds as (
    select
        least(
            (select min(business_date) from {{ ref('stg_productivity') }}),
            (select min(create_date) from {{ ref('stg_tickets') }})
        ) as first_day,
        greatest(
            (select max(business_date) from {{ ref('stg_productivity') }}),
            (select max(create_date) from {{ ref('stg_tickets') }})
        ) as last_day
),
days as (
    select {{ as_date('d') }} as date_day
    from bounds, {{ date_series('bounds.first_day', 'bounds.last_day') }}
)
select
    date_day,
    {{ week_start_sunday('date_day') }}  as week_start,
    {{ month_start('date_day') }}        as month_start,
    extract(year from date_day)          as year,
    {{ iso_week('date_day') }}           as iso_week,
    {{ day_name('date_day') }}           as day_name,
    {{ day_of_week('date_day') }} in (0, 6) as is_weekend
from days
