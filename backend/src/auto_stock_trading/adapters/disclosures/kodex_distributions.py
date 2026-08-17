from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from typing import Annotated, ClassVar, Final, final, override
from zoneinfo import ZoneInfo

import httpx2
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from auto_stock_trading.domain.market_data.corporate_actions import (
    CorporateAction,
    CorporateActionBundle,
    CorporateActionLifecycle,
    CorporateActionObservation,
    CorporateActionQuality,
    CorporateActionRawResponse,
    CorporateActionType,
    TimePrecision,
)

KODEX_DISTRIBUTION_ENDPOINT: Final = "/api/v1/kodex/divid-info.do"
_PRODUCT_URL: Final = "https://www.samsungfund.com/etf/product/view.do?id={fund_id}"
_SOURCE: Final = "KODEX"
_CURRENCY: Final = "KRW"
_SEOUL: Final = ZoneInfo("Asia/Seoul")
_USER_AGENT: Final = "auto-stock-trading/0.1 (corporate-action integration)"
_HTTP_ERROR_STATUS: Final = 400


@final
@dataclass(frozen=True, slots=True)
class KodexTransportError(Exception):
    endpoint: str
    status_code: int | None

    @override
    def __str__(self) -> str:
        suffix = "network failure" if self.status_code is None else f"HTTP {self.status_code}"
        return f"KODEX request failed at {self.endpoint}: {suffix}"


@final
@dataclass(frozen=True, slots=True)
class KodexContractError(Exception):
    message: str = "KODEX distribution response did not match the expected contract"

    @override
    def __str__(self) -> str:
        return self.message


class KodexDistributionEntry(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True)

    record_date: Annotated[str, Field(alias="basicD")]
    per_share_amount: Annotated[str, Field(alias="dividA")]
    payment_date: Annotated[str | None, Field(alias="payD")]
    taxable_amount: Annotated[str | None, Field(alias="taxDividA")]
    distribution_yield: Annotated[str | None, Field(alias="dividY")]


class KodexDistributionResponse(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore", frozen=True)

    entries: Annotated[tuple[KodexDistributionEntry, ...], Field(alias="dividList")]


@final
@dataclass(frozen=True, slots=True)
class KodexDistributionTarget:
    symbol: str
    fund_id: str


@final
class KodexDistributionAdapter:
    def __init__(self, client: httpx2.AsyncClient, target: KodexDistributionTarget) -> None:
        self._client = client
        self._target = target

    @property
    def source_name(self) -> str:
        return _SOURCE

    @property
    def symbol(self) -> str:
        return self._target.symbol

    async def fetch_corporate_actions(
        self,
        start_date: date,
        end_date: date,
    ) -> CorporateActionBundle:
        payload = await self._fetch_distribution_history()
        received_at = datetime.now(UTC)
        raw = CorporateActionRawResponse(
            endpoint=KODEX_DISTRIBUTION_ENDPOINT,
            request_fingerprint=f"kodex:distributions:{self._target.fund_id}",
            received_at=received_at,
            payload_json=payload,
        )
        entries = _validated_entries(payload)
        selected = tuple(
            entry
            for entry in sorted(entries, key=lambda entry: entry.record_date)
            if start_date <= _entry_date(entry.record_date, "basicD") <= end_date
        )
        observations = tuple(
            CorporateActionObservation(
                action=_distribution_action(self._target, entry, received_at),
                raw_response=raw,
            )
            for entry in selected
        )
        return CorporateActionBundle(
            source=_SOURCE,
            symbol=self._target.symbol,
            observations=observations,
            supporting_raw_responses=(),
            collected_at=received_at,
        )

    async def close(self) -> None:
        await self._client.aclose()

    async def _fetch_distribution_history(self) -> str:
        try:
            response = await self._client.get(
                KODEX_DISTRIBUTION_ENDPOINT,
                params={"id": self._target.fund_id},
            )
        except httpx2.HTTPError as error:
            raise KodexTransportError(KODEX_DISTRIBUTION_ENDPOINT, None) from error
        if response.status_code >= _HTTP_ERROR_STATUS:
            raise KodexTransportError(KODEX_DISTRIBUTION_ENDPOINT, response.status_code)
        return response.text


def create_kodex_http_client(base_url: str) -> httpx2.AsyncClient:
    return httpx2.AsyncClient(
        base_url=base_url,
        timeout=httpx2.Timeout(connect=5.0, read=30.0, write=10.0, pool=10.0),
        follow_redirects=True,
        headers={"Accept": "application/json", "User-Agent": _USER_AGENT},
    )


def _validated_entries(payload: str) -> tuple[KodexDistributionEntry, ...]:
    try:
        response = KodexDistributionResponse.model_validate_json(payload)
    except ValidationError as error:
        message = "KODEX distribution response did not match the expected contract"
        raise KodexContractError(message) from error
    record_dates = [entry.record_date for entry in response.entries]
    if len(record_dates) != len(set(record_dates)):
        message = "KODEX distribution response repeats a record date"
        raise KodexContractError(message)
    return response.entries


def _distribution_action(
    target: KodexDistributionTarget,
    entry: KodexDistributionEntry,
    received_at: datetime,
) -> CorporateAction:
    return CorporateAction(
        action_type=CorporateActionType.ETF_DISTRIBUTION,
        lifecycle=CorporateActionLifecycle.CONFIRMED,
        quality=CorporateActionQuality.PENDING,
        announced_at=None,
        announcement_date=received_at.astimezone(_SEOUL).date(),
        time_precision=TimePrecision.DATE,
        ex_date=None,
        effective_date=None,
        record_date=_entry_date(entry.record_date, "basicD"),
        payment_date=_entry_date(entry.payment_date, "payD") if entry.payment_date else None,
        share_multiplier=None,
        cash_amount=_per_share_amount(entry.per_share_amount),
        currency=_CURRENCY,
        subscription_price=None,
        related_instrument_id=None,
        source=_SOURCE,
        source_event_id=f"{target.fund_id}:{entry.record_date}",
        source_reference=_PRODUCT_URL.format(fund_id=target.fund_id),
        available_at=received_at,
        received_at=received_at,
    )


def _entry_date(text: str, field_name: str) -> date:
    try:
        return datetime.strptime(text, "%Y%m%d").replace(tzinfo=UTC).date()
    except ValueError as error:
        message = f"invalid KODEX distribution date for {field_name}: {text}"
        raise KodexContractError(message) from error


def _per_share_amount(text: str) -> Decimal:
    try:
        amount = Decimal(text.replace(",", ""))
    except InvalidOperation as error:
        message = f"invalid KODEX distribution amount: {text}"
        raise KodexContractError(message) from error
    return amount
