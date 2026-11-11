with pivoted as (
    select symbol, period, start, "end", as_of,
        {% for metric in ['revenue', 'net_income', 'operating_cash_flow', 'capex'] %}
        cast(max(case when metric = '{{ metric }}' then value_usd end) as decimal(38,0)) as {{ metric }}
        {{ ',' if not loop.last }}
        {% endfor %}
    from {{ ref('stg_facts') }}
    group by symbol, period, start, "end", as_of
)
select *, date_diff('day', start, "end") + 1 as days,
    case when revenue is not null and net_income is not null
        and operating_cash_flow is not null and capex is not null
        then 'ok' else 'missing_input' end as status,
    operating_cash_flow - capex as free_cash_flow,
    operating_cash_flow - net_income as cfo_minus_profit
from pivoted
