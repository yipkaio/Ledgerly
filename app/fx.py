"""Workspace reporting currency and cached ECB reference-rate snapshots."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
import json
import xml.etree.ElementTree as ET

import httpx
from pydantic import BaseModel, Field, field_validator


SUPPORTED_CURRENCIES = {"SGD", "MYR", "USD", "EUR", "GBP", "AUD"}
ECB_DAILY_URL = "https://www.ecb.europa.eu/stats/eurofxref/eurofxref-daily.xml"

FX_SCHEMA = (
    "CREATE TABLE workspace_settings (singleton INTEGER PRIMARY KEY CHECK(singleton=1), "
    "default_currency TEXT, updated_at TEXT NOT NULL)",
    "CREATE TABLE fx_rate_snapshots (as_of TEXT PRIMARY KEY, fetched_at TEXT NOT NULL, "
    "source TEXT NOT NULL, rates_json TEXT NOT NULL)",
)


class FXUnavailable(RuntimeError):
    """No current or cached reference-rate snapshot can be used."""


class WorkspaceCurrency(BaseModel):
    default_currency: str = Field(pattern=r"^[A-Z]{3}$")

    @field_validator("default_currency")
    @classmethod
    def supported(cls, value: str) -> str:
        if value not in SUPPORTED_CURRENCIES:
            raise ValueError("Unsupported reporting currency")
        return value


class ECBRateProvider:
    async def latest(self) -> dict:
        try:
            async with httpx.AsyncClient(timeout=5.0, follow_redirects=False) as client:
                response = await client.get(ECB_DAILY_URL, headers={"Accept": "application/xml"})
            response.raise_for_status()
            if len(response.content) > 1_000_000:
                raise FXUnavailable("Exchange-rate response is too large")
            return parse_ecb_xml(response.content)
        except (httpx.HTTPError, ET.ParseError, ArithmeticError, ValueError) as exc:
            raise FXUnavailable("Latest reference rates are unavailable") from exc


def parse_ecb_xml(content: bytes) -> dict:
    root = ET.fromstring(content)
    dated = next((node for node in root.iter() if node.attrib.get("time")), None)
    if dated is None:
        raise FXUnavailable("Exchange-rate response has no date")
    rates = {"EUR": Decimal("1")}
    for node in dated:
        currency, rate = node.attrib.get("currency"), node.attrib.get("rate")
        if currency in SUPPORTED_CURRENCIES and rate:
            value = Decimal(rate)
            if value <= 0 or not value.is_finite():
                raise FXUnavailable("Exchange-rate response is invalid")
            rates[currency] = value
    if not SUPPORTED_CURRENCIES.issubset(rates):
        raise FXUnavailable("Exchange-rate response is incomplete")
    return {"as_of": dated.attrib["time"], "source": "European Central Bank",
            "rates": {key: str(value) for key, value in rates.items()}}


def workspace_currency(store) -> str | None:
    with store.connect() as db:
        row = db.execute(
            "SELECT default_currency FROM workspace_settings WHERE singleton=1"
        ).fetchone()
    return row[0] if row else None


def set_workspace_currency(store, currency: str) -> dict:
    timestamp = datetime.now(timezone.utc).isoformat()
    with store.connect() as db:
        db.execute(
            "INSERT INTO workspace_settings VALUES (1,?,?) ON CONFLICT(singleton) "
            "DO UPDATE SET default_currency=excluded.default_currency,updated_at=excluded.updated_at",
            (currency, timestamp),
        )
    return {"default_currency": currency, "updated_at": timestamp}


async def latest_snapshot(store, provider: ECBRateProvider) -> dict:
    with store.connect() as db:
        cached = db.execute(
            "SELECT as_of,fetched_at,source,rates_json FROM fx_rate_snapshots "
            "ORDER BY fetched_at DESC LIMIT 1"
        ).fetchone()
    if cached:
        fetched = datetime.fromisoformat(cached["fetched_at"])
        if datetime.now(timezone.utc) - fetched <= timedelta(hours=12):
            return {"as_of": cached["as_of"], "fetched_at": cached["fetched_at"],
                    "source": cached["source"], "rates": json.loads(cached["rates_json"]),
                    "stale": False}
    try:
        result = await provider.latest()
    except FXUnavailable:
        if not cached or datetime.now(timezone.utc) - datetime.fromisoformat(
            cached["fetched_at"]
        ) > timedelta(days=7):
            raise
        return {"as_of": cached["as_of"], "fetched_at": cached["fetched_at"],
                "source": cached["source"], "rates": json.loads(cached["rates_json"]),
                "stale": True}
    fetched_at = datetime.now(timezone.utc).isoformat()
    with store.connect() as db:
        db.execute(
            "INSERT INTO fx_rate_snapshots VALUES (?,?,?,?) ON CONFLICT(as_of) DO UPDATE SET "
            "fetched_at=excluded.fetched_at,source=excluded.source,rates_json=excluded.rates_json",
            (result["as_of"], fetched_at, result["source"], json.dumps(result["rates"])),
        )
    return {**result, "fetched_at": fetched_at, "stale": False}


def convert_cents(cents: int, source: str, target: str, rates: dict[str, str]) -> int:
    if source not in rates or target not in rates:
        raise FXUnavailable(f"No reference rate is available for {source}")
    converted = Decimal(cents) / Decimal(rates[source]) * Decimal(rates[target])
    return int(converted.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
