from datetime import date, datetime
from typing import TYPE_CHECKING
from uuid import UUID

from fastapi import APIRouter, HTTPException, status

from auto_stock_trading.api.market_data_adjusted_models import (
    AdjustedDailyBarResponse,
    AdjustedDailyBarsResponse,
    AdjustedDatasetResponse,
    AdjustedDatasetsForActionResponse,
    AppliedCorporateActionResponse,
    CorporateActionsResponse,
    CorporateActionVersionResponse,
)
from auto_stock_trading.domain.market_data.adjustments import AdjustmentMethod
from auto_stock_trading.domain.market_data.corporate_actions import (
    CorporateActionRange,
    VersionedCorporateAction,
)

if TYPE_CHECKING:
    from auto_stock_trading.application.adjusted_prices import (
        AdjustedPriceReader,
        CorporateActionReader,
    )
    from auto_stock_trading.application.market_data import MarketDataReader
    from auto_stock_trading.domain.market_data.adjustment_datasets import (
        AdjustedBarRecord,
        AdjustmentDatasetRecord,
        DatasetActionRecord,
    )

_METHOD_DESCRIPTION = (
    "`split_adjusted`는 주식 수 변화 사건만 반영하며 사건일 이전 가격에 1/주식수승수, "
    "거래량에 주식수승수를 누적 적용한다. `total_return`은 여기에 현금배당·ETF 분배금을 "
    "락일 직전 종가 기준 (P - D) / P 가격계수로 추가 반영한다. "
    "두 계열 모두 비수정 확정 일봉에서 파생되며 체결가로 사용할 수 없다."
)


def create_market_data_adjusted_router(
    instruments: MarketDataReader,
    corporate_actions: CorporateActionReader,
    adjusted_prices: AdjustedPriceReader,
) -> APIRouter:
    router = APIRouter(prefix="/api/market-data", tags=["market-data"])

    async def corporate_action_list(
        symbol: str,
        start_date: date | None = None,
        end_date: date | None = None,
        knowledge_cutoff_at: datetime | None = None,
        include_history: bool = False,  # noqa: FBT001, FBT002
    ) -> CorporateActionsResponse:
        _validate_corporate_action_query(
            start_date,
            end_date,
            knowledge_cutoff_at,
            include_history=include_history,
        )
        if await instruments.instrument(symbol) is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Instrument not found")
        results = await _read_corporate_actions(
            corporate_actions,
            CorporateActionRange(symbol, start_date, end_date),
            knowledge_cutoff_at,
            include_history=include_history,
        )
        return CorporateActionsResponse(
            symbol=symbol,
            start_date=start_date,
            end_date=end_date,
            knowledge_cutoff_at=knowledge_cutoff_at,
            include_history=include_history,
            actions=tuple(_action_version_response(result) for result in results),
        )

    async def adjusted_daily_bars(
        symbol: str,
        method: AdjustmentMethod,
    ) -> AdjustedDailyBarsResponse:
        dataset = await adjusted_prices.read_latest_published(symbol, method)
        if dataset is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Published adjusted dataset not found")
        return await _dataset_bundle(dataset)

    async def adjusted_dataset(dataset_id: UUID) -> AdjustedDailyBarsResponse:
        dataset = await adjusted_prices.read_dataset(dataset_id)
        if dataset is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Adjusted dataset not found")
        return await _dataset_bundle(dataset)

    async def datasets_for_action(action_key: UUID) -> AdjustedDatasetsForActionResponse:
        datasets = await adjusted_prices.read_datasets_for_action(action_key)
        return AdjustedDatasetsForActionResponse(
            action_key=action_key,
            datasets=tuple(_dataset_response(record) for record in datasets),
        )

    async def _dataset_bundle(dataset: AdjustmentDatasetRecord) -> AdjustedDailyBarsResponse:
        bars = await adjusted_prices.read_adjusted_bars(dataset.dataset_id)
        actions = await adjusted_prices.read_dataset_actions(dataset.dataset_id)
        return AdjustedDailyBarsResponse(
            dataset=_dataset_response(dataset),
            bars=tuple(_bar_response(bar) for bar in bars),
            applied_actions=tuple(_applied_action_response(action) for action in actions),
        )

    router.add_api_route(
        "/instruments/{symbol}/corporate-actions",
        corporate_action_list,
        methods=["GET"],
        description=(
            "종목의 기업행사 사실 버전을 조회한다. 기본은 현재 버전이며 "
            "`knowledge_cutoff_at`은 당시 알 수 있었던 버전, `include_history`는 "
            "정정·취소 이력 전체를 반환한다."
        ),
    )
    router.add_api_route(
        "/instruments/{symbol}/adjusted-daily-bars",
        adjusted_daily_bars,
        methods=["GET"],
        description=("최신 발행 수정주가 데이터셋과 파생 일봉을 반환한다. " + _METHOD_DESCRIPTION),
    )
    router.add_api_route(
        "/adjusted-datasets/{dataset_id}",
        adjusted_dataset,
        methods=["GET"],
        description="데이터셋 ID로 수정 일봉, 개별 계수와 반영 기업행사 계보를 조회한다. "
        + _METHOD_DESCRIPTION,
    )
    router.add_api_route(
        "/corporate-actions/{action_key}/adjusted-datasets",
        datasets_for_action,
        methods=["GET"],
        description="특정 기업행사 사실이 반영된 수정주가 데이터셋 목록을 조회한다.",
    )
    return router


