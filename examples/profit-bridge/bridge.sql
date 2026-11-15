-- Inputs are selected source rows, never Python's derived bridge totals.
-- NULL propagation and adjacent fiscal windows are explicit.
WITH grouped AS (
    SELECT symbol, period, MAX(start) AS start, MAX(end) AS end,
        MAX(CASE WHEN category='anchor' AND line_id='net_income' THEN value_usd END) AS net_income,
        MAX(CASE WHEN category='anchor' AND line_id='operating_cash_flow' THEN value_usd END) AS operating_cash_flow,
        MAX(CASE WHEN category='anchor' AND line_id='capex' THEN value_usd END) AS capex,
        CASE WHEN SUM(category='adjustments')=COUNT(CASE WHEN category='adjustments' THEN value_usd END)
            THEN SUM(CASE WHEN category='adjustments' THEN value_usd END) END AS adjustments,
        CASE WHEN SUM(category='operating_changes')=COUNT(CASE WHEN category='operating_changes' THEN value_usd END)
            THEN SUM(CASE WHEN category='operating_changes' THEN value_usd END) END AS operating_changes,
        MAX(CASE WHEN category='supplemental' AND line_id='tax_expense' THEN value_usd END) AS tax_expense,
        MAX(CASE WHEN category='supplemental' AND line_id='cash_taxes' THEN value_usd END) AS cash_taxes,
        MAX(CASE WHEN category='supplemental' AND line_id='acquisition_line' THEN value_usd END) AS acquisition_line,
        MAX(CASE WHEN category='supplemental' AND line_id='finance_lease_additions' THEN value_usd END) AS finance_lease_additions,
        MAX(CASE WHEN category='supplemental' AND line_id='finance_lease_principal' THEN value_usd END) AS finance_lease_principal,
        MAX(CASE WHEN category='supplemental' AND line_id='finance_lease_interest' THEN value_usd END) AS finance_lease_interest,
        MAX(CASE WHEN category='supplemental' AND line_id='combined_lease_additions' THEN value_usd END) AS combined_lease_additions
    FROM facts GROUP BY symbol, period
), amounts AS (
    SELECT *, net_income+adjustments+operating_changes AS calculated_cfo,
        operating_cash_flow-capex AS free_cash_flow
    FROM grouped
), previous AS (
    SELECT *, LAG(end) OVER w AS previous_end,
        LAG(net_income) OVER w AS previous_profit,
        LAG(adjustments) OVER w AS previous_adjustments,
        LAG(operating_changes) OVER w AS previous_changes,
        LAG(operating_cash_flow) OVER w AS previous_cfo
    FROM amounts WINDOW w AS (PARTITION BY symbol ORDER BY start)
), changes AS (
    SELECT *,
        CASE WHEN julianday(start)-julianday(previous_end)=1 THEN net_income-previous_profit END AS delta_net_income,
        CASE WHEN julianday(start)-julianday(previous_end)=1 THEN adjustments-previous_adjustments END AS delta_adjustments,
        CASE WHEN julianday(start)-julianday(previous_end)=1 THEN operating_changes-previous_changes END AS delta_operating_changes,
        CASE WHEN julianday(start)-julianday(previous_end)=1 THEN operating_cash_flow-previous_cfo END AS delta_cfo
    FROM previous
)
SELECT symbol, period, net_income, adjustments, operating_changes, calculated_cfo,
    operating_cash_flow, operating_cash_flow-calculated_cfo AS reconciliation_residual,
    capex, free_cash_flow, tax_expense, cash_taxes, acquisition_line, finance_lease_additions,
    finance_lease_principal, finance_lease_interest, combined_lease_additions,
    free_cash_flow-acquisition_line AS fcf_less_acquisition_line,
    free_cash_flow-finance_lease_principal AS fcf_less_lease_principal,
    delta_net_income, delta_adjustments, delta_operating_changes, delta_cfo,
    delta_cfo-delta_net_income-delta_adjustments-delta_operating_changes AS delta_residual
FROM changes ORDER BY symbol, start;
