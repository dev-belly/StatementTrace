"""Strict JSON and deterministic, exact-number formatting."""

import hashlib
import json
import re
from datetime import date
from decimal import ROUND_HALF_EVEN, Context, Decimal, localcontext
from fractions import Fraction


class ContractError(ValueError):
    """An input is malformed, ambiguous, or outside the supported contract."""


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ContractError(f"Duplicate JSON key: {key}")
        result[key] = value
    return result


def _nonfinite(value):
    raise ContractError(f"Non-finite JSON number: {value}")


def read_json(raw):
    try:
        return json.loads(raw, object_pairs_hook=_pairs, parse_constant=_nonfinite)
    except (ValueError, TypeError, UnicodeError) as exc:
        raise ContractError(f"Invalid JSON: {exc}") from exc


def canonical(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n").encode("utf-8")


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def iso_date(value, field):
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise ContractError(f"{field} must be YYYY-MM-DD")
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ContractError(f"Invalid {field}: {value}") from exc


def integer(value, field, minimum=None):
    if type(value) is not int or (minimum is not None and value < minimum):
        raise ContractError(f"{field} must be an integer" + (f" >= {minimum}" if minimum is not None else ""))
    return value


def exact(value):
    if value is None:
        return ""
    value = Fraction(value)
    return f"{value.numerator}/{value.denominator}"


def display(value, places=6):
    if value is None:
        return ""
    value = Fraction(value)
    precision = max(50, len(str(abs(value.numerator))) + places + 10)
    with localcontext(Context(prec=precision, rounding=ROUND_HALF_EVEN)):
        return format(Decimal(value.numerator) / Decimal(value.denominator), f".{places}f")
