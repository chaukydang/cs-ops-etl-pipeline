select *
from {{ ref('fct_productivity_daily') }}
where paid_hours < 0 or online_hrs < 0 or busy_hrs < 0
