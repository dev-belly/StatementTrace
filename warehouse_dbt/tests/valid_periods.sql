select * from {{ ref('stg_facts') }} where start > "end"
