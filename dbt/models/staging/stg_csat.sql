select
    {{ clean_text('ticket_id_id') }}                   as ticket_id,
    {{ to_date('official_csat_survey_submit_date') }}  as survey_date,
    {{ clean_text('usertype') }}                       as user_type,
    {{ clean_text('ticket_skill_group_name') }}        as skill_group,
    {{ clean_text('ticket_channel_name_en') }}         as channel,
    lower({{ clean_text('final_dealer_email') }})      as agent_email,
    {{ as_int(to_num('official_csat_survey_score')) }}    as score
from {{ dedupe_by_key(source('raw', 'csat'), clean_text('ticket_id_id') ~ ", " ~ to_date('official_csat_survey_submit_date')) }} as c
where {{ to_date('official_csat_survey_submit_date') }} is not null
  and {{ to_num('official_csat_survey_score') }} is not null
