{{ config(materialized='view') }}
select symbol, period, start, "end", as_of, metric, value_usd, status,
    filed, accession, tag, fact_id, source_url
from {{ source('frozen_packet', 'source_facts') }}
