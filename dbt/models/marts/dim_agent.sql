-- One row per agent. Attributes come from the most recent productivity row,
-- since tier / tenure / team change over time. Facts join on agent_key so the
-- e-mail only needs to be exposed here.
with ranked as (
    select
        agent_email,
        department,
        tier,
        tenure,
        skill_group,
        business_date,
        row_number() over (
            partition by agent_email order by business_date desc
        ) as rn,
        min(business_date) over (partition by agent_email) as first_seen,
        max(business_date) over (partition by agent_email) as last_seen
    from {{ ref('stg_productivity') }}
)
select
    {{ hash_key('agent_email') }}    as agent_key,
    agent_email,
    department,
    tier,
    tenure,
    skill_group,
    first_seen,
    last_seen
from ranked
where rn = 1
