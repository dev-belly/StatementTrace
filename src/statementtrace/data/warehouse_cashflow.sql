-- Input: typed, selected source_facts. Amounts never pass through DOUBLE.
-- Ratios retain numerator/denominator pairs; zero denominators stay NULL.
WITH pivoted AS (
    SELECT symbol, period, start, "end", as_of,
        CAST(MAX(CASE WHEN metric = 'revenue' THEN value_usd END) AS DECIMAL(38,0)) AS revenue,
        CAST(MAX(CASE WHEN metric = 'net_income' THEN value_usd END) AS DECIMAL(38,0)) AS net_income,
        CAST(MAX(CASE WHEN metric = 'operating_cash_flow' THEN value_usd END) AS DECIMAL(38,0)) AS operating_cash_flow,
        CAST(MAX(CASE WHEN metric = 'capex' THEN value_usd END) AS DECIMAL(38,0)) AS capex
    FROM source_facts
    GROUP BY symbol, period, start, "end", as_of
), annual AS (
    SELECT *, date_diff('day', start, "end") + 1 AS days,
        CASE WHEN revenue IS NOT NULL AND net_income IS NOT NULL
            AND operating_cash_flow IS NOT NULL AND capex IS NOT NULL
            THEN 'ok' ELSE 'missing_input' END AS status,
        operating_cash_flow - capex AS free_cash_flow,
        operating_cash_flow - net_income AS cfo_minus_profit
    FROM pivoted
), lagged AS (
    SELECT *, LAG("end") OVER w AS previous_end,
        LAG(net_income) OVER w AS previous_profit,
        LAG(free_cash_flow) OVER w AS previous_fcf,
        LAG(operating_cash_flow) OVER w AS previous_cfo,
        LAG(capex) OVER w AS previous_capex
    FROM annual
    WINDOW w AS (PARTITION BY symbol, as_of ORDER BY start)
), changes AS (
    SELECT *,
        CASE WHEN start = previous_end + INTERVAL 1 DAY THEN net_income - previous_profit END AS delta_profit,
        CASE WHEN start = previous_end + INTERVAL 1 DAY THEN free_cash_flow - previous_fcf END AS delta_fcf,
        CASE WHEN start = previous_end + INTERVAL 1 DAY THEN operating_cash_flow - previous_cfo END AS delta_cfo,
        CASE WHEN start = previous_end + INTERVAL 1 DAY THEN previous_capex - capex END AS negative_delta_capex
    FROM lagged
)
SELECT symbol, period, start, "end", as_of, days, status,
    revenue, net_income, operating_cash_flow, capex, free_cash_flow, cfo_minus_profit,
    CASE WHEN net_income IS NOT NULL AND revenue <> 0 THEN net_income END AS net_margin_numerator,
    CASE WHEN net_income IS NOT NULL AND revenue <> 0 THEN revenue END AS net_margin_denominator,
    CASE WHEN free_cash_flow IS NOT NULL AND revenue <> 0 THEN free_cash_flow END AS fcf_margin_numerator,
    CASE WHEN free_cash_flow IS NOT NULL AND revenue <> 0 THEN revenue END AS fcf_margin_denominator,
    CASE WHEN operating_cash_flow IS NOT NULL AND net_income <> 0 THEN operating_cash_flow END AS cash_conversion_numerator,
    CASE WHEN operating_cash_flow IS NOT NULL AND net_income <> 0 THEN net_income END AS cash_conversion_denominator,
    CASE WHEN capex IS NOT NULL AND operating_cash_flow <> 0 THEN capex END AS capex_cfo_numerator,
    CASE WHEN capex IS NOT NULL AND operating_cash_flow <> 0 THEN operating_cash_flow END AS capex_cfo_denominator,
    CASE WHEN delta_profit IS NOT NULL AND previous_profit <> 0 THEN delta_profit END AS net_income_growth_numerator,
    CASE WHEN delta_profit IS NOT NULL AND previous_profit <> 0 THEN previous_profit END AS net_income_growth_denominator,
    CASE WHEN delta_fcf IS NOT NULL AND previous_fcf <> 0 THEN delta_fcf END AS fcf_growth_numerator,
    CASE WHEN delta_fcf IS NOT NULL AND previous_fcf <> 0 THEN previous_fcf END AS fcf_growth_denominator,
    delta_cfo, negative_delta_capex, delta_fcf,
    delta_fcf - delta_cfo - negative_delta_capex AS bridge_residual
FROM changes
ORDER BY symbol, start
