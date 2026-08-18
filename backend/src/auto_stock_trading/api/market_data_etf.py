from typing import TYPE_CHECKING

from fastapi import APIRouter, HTTPException, status

from auto_stock_trading.api.market_data_etf_models import (
    DistributionYieldResponse,
    EtfDetailResponse,
    EtfListingResponse,
    EtfSnapshotResponse,
    EtfsResponse,
)
from auto_stock_trading.application.etf import DistributionYield, distribution_yield
from auto_stock_trading.domain.market_data.corporate_actions import CorporateActionRange
from auto_stock_trading.domain.market_data.etf import EtfListing, EtfNavSnapshot

if TYPE_CHECKING:
    from auto_stock_trading.application.adjusted_prices import CorporateActionReader
    from auto_stock_trading.application.etf import EtfReader


def create_market_data_etf_router(
    etfs: EtfReader,
    corporate_actions: CorporateActionReader,
) -> APIRouter:
    router = APIRouter(prefix="/api/market-data/etfs", tags=["market-data-etf"])

    async def etf_list() -> EtfsResponse:
        listings = await etfs.read_etf_list()
        return EtfsResponse(etfs=tuple(_listing_response(item) for item in listings))

    async def etf_detail(symbol: str) -> EtfDetailResponse:
        listing = await etfs.read_etf(symbol)
        if listing is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "ETF not found")
        actions = await corporate_actions.read_current(CorporateActionRange(symbol, None, None))
        result = distribution_yield(actions, listing.snapshot)
        return EtfDetailResponse(
            symbol=listing.profile.symbol,
            isin=listing.profile.isin,
            name=listing.profile.name,
            snapshot=_snapshot_response(listing.snapshot),
            distribution_yield=_yield_response(result),
        )

    router.add_api_route(
        "",
        etf_list,
        methods=["GET"],
        description=(
            "KIS 마스터 파일의 국내 ETF 현재 버전 전체를 최신 NAV 스냅샷과 함께 반환한다. "
            "괴리율·추적오차·운용사·추적배수는 KIS 원본 필드이며 순자산총액 단위는 억원"
            "(net_asset_unit)이다. 스냅샷이 없는 종목은 snapshot이 null이다."
        ),
    )
    router.add_api_route(
        "/{symbol}",
        etf_detail,
        methods=["GET"],
        description=(
            "단일 ETF의 마스터·최신 스냅샷·분배율을 반환한다. 분배율은 저장된 분배금 사실이 "
            "있는 ETF만 계산하며 수식·기간·건수를 함께 노출한다(없으면 사유 코드)."
        ),
    )
    return router


def _listing_response(listing: EtfListing) -> EtfListingResponse:
    return EtfListingResponse(
        symbol=listing.profile.symbol,
        isin=listing.profile.isin,
        name=listing.profile.name,
        snapshot=_snapshot_response(listing.snapshot),
    )


def _snapshot_response(snapshot: EtfNavSnapshot | None) -> EtfSnapshotResponse | None:
    if snapshot is None:
        return None
    return EtfSnapshotResponse(
        price=snapshot.price,
        change_percent=snapshot.change_percent,
        volume=snapshot.volume,
        previous_volume=snapshot.previous_volume,
        nav=snapshot.nav,
        divergence_rate=snapshot.divergence_rate,
        tracking_error=snapshot.tracking_error,
        tracking_multiple=snapshot.tracking_multiple,
        net_asset_total=snapshot.net_asset_total,
        listed_shares=snapshot.listed_shares,
        manager=snapshot.manager,
        index_name=snapshot.index_name,
        listing_date=snapshot.listing_date,
        currency=snapshot.currency,
        as_of=snapshot.as_of,
        received_at=snapshot.received_at,
    )


def _yield_response(result: DistributionYield) -> DistributionYieldResponse:
    return DistributionYieldResponse(
        value=result.value,
        unavailable_reason=(
            None if result.unavailable_reason is None else result.unavailable_reason.value
        ),
        formula=result.formula,
        distribution_total=result.distribution_total,
        distribution_count=result.distribution_count,
        window_start=result.window_start,
        window_end=result.window_end,
    )
