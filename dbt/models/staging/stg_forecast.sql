select
    {{ to_date('business_date') }}                     as business_date,
    {{ clean_text('skill_group_name') }}               as skill_group,
    {{ to_num('forecast_traffic') }}                   as forecast_traffic,
    {{ to_num('actual_traffic') }}                     as actual_traffic,
    {{ to_num('forecast_fte') }}                       as forecast_fte,
    {{ to_num('production_schedule_fte') }}            as scheduled_fte
from {{ dedupe_exact(source('raw', 'forecast_actual')) }} as f
where {{ to_date('business_date') }} is not null
