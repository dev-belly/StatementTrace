select * from {{ ref('stg_facts') }} where not (
    (status = 'selected' and value_usd is not null and filed is not null
        and accession is not null and tag is not null and fact_id is not null and source_url is not null)
    or (status = 'missing_input' and value_usd is null and filed is null
        and accession is null and tag is null and fact_id is null and source_url is null)
)
