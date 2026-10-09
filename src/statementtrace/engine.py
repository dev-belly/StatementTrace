"""Select entity-wide USD annual facts by filing date and exact fiscal period."""

import re
from dataclasses import dataclass
from fractions import Fraction

from .contracts import ContractError, canonical, digest, display, exact, integer, iso_date

# Alias order is explicit; it never resolves conflicting values silently.
METRICS = {
    "revenue": ("duration", ("RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues")),
    "operating_income": ("duration", ("OperatingIncomeLoss",)),
    "net_income": ("duration", ("NetIncomeLoss",)),
    "operating_cash_flow": ("duration", ("NetCashProvidedByUsedInOperatingActivities",)),
    "capex": ("duration", ("PaymentsToAcquirePropertyPlantAndEquipment",)),
    "assets": ("instant", ("Assets",)),
    "liabilities": ("instant", ("Liabilities",)),
    "equity": ("instant", ("StockholdersEquity",)),
    "current_assets": ("instant", ("AssetsCurrent",)),
    "current_liabilities": ("instant", ("LiabilitiesCurrent",)),
    "cash": ("instant", ("CashAndCashEquivalentsAtCarryingValue",)),
}


@dataclass(frozen=True)
class Fact:
    metric: str
    tag: str
    unit: str
    record: dict
    fact_id: str
    source_url: str

    @property
    def value(self):
        return self.record["val"]


def validate_request(request):
    if not isinstance(request, dict) or set(request) != {"periods", "as_of_dates"}:
        raise ContractError("Request requires exactly periods and as_of_dates")
    periods, cutoffs = request["periods"], request["as_of_dates"]
    if not isinstance(periods, list) or not periods:
        raise ContractError("periods must be a nonempty list")
    previous_end, labels = None, set()
    for period in periods:
        if not isinstance(period, dict) or set(period) != {"label", "start", "end"}:
            raise ContractError("Each period requires label, start, end")
        label = period["label"]
        if not isinstance(label, str) or not label or label in labels:
            raise ContractError("Period labels must be nonempty and unique")
        labels.add(label)
        start = iso_date(period["start"], "period start")
        end = iso_date(period["end"], "period end")
        if start > end or (previous_end is not None and start <= previous_end):
            raise ContractError("Periods must be ordered, non-overlapping and start <= end")
        previous_end = end
    if not isinstance(cutoffs, list) or not cutoffs:
        raise ContractError("as_of_dates must be a nonempty list")
    for cutoff in cutoffs:
        iso_date(cutoff, "as_of")
    if cutoffs != sorted(set(cutoffs)):
        raise ContractError("as_of_dates must be sorted and unique")
    return request


def normalize(data):
    if not isinstance(data, dict):
        raise ContractError("Company facts must be a JSON object")
    cik = integer(data.get("cik"), "cik", 1)
    if cik > 9999999999:
        raise ContractError("cik must fit ten digits")
    if not isinstance(data.get("entityName"), str) or not data["entityName"]:
        raise ContractError("entityName is required")
    if not isinstance(data.get("facts"), dict):
        raise ContractError("facts must be an object")
    concepts = data["facts"].get("us-gaap", {})
    if not isinstance(concepts, dict):
        raise ContractError("facts.us-gaap must be an object")
    result = []
    for metric, (_, tags) in METRICS.items():
        for tag in tags:
            if tag not in concepts:
                continue
            concept = concepts[tag]
            if not isinstance(concept, dict) or not isinstance(concept.get("units"), dict):
                raise ContractError(f"{tag}.units must be an object")
            for unit, rows in sorted(concept["units"].items()):
                if not isinstance(rows, list):
                    raise ContractError(f"{tag}.{unit} must be a list")
                for row in rows:
                    if not isinstance(row, dict):
                        raise ContractError(f"{tag} contains a non-object record")
                    # Other units are retained as exclusions, but not used for USD ratios.
                    if unit == "USD":
                        integer(row.get("val"), f"{tag}.val")
                    if "val" not in row:
                        raise ContractError(f"{tag}.val is required")
                    end = iso_date(row.get("end"), "fact end")
                    filed = iso_date(row.get("filed"), "filed")
                    start = iso_date(row["start"], "fact start") if "start" in row else None
                    if end > filed or (start is not None and start > end):
                        raise ContractError("Fact dates must satisfy start <= end <= filed")
                    accn, form = row.get("accn"), row.get("form")
                    if not isinstance(accn, str) or not re.fullmatch(r"\d{10}-\d{2}-\d{6}", accn):
                        raise ContractError("Invalid accession number")
                    if not isinstance(form, str) or not form:
                        raise ContractError("form is required")
                    source = f"https://www.sec.gov/Archives/edgar/data/{cik}/{accn.replace('-', '')}/{accn}-index.htm"
                    fact_id = digest(canonical({"cik": cik, "tag": tag, "unit": unit, "record": row}))
                    result.append(Fact(metric, tag, unit, row, fact_id, source))
    # Same record duplicated by a feed is idempotent; row order cannot break a tie.
    return sorted({f.fact_id: f for f in result}.values(), key=lambda f: f.fact_id)


