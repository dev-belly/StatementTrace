select * from {{ ref('stg_facts') }} where metric = 'capex' and value_usd < 0
