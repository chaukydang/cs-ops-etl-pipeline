select
    {{ hash_key(as_text('backlog_date') ~ " || '|' || coalesce(user_type, '')") }} as row_key,
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
