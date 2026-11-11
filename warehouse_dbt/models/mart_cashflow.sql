with lagged as (
    select *, lag("end") over w as previous_end,
        lag(net_income) over w as previous_profit,
        lag(free_cash_flow) over w as previous_fcf,
        lag(operating_cash_flow) over w as previous_cfo,
        lag(capex) over w as previous_capex
    from {{ ref('int_annual_cashflow') }}
    window w as (partition by symbol, as_of order by start)
), changes as (
    select *,
        case when start = previous_end + interval 1 day then net_income - previous_profit end as delta_profit,
        case when start = previous_end + interval 1 day then free_cash_flow - previous_fcf end as delta_fcf,
        case when start = previous_end + interval 1 day then operating_cash_flow - previous_cfo end as delta_cfo,
        case when start = previous_end + interval 1 day then previous_capex - capex end as negative_delta_capex
    from lagged
)
select symbol, period, start, "end", as_of, days, status,
    revenue, net_income, operating_cash_flow, capex, free_cash_flow, cfo_minus_profit,
    {% for name, numerator, denominator in [
        ('net_margin', 'net_income', 'revenue'),
        ('fcf_margin', 'free_cash_flow', 'revenue'),
        ('cash_conversion', 'operating_cash_flow', 'net_income'),
        ('capex_cfo', 'capex', 'operating_cash_flow'),
        ('net_income_growth', 'delta_profit', 'previous_profit'),
        ('fcf_growth', 'delta_fcf', 'previous_fcf')
    ] %}
    case when {{ numerator }} is not null and {{ denominator }} <> 0
        then {{ numerator }} end as {{ name }}_numerator,
    case when {{ numerator }} is not null and {{ denominator }} <> 0
        then {{ denominator }} end as {{ name }}_denominator,
    {% endfor %}
    delta_cfo, negative_delta_capex, delta_fcf,
    delta_fcf - delta_cfo - negative_delta_capex as bridge_residual
from changes
