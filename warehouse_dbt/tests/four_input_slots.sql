select symbol, period, start, "end", as_of
from {{ ref('stg_facts') }}
group by all having count(*) <> 4 or count(distinct metric) <> 4