def choose(facts, metric, period, cutoff):
    kind, tags = METRICS[metric]
    reasons, eligible = {}, []
    for fact in facts:
        if fact.metric != metric:
            continue
        row = fact.record
        if fact.unit != "USD":
            reason = "wrong_unit"
        elif row["form"] not in {"10-K", "10-K/A"}:
            reason = "wrong_form"
        elif (
            row["end"] != period["end"]
            or (kind == "duration" and row.get("start") != period["start"])
            or (kind == "instant" and "start" in row)
        ):
            reason = "wrong_period"
        elif row["filed"] > cutoff:
            reason = "future_filing"
        else:
            reason = "eligible"
            eligible.append(fact)
        reasons[fact.fact_id] = reason
    if not eligible:
        return None, reasons
    latest = max(f.record["filed"] for f in eligible)
    latest_facts = [f for f in eligible if f.record["filed"] == latest]
    # A day-only API cannot order conflicting same-day filings; fail closed.
    if len({f.value for f in latest_facts}) != 1:
        raise ContractError(f"Conflicting latest facts for {metric}, {period['label']}, {cutoff}")
    selected = min(latest_facts, key=lambda f: (tags.index(f.tag), f.record["accn"], f.fact_id))
    for fact in eligible:
        reasons[fact.fact_id] = "selected" if fact == selected else "superseded"
    return selected, reasons


def calculate(selected, prior_revenue):
    """Each output carries the IDs of the inputs actually used in its formula."""
    specs = [
        ("net_margin", "net_income / revenue", ("net_income", "revenue"), "divide", "ratio"),
        ("operating_margin", "operating_income / revenue", ("operating_income", "revenue"), "divide", "ratio"),
        (
            "cash_conversion",
            "operating_cash_flow / net_income",
            ("operating_cash_flow", "net_income"),
            "divide",
            "ratio",
        ),
        (
            "current_ratio",
            "current_assets / current_liabilities",
            ("current_assets", "current_liabilities"),
            "divide",
            "ratio",
        ),
        ("liability_ratio", "liabilities / assets", ("liabilities", "assets"), "divide", "ratio"),
        ("free_cash_flow", "operating_cash_flow - capex", ("operating_cash_flow", "capex"), "subtract", "USD"),
        (
            "fcf_margin",
            "(operating_cash_flow - capex) / revenue",
            ("operating_cash_flow", "capex", "revenue"),
            "fcf_divide",
            "ratio",
        ),
        ("balance_residual", "assets - liabilities - equity", ("assets", "liabilities", "equity"), "balance", "USD"),
        (
            "revenue_growth",
            "revenue / previous_period_revenue - 1",
            ("revenue", "previous_period_revenue"),
            "growth",
            "ratio",
        ),
    ]
    available = {**selected, "previous_period_revenue": prior_revenue}
    outputs = []
    for name, formula, keys, operation, unit in specs:
        inputs = [available[key] for key in keys]
        missing = [key for key, fact in zip(keys, inputs, strict=True) if fact is None]
        value, status = None, "missing_input" if missing else "ok"
        if not missing:
            values = [Fraction(f.value) for f in inputs]
            if operation in {"divide", "fcf_divide", "growth"} and values[-1] == 0:
                status = "zero_denominator"
            elif operation == "divide":
                value = values[0] / values[1]
            elif operation == "subtract":
                value = values[0] - values[1]
            elif operation == "fcf_divide":
                value = (values[0] - values[1]) / values[2]
            elif operation == "balance":
                value = values[0] - values[1] - values[2]
            elif operation == "growth":
                value = values[0] / values[1] - 1
        outputs.append(
            {
                "metric": name,
                "formula": formula,
                "unit": unit,
                "status": status,
                "exact": exact(value),
                "display": display(value),
                "missing": missing,
                "inputs": [
                    {"role": key, "fact_id": fact.fact_id} for key, fact in zip(keys, inputs, strict=True) if fact
                ],
            }
        )
    return outputs


def analyze(data, request):
    request = validate_request(request)
    facts = normalize(data)
    panels, decisions = [], []
    for cutoff in request["as_of_dates"]:
        prior_revenue = None
        for period in request["periods"]:
            selected = {}
            for metric in METRICS:
                fact, reasons = choose(facts, metric, period, cutoff)
                selected[metric] = fact
                decisions.extend(
                    {"as_of": cutoff, "period": period["label"], "metric": metric, "fact_id": fid, "reason": reason}
                    for fid, reason in sorted(reasons.items())
                )
            panels.append(
                {
                    "as_of": cutoff,
                    "period": period,
                    "duration_days": (iso_date(period["end"], "end") - iso_date(period["start"], "start")).days + 1,
                    "facts": {
                        key: (
                            {
                                "fact_id": f.fact_id,
                                "tag": f.tag,
                                "unit": f.unit,
                                "record": f.record,
                                "source_url": f.source_url,
                            }
                            if f
                            else None
                        )
                        for key, f in selected.items()
                    },
                    "metrics": calculate(selected, prior_revenue),
                }
            )
            prior_revenue = selected["revenue"]
    return {
        "schema_version": 1,
        "entity": data["entityName"],
        "cik": data["cik"],
        "cutoff_policy": "SEC filed date <= as_of; date granularity, no intraday claim",
        "fact_count": len(facts),
        "panels": panels,
        "decisions": decisions,
    }
