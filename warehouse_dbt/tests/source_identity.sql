select symbol, period, start, "end", as_of, metric
from {{ ref('stg_facts') }}
group by all having count(*) <> 1
