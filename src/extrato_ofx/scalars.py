"""Montantes e datas OFX sem floats, contexto Decimal ou fuso local."""
import re
from datetime import datetime, timedelta, timezone
from .model import OfxError

_AMOUNT = re.compile(r"[+-]?(?:[0-9]+(?:[.,][0-9]*)?|[.,][0-9]+)\Z")
_DATE = re.compile(r"([0-9]{8}(?:[0-9]{2}){0,3})(?:\.([0-9]{3}))?(?:\[([+-]?[0-9]{1,2}(?:\.[0-9]{1,2})?)(?::([A-Za-z0-9_+/-]{1,32}))?\])?\Z")


def _canonical(coefficient: int, scale: int) -> str:
    if coefficient == 0:
        return "0"
    sign = "-" if coefficient < 0 else ""
    digits = str(abs(coefficient))
    if scale:
        digits = digits.zfill(scale + 1)
        digits = (digits[:-scale] + "." + digits[-scale:]).rstrip("0").rstrip(".")
    return sign + digits


def _parts(token: str) -> tuple[int, int]:
    normalized = token.replace(",", ".")
    integer, _, fraction = normalized.partition(".")
    negative = integer.startswith("-")
    integer = integer.lstrip("+-") or "0"
    return int(integer + fraction) * (-1 if negative else 1), len(fraction)


def parse_amount(text: str) -> dict:
    if not isinstance(text, str):
        raise OfxError("invalid_amount")
    token = text.strip()
    if not 1 <= len(token) <= 32 or not _AMOUNT.fullmatch(token):
        raise OfxError("invalid_amount")
    coefficient, scale = _parts(token)
    return {"raw": token, "value": _canonical(coefficient, scale)}


def sum_amounts(amounts) -> str:
    coefficient, scale = 0, 0
    for amount in amounts:
        # Public utility accepts parsed Money objects and validates each value.
        if not isinstance(amount, dict) or not isinstance(amount.get("value"), str):
            raise OfxError("invalid_amount")
        token = amount["value"]
        # Adding the leading zero to an accepted .fraction can add one byte.
        if not 1 <= len(token) <= 33 or not _AMOUNT.fullmatch(token):
            raise OfxError("invalid_amount")
        current, current_scale = _parts(token)
        target = max(scale, current_scale)
        coefficient = coefficient * 10 ** (target - scale) + current * 10 ** (target - current_scale)
        scale = target
    return _canonical(coefficient, scale)


def parse_date(text: str) -> dict:
    if not isinstance(text, str):
        raise OfxError("invalid_date")
    token = text.strip()
    match = _DATE.fullmatch(token)
    if not match:
        raise OfxError("invalid_date")
    digits, fraction, offset, label = match.groups()
    if fraction and len(digits) != 14:
        raise OfxError("invalid_date")
    if len(digits) == 14 and digits[12:14] == "60":
        raise OfxError("unsupported_leap_second")
    offset = offset or "0"
    offset_coefficient, offset_scale = _parts(offset)
    offset_seconds = offset_coefficient * 3600 // 10 ** offset_scale
    if abs(offset_coefficient) > 12 * 10 ** offset_scale:
        raise OfxError("invalid_date_offset")
    padded = digits.ljust(14, "0")
    try:
        local = datetime(int(padded[:4]), int(padded[4:6]), int(padded[6:8]),
                         int(padded[8:10]), int(padded[10:12]), int(padded[12:14]),
                         int(fraction or "0") * 1000,
                         tzinfo=timezone(timedelta(seconds=offset_seconds)))
        utc = local.astimezone(timezone.utc)
    except (ValueError, OverflowError):
        raise OfxError("invalid_date") from None
    precision = {8: "date", 10: "hour", 12: "minute", 14: "second"}[len(digits)]
    if fraction:
        precision = "millisecond"
    timespec = "milliseconds" if fraction else "seconds"
    return {"raw": token, "precision": precision, "iso": local.isoformat(timespec=timespec),
            "utc": utc.isoformat(timespec=timespec).replace("+00:00", "Z"),
            "offsetHours": _canonical(offset_coefficient, offset_scale), "zoneLabel": label}
