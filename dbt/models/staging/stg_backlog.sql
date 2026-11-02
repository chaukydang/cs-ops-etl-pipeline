select
    {{ to_date('date') }}                              as backlog_date,
    {{ clean_text('user_type_name_en') }}              as user_type,
    {{ to_num('backlog_rate') }}                       as backlog_rate,
    coalesce({{ to_num('unassigned_cnt') }}, 0)        as unassigned,
    coalesce({{ to_num('unprocessed_cnt') }}, 0)       as unprocessed,
    coalesce({{ to_num('pending_cnt') }}, 0)           as pending,
    coalesce({{ to_num('onhold_cnt') }}, 0)            as onhold,
    coalesce({{ to_num('unassigned_duration_over_24h_ticket_cnt') }}, 0)
      + coalesce({{ to_num('unprocessed_duration_over_24h_ticket_cnt') }}, 0)
      + coalesce({{ to_num('processing_duration_over_24h_ticket_cnt') }}, 0) as aged_over_24h,
    coalesce({{ to_num('pending_duration_over_72h_ticket_cnt') }}, 0)
      + coalesce({{ to_num('onhold_duration_over_72h_ticket_cnt') }}, 0)     as aged_over_72h,
    coalesce({{ to_num('close_cnt') }}, 0)             as closed
from {{ dedupe_exact(source('raw', 'backlog_daily')) }} as b
where {{ to_date('date') }} is not null
