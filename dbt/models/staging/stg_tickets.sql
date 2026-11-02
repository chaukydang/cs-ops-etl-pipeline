select
    {{ clean_text('ticket_id_id') }}                   as ticket_id,
    {{ to_date('create_date') }}                       as create_date,
    {{ to_date('close_date') }}                        as close_date,
    -- IM conversations are handled by the IM skill group, the rest by the ticket skill group
    coalesce(
        case when {{ clean_text('ticket_channel_name_en') }} = 'IM' then {{ clean_text('im_skill_group_name_im') }} end,
        {{ clean_text('ticket_skill_group_name') }}
    )                                                  as skill_group,
    lower({{ clean_text('final_dealer_email') }})      as agent_email,
    {{ clean_text('user_type_name_en') }}              as user_type,
    {{ clean_text('ticket_channel_name_en') }}         as channel,
    {{ clean_text('country') }}                        as country,
    {{ clean_text('sub_status_name_en') }}             as sub_status,
    {{ to_num('total_first_response_time_hrs') }}      as first_response_hrs,
    {{ to_num('resolution_hours') }}                   as resolution_hrs,
    ({{ to_num('first_contact_resolution') }} = 1)     as is_fcr,
    ({{ to_num('official_ticket_24h_resolution_rate_24h') }} = 1) as is_resolved_24h
from {{ dedupe_by_key(source('raw', 'tickets'), clean_text('ticket_id_id')) }} as t
where {{ to_date('create_date') }} is not null
  and {{ clean_text('ticket_id_id') }} is not null
