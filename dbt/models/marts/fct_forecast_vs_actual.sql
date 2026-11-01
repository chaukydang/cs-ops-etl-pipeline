select
    business_date,
    skill_group,
    forecast_traffic,
    actual_traffic,
    actual_traffic - forecast_traffic                                  as traffic_error,
    abs(actual_traffic - forecast_traffic) / nullif(actual_traffic, 0) as abs_pct_error,
    forecast_fte,
    scheduled_fte,
    scheduled_fte - forecast_fte                                       as fte_gap,
    actual_traffic / nullif(scheduled_fte, 0)                          as traffic_per_scheduled_fte
from {{ ref('stg_forecast') }}
