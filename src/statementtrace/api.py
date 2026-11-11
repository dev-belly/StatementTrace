"""Read-only, typed HTTP access to a captured and verified financial packet."""

import tempfile
from datetime import date
from pathlib import Path
from typing import Annotated, Generic, Literal, TypeVar

from fastapi import FastAPI, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from .cashflow import AMOUNTS, BRIDGE, RATIOS
from .contracts import ContractError, canonical, digest, read_json
from .warehouse import MEMBERS, verify_warehouse

IntegerText = Annotated[str, Field(pattern=r"^-?(0|[1-9][0-9]*)$", description="Exact integer, serialized as text")]
Metric = Literal["revenue", "net_income", "operating_cash_flow", "capex"]
T = TypeVar("T")


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Identity(Model):
    snapshot_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    as_of: date


class Snapshot(Identity):
    source_rows: int
    issuer_years: int
    currency: Literal["USD"] = "USD"
    availability_rule: Literal["filed <= as_of"] = "filed <= as_of"


class ExactRatio(Model):
    numerator: IntegerText
    denominator: Annotated[str, Field(pattern=r"^[1-9][0-9]*$")]


class Amounts(Model):
    revenue: IntegerText | None
    net_income: IntegerText | None
    operating_cash_flow: IntegerText | None
    capex: IntegerText | None
    free_cash_flow: IntegerText | None
    cfo_minus_profit: IntegerText | None


class Ratios(Model):
    net_margin: ExactRatio | None
    fcf_margin: ExactRatio | None
    cash_conversion: ExactRatio | None
    capex_cfo: ExactRatio | None
    net_income_growth: ExactRatio | None
    fcf_growth: ExactRatio | None


class Bridge(Model):
    delta_cfo: IntegerText | None
    negative_delta_capex: IntegerText | None
    delta_fcf: IntegerText | None
    bridge_residual: IntegerText | None


class Cashflow(Model):
    symbol: str
    period: str
    start: date
    end: date
    days: int
    status: Literal["ok", "missing_input"]
    amounts: Amounts
    ratios: Ratios
    bridge: Bridge


class Fact(Model):
    symbol: str
    period: str
    start: date
    end: date
    as_of: date
    metric: Metric
    value_usd: IntegerText | None
    status: Literal["selected", "missing_input"]
    filed: date | None
    accession: str | None
    tag: str | None
    fact_id: str | None
    source_url: str | None


class Issuer(Model):
    symbol: str
    periods: tuple[str, ...]


class Parity(Model):
    rows: int
    cells: int


class Quality(Model):
    snapshot: Identity
    source_rows: int
    violations: dict[str, int]
    python_duckdb: Parity


class Page(Model, Generic[T]):
    snapshot: Identity
    total: int
    offset: int
    limit: int
    next_offset: int | None
    items: tuple[T, ...]


class Filters(Model):
    symbol: str | None = Field(default=None, pattern=r"^[A-Z][A-Z0-9.-]{0,14}$")
    period: str | None = None
    limit: int = Field(default=100, ge=1, le=500)
    offset: int = Field(default=0, ge=0)


class FactFilters(Filters):
    metric: Metric | None = None


class NoFilters(Model):
    pass


def capture(directory):
    """Validate the captured bytes, so requests cannot mix files changed after startup."""
    source = Path(directory)
    expected = {*MEMBERS, "manifest.json"}
    if source.is_symlink() or not source.is_dir():
        raise ContractError("API warehouse must be a real directory")
    if {path.name for path in source.iterdir()} != expected:
        raise ContractError("API warehouse file set differs")
    packet = {}
    for name in sorted(expected):
        path = source / name
        if path.is_symlink() or not path.is_file():
            raise ContractError(f"API warehouse member must be a real file: {name}")
        packet[name] = path.read_bytes()
    with tempfile.TemporaryDirectory(prefix="statementtrace-api-") as temp:
        for name, raw in packet.items():
            (Path(temp) / name).write_bytes(raw)
        verify_warehouse(temp)
    return packet


def _integer(value):
    return str(value) if value is not None else None


