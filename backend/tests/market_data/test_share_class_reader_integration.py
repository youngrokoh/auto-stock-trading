"""종목 목록이 상장 주식종류를 저장 사실에서 말하는지 검증한다.

운영 개요 미리보기는 전략·주문 대상(보통주)만 보여야 한다. 그 판정을 화면이 단축코드 6번째
자리로 추론하면 데이터 규칙이 UI에 복제된다 — 백엔드가 사실을 말한다.
"""

from datetime import UTC, datetime
from typing import Final

import anyio
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import create_async_engine

from auto_stock_trading.adapters.database.market_data_repository import (
    PostgresMarketDataRepository,
)
from auto_stock_trading.adapters.database.market_data_rows import (
    InstrumentRow,
    RawApiResponseRow,
)
from auto_stock_trading.adapters.database.market_data_share_class_store import (
    PostgresShareClassStore,
)
from auto_stock_trading.adapters.database.reference_stock_rows import ShareClassRow
from auto_stock_trading.domain.market_data.models import BrokerOperation, RawBrokerResponse
from auto_stock_trading.domain.market_data.share_classes import ShareClassKind, pair_share_classes
from auto_stock_trading.domain.market_data.stocks import StockListing
from auto_stock_trading.settings.runtime import Settings

_NOW: Final = datetime(2026, 8, 24, 1, 0, tzinfo=UTC)
_COMMON: Final = "900310"
_PREFERRED: Final = "90031K"


def _listing(symbol: str, name: str) -> StockListing:
    return StockListing(
        symbol=symbol,
        isin=f"KR7{symbol}003",
        name=name,
        source="KIS_MASTER",
        received_at=_NOW,
    )


def _raw() -> RawBrokerResponse:
    return RawBrokerResponse(
        operation=BrokerOperation.STOCK_MASTER,
        endpoint="/common/master/kospi_code.mst.zip",
        request_fingerprint=f"share-class-reader:{_NOW.isoformat()}",
        received_at=_NOW,
        payload_json='{"fixture": true}',
    )


def test_the_instrument_list_reports_the_stored_share_class() -> None:
    async def run() -> None:
        url = Settings().database_url.get_secret_value()
        store = PostgresShareClassStore.from_url(url)
        reader = PostgresMarketDataRepository.from_url(url)
        try:
            pairing = pair_share_classes(
                (_listing(_COMMON, "픽스처보통주"), _listing(_PREFERRED, "픽스처우선주"))
            )
            assert pairing.refused == ()
            _ = await store.save_groups(pairing.groups, _raw(), _NOW)
            for item in pairing.groups[0].classes:
                await store.ensure_instrument(item, _NOW)

            found = {
                instrument.symbol: instrument.share_class
                for instrument in await reader.instruments()
                if instrument.symbol in (_COMMON, _PREFERRED)
            }
        finally:
            await reader.close()
            await store.close()
            await _cleanup(url)

        assert found == {
            _COMMON: ShareClassKind.COMMON,
            _PREFERRED: ShareClassKind.PREFERRED,
        }

    anyio.run(run)


async def _cleanup(url: str) -> None:
    """만든 것을 모두 지운다 — **종목 행까지** 포함한다.

    `ensure_instrument`가 만든 `reference.instrument` 행을 남기면 종목 목록에 클래스를 모르는
    픽스처 종목이 계속 나타난다(구현 중 실측: 249종목 중 2건이 픽스처였다).
    """
    engine = create_async_engine(url)
    try:
        async with engine.begin() as connection:
            _ = await connection.execute(
                delete(ShareClassRow).where(ShareClassRow.common_symbol == _COMMON)
            )
            _ = await connection.execute(
                delete(InstrumentRow).where(InstrumentRow.symbol.in_((_COMMON, _PREFERRED)))
            )
            _ = await connection.execute(
                delete(RawApiResponseRow).where(
                    RawApiResponseRow.request_fingerprint
                    == f"share-class-reader:{_NOW.isoformat()}"
                )
            )
    finally:
        await engine.dispose()
