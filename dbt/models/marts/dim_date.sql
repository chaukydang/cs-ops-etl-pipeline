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
)
select
    d::date                                         as date_day,
    {{ week_start_sunday('d::date') }}              as week_start,
    date_trunc('month', d)::date                    as month_start,
    extract(year from d)::int                       as year,
    extract(week from d)::int                       as iso_week,
    to_char(d, 'Dy')                                as day_name,
    extract(dow from d) in (0, 6)                   as is_weekend
from bounds,
     generate_series(bounds.first_day, bounds.last_day, interval '1 day') as d
