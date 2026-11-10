-- Input: source_facts.csv imported into facts. Amounts are integral USD.
-- This query recomputes arithmetic on already selected filing/period facts.
-- It does not independently repeat the Python fact-selection algorithm.
WITH pivoted AS (
    SELECT symbol, period, start, end,
        MAX(CASE WHEN metric = 'revenue' THEN value_usd END) AS revenue,
        MAX(CASE WHEN metric = 'net_income' THEN value_usd END) AS net_income,
        MAX(CASE WHEN metric = 'operating_cash_flow' THEN value_usd END) AS operating_cash_flow,
        MAX(CASE WHEN metric = 'capex' THEN value_usd END) AS capex
    FROM facts
    GROUP BY symbol, period, start, end
), amounts AS (
    SELECT *, operating_cash_flow - capex AS free_cash_flow,
        operating_cash_flow - net_income AS cfo_minus_profit
    FROM pivoted
), prior AS (
    SELECT *, LAG(end) OVER w AS previous_end,
        LAG(net_income) OVER w AS previous_profit,
        LAG(operating_cash_flow) OVER w AS previous_cfo,
        LAG(capex) OVER w AS previous_capex,
        LAG(free_cash_flow) OVER w AS previous_fcf
    FROM amounts
    WINDOW w AS (PARTITION BY symbol ORDER BY start)
), paired AS (
    SELECT *,
        CASE WHEN date(previous_end, '+1 day') = start THEN previous_profit END AS profit_base,
        CASE WHEN date(previous_end, '+1 day') = start THEN previous_fcf END AS fcf_base,
        CASE WHEN date(previous_end, '+1 day') = start THEN operating_cash_flow - previous_cfo END AS delta_cfo,
        CASE WHEN date(previous_end, '+1 day') = start THEN previous_capex - capex END AS negative_delta_capex,
        CASE WHEN date(previous_end, '+1 day') = start THEN free_cash_flow - previous_fcf END AS delta_fcf
    FROM prior
)
SELECT symbol, period, revenue, net_income, operating_cash_flow, capex,
    free_cash_flow, cfo_minus_profit,
    1.0 * net_income / NULLIF(revenue, 0) AS net_margin,
    1.0 * free_cash_flow / NULLIF(revenue, 0) AS fcf_margin,
    1.0 * operating_cash_flow / NULLIF(net_income, 0) AS cash_conversion,
    1.0 * capex / NULLIF(operating_cash_flow, 0) AS capex_cfo,
    1.0 * (net_income - profit_base) / NULLIF(profit_base, 0) AS net_income_growth,
    1.0 * (free_cash_flow - fcf_base) / NULLIF(fcf_base, 0) AS fcf_growth,
    delta_cfo, negative_delta_capex, delta_fcf,
    delta_fcf - delta_cfo - negative_delta_capex AS bridge_residual
FROM paired
ORDER BY symbol, start;
