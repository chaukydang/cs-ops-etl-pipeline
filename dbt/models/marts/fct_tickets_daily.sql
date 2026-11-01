select
    create_date,
    skill_group,
    user_type,
    channel,
    count(*)                                          as tickets,
    count(close_date)                                 as closed_tickets,
    count(*) filter (where is_fcr)                    as fcr_tickets,
    count(*) filter (where is_resolved_24h)           as resolved_24h_tickets,
    avg(first_response_hrs)                           as avg_first_response_hrs,
    avg(resolution_hrs)                               as avg_resolution_hrs,
    count(*) filter (where is_fcr) / nullif(count(*), 0)::numeric as fcr_rate
from {{ ref('stg_tickets') }}
group by 1, 2, 3, 4