def _validate_corporate_action_query(
    start_date: date | None,
    end_date: date | None,
    knowledge_cutoff_at: datetime | None,
    *,
    include_history: bool,
) -> None:
    if start_date is not None and end_date is not None and start_date > end_date:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "start_date must not be after end_date",
        )
    if knowledge_cutoff_at is not None and knowledge_cutoff_at.tzinfo is None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "knowledge_cutoff_at must include a timezone offset",
        )
    if include_history and knowledge_cutoff_at is not None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "include_history cannot be combined with knowledge_cutoff_at",
        )


async def _read_corporate_actions(
    reader: CorporateActionReader,
    query: CorporateActionRange,
    knowledge_cutoff_at: datetime | None,
    *,
    include_history: bool,
) -> tuple[VersionedCorporateAction, ...]:
    if knowledge_cutoff_at is not None:
        return await reader.read_as_of(query, knowledge_cutoff_at)
    if include_history:
        return await reader.read_history(query)
    return await reader.read_current(query)


def _action_version_response(result: VersionedCorporateAction) -> CorporateActionVersionResponse:
    action = result.action
    return CorporateActionVersionResponse(
        corporate_action_id=result.corporate_action_id,
        action_key=result.action_key,
        version=result.version,
        valid_from=result.valid_from,
        superseded_at=result.superseded_at,
        action_type=action.action_type.value,
        lifecycle=action.lifecycle.value,
        quality=action.quality.value,
        announced_at=action.announced_at,
        announcement_date=action.announcement_date,
        time_precision=action.time_precision.value,
        ex_date=action.ex_date,
        effective_date=action.effective_date,
        record_date=action.record_date,
        payment_date=action.payment_date,
        share_multiplier=action.share_multiplier,
        cash_amount=action.cash_amount,
        currency=action.currency,
        subscription_price=action.subscription_price,
        related_instrument_id=action.related_instrument_id,
        source=action.source,
        source_event_id=action.source_event_id,
        source_reference=action.source_reference,
        available_at=action.available_at,
        received_at=action.received_at,
    )


def _dataset_response(record: AdjustmentDatasetRecord) -> AdjustedDatasetResponse:
    return AdjustedDatasetResponse(
        dataset_id=record.dataset_id,
        symbol=record.symbol,
        method=record.method.value,
        interval=record.interval,
        range_start=record.range_start,
        price_cutoff_date=record.price_cutoff_date,
        knowledge_cutoff_at=record.knowledge_cutoff_at,
        algorithm_version=record.algorithm_version,
        input_bar_version_hash=record.input_bar_version_hash,
        action_version_hash=record.action_version_hash,
        status=record.status,
        generated_at=record.generated_at,
        superseded_at=record.superseded_at,
        failure_code=record.failure_code,
    )


def _bar_response(record: AdjustedBarRecord) -> AdjustedDailyBarResponse:
    return AdjustedDailyBarResponse(
        trading_date=record.trading_date,
        open_price=record.open_price,
        high_price=record.high_price,
        low_price=record.low_price,
        close_price=record.close_price,
        volume=record.volume,
        trading_value=record.trading_value,
        price_factor=record.price_factor,
        volume_factor=record.volume_factor,
        source=record.source,
        source_bar_id=record.source_bar_id,
        source_bar_version=record.source_bar_version,
    )


def _applied_action_response(record: DatasetActionRecord) -> AppliedCorporateActionResponse:
    return AppliedCorporateActionResponse(
        corporate_action_id=record.corporate_action_id,
        action_key=record.action_key,
        action_version=record.action_version,
        event_date=record.event_date,
        event_price_factor=record.event_price_factor,
        event_volume_factor=record.event_volume_factor,
        source=record.source,
    )
