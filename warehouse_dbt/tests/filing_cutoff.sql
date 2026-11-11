select * from {{ ref('stg_facts') }} where filed > as_of
