select
    backlog_date,
    user_type,
    backlog_rate,
    unassigned + unprocessed + pending + onhold as open_tickets,
    unassigned,
    unprocessed,
    pending,
    onhold,
    aged_over_24h,
    aged_over_72h,
    closed
from {{ ref('stg_backlog') }}
