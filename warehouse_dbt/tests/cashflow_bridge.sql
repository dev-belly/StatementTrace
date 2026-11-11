select * from {{ ref('mart_cashflow') }} where bridge_residual <> 0
