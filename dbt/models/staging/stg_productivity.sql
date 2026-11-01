select
    lower({{ clean_text('agent_email') }})            as agent_email,
    {{ to_date('business_date') }}                    as business_date,
    {{ clean_text('segment') }}                       as segment,
    {{ clean_text('department_name') }}               as department,
    {{ clean_text('tier') }}                          as tier,
    {{ clean_text('tenure') }}                        as tenure,
    {{ clean_text('agent_primary_skill_group_name') }} as skill_group,
    {{ clean_text('cs_sps_spg_efficiency_official') }} as efficiency_group,
    coalesce({{ to_num('close') }}, 0)                as closed,
    coalesce({{ to_num('contact_new') }}, 0)          as contacts,
    coalesce({{ to_num('paid_hours') }}, 0)           as paid_hours,
    coalesce({{ to_num('online_hrs') }}, 0)           as online_hrs,
    coalesce({{ to_num('busy_hrs') }}, 0)             as busy_hrs,
    coalesce({{ to_num('idle_hrs') }}, 0)             as idle_hrs,
    coalesce({{ to_num('abnormal_hrs') }}, 0)         as abnormal_hrs,
    coalesce({{ to_num('break_hrs') }}, 0)            as break_hrs,
    coalesce({{ to_num('training_hrs') }}, 0)         as training_hrs,
    coalesce({{ to_num('meeting_hrs') }}, 0)          as meeting_hrs,
    coalesce({{ to_num('other_hrs') }}, 0)            as other_hrs,
    coalesce({{ to_num('productivity_numerator_hrs') }}, 0) as productivity_hrs
from {{ source('raw', 'productivity_daily') }}
where {{ to_date('business_date') }} is not null
  and {{ clean_text('agent_email') }} is not null
