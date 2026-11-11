select symbol, period, as_of from {{ ref('mart_cashflow') }}
group by all having count(*) <> 1
