{{ config(severity='warn') }}
select * from {{ ref('stg_csat') }} where score not between 1 and 5
