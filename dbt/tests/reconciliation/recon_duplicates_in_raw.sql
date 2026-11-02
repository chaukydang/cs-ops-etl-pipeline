{{ config(severity='warn') }}
{#
  Duplicates are removed in staging; this only reports how many there were, so
  a sudden increase gets noticed.
#}
select * from (
    select 'tickets (same ticket_id)' as source_name,
           count(*) - count(distinct {{ clean_text('ticket_id_id') }}) as duplicate_rows
    from {{ source('raw', 'tickets') }}
    where {{ clean_text('ticket_id_id') }} is not null
    union all
    select 'productivity_daily (identical rows)',
           count(*) - count(distinct _row_hash)
    from {{ source('raw', 'productivity_daily') }}
    union all
    select 'attendance (identical rows)',
           count(*) - count(distinct _row_hash)
    from {{ source('raw', 'attendance') }}
) found
where duplicate_rows > 0