def _cashflow(row):
    ratios = {}
    for name in RATIOS:
        value = row[name]
        numerator, denominator = value.split("/") if value is not None else (None, None)
        ratios[name] = ExactRatio(numerator=numerator, denominator=denominator) if value is not None else None
    return Cashflow(
        **{key: row[key] for key in ("symbol", "period", "start", "end", "days", "status")},
        amounts=Amounts(**{key: _integer(row[key]) for key in AMOUNTS}),
        ratios=Ratios(**ratios),
        bridge=Bridge(**{key: _integer(row[key]) for key in BRIDGE}),
    )


def create_app(directory):
    """Create an independent application from one verified, immutable snapshot."""
    packet = capture(directory)
    analysis = read_json(packet["analysis.json"])
    manifest = read_json(packet["manifest.json"])
    identity = Identity(snapshot_id=digest(canonical(manifest["sha256"])), as_of=analysis["as_of"])
    rows = tuple(_cashflow(row) for row in analysis["rows"])
    facts = tuple(
        Fact(**{**row, "value_usd": _integer(row["value_usd"])})
        for raw in packet["source_facts.jsonl"].splitlines()
        for row in [read_json(raw)]
    )
    snapshot = Snapshot(**identity.model_dump(), source_rows=len(facts), issuer_years=len(rows))
    quality = Quality(snapshot=identity, **read_json(packet["quality.json"]))
    issuers = tuple(
        Issuer(symbol=symbol, periods=tuple(row.period for row in rows if row.symbol == symbol))
        for symbol in sorted({row.symbol for row in rows})
    )
    app = FastAPI(
        title="StatementTrace Financial API",
        version="1.0.0",
        description=(
            "Read-only access to one verified filing-date snapshot. Amounts and ratio components are exact integer "
            "strings. Missing facts remain null. Query filters do not change the snapshot cutoff; build another packet "
            "and restart to serve a different cutoff."
        ),
    )

    @app.middleware("http")
    async def snapshot_header(request: Request, call_next):
        duplicate = next((key for key in request.query_params if len(request.query_params.getlist(key)) > 1), None)
        if duplicate is not None:
            response = JSONResponse(
                status_code=422,
                content={
                    "detail": [
                        {
                            "type": "value_error",
                            "loc": ["query", duplicate],
                            "msg": "Duplicate query parameter",
                            "input": request.query_params.getlist(duplicate),
                        }
                    ]
                },
            )
        else:
            response = await call_next(request)
        response.headers["X-StatementTrace-Snapshot"] = identity.snapshot_id
        return response

    def page(items, filters, model):
        selected = tuple(
            row
            for row in items
            if (filters.symbol is None or row.symbol == filters.symbol)
            and (filters.period is None or row.period == filters.period)
            and (not isinstance(filters, FactFilters) or filters.metric is None or row.metric == filters.metric)
        )
        end = filters.offset + filters.limit
        return Page[model](
            snapshot=identity,
            total=len(selected),
            offset=filters.offset,
            limit=filters.limit,
            next_offset=end if end < len(selected) else None,
            items=selected[filters.offset : end],
        )

    @app.get("/healthz", response_model=Identity, tags=["Snapshot"])
    async def health(filters: Annotated[NoFilters, Query()]):
        return identity

    @app.get("/v1/snapshot", response_model=Snapshot, tags=["Snapshot"])
    async def snapshot_info(filters: Annotated[NoFilters, Query()]):
        return snapshot

    @app.get("/v1/quality", response_model=Quality, tags=["Snapshot"])
    async def quality_info(filters: Annotated[NoFilters, Query()]):
        return quality

    @app.get("/v1/issuers", response_model=tuple[Issuer, ...], tags=["Research"])
    async def issuer_list(filters: Annotated[NoFilters, Query()]):
        return issuers

    @app.get("/v1/cashflow", response_model=Page[Cashflow], tags=["Research"])
    async def cashflow(filters: Annotated[Filters, Query()]):
        return page(rows, filters, Cashflow)

    @app.get("/v1/facts", response_model=Page[Fact], tags=["Sources"])
    async def source_facts(filters: Annotated[FactFilters, Query()]):
        return page(facts, filters, Fact)

    return app
