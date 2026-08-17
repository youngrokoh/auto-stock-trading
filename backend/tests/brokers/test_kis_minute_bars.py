import json
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from urllib.parse import parse_qs
from zoneinfo import ZoneInfo

import anyio
import httpx2
from pydantic import SecretStr

from auto_stock_trading.adapters.brokers.kis_coordination import (
    InMemoryKisRequestCoordinator,
    KisCoordinationConfig,
)
from auto_stock_trading.adapters.brokers.kis_http import KisCredentials, KisHttpClient
from auto_stock_trading.adapters.brokers.kis_minute_bars import (
    MINUTE_BARS_ENDPOINT,
    KisMinuteBarAdapter,
)
from auto_stock_trading.domain.market_data.calendar import SessionWindow
from auto_stock_trading.domain.market_data.models import InstrumentTarget, ProductType

_FIXTURE_ROOT = Path(__file__).parents[1] / "fixtures" / "kis"
_SEOUL = ZoneInfo("Asia/Seoul")
_TARGET_DATE = date(2026, 8, 14)
_PREVIOUS_DATE = date(2026, 8, 13)
_MINUTE = timedelta(minutes=1)
_OPENS_AT = datetime(2026, 8, 14, 9, 0, tzinfo=_SEOUL)
_CLOSES_AT = datetime(2026, 8, 14, 15, 30, tzinfo=_SEOUL)
_WINDOW = SessionWindow(_OPENS_AT.astimezone(UTC), _CLOSES_AT.astimezone(UTC))
_TARGET = InstrumentTarget("069500", ProductType.ETF)


def _row(day: date, label: datetime) -> dict[str, str]:
    minute_index = label.hour * 60 + label.minute
    base = 100000 + minute_index
    return {
        "stck_bsop_date": day.strftime("%Y%m%d"),
        "stck_cntg_hour": label.strftime("%H%M%S"),
        "stck_oprc": str(base - 5),
        "stck_hgpr": str(base + 10),
        "stck_lwpr": str(base - 10),
        "stck_prpr": str(base),
        "cntg_vol": "100",
        "acml_tr_pbmn": str(1_000_000 + minute_index),
    }


class MinutePageHandler:
    def __init__(self) -> None:
        self.requested_hours: list[str] = []

    def __call__(self, request: httpx2.Request) -> httpx2.Response:
        if request.url.path == "/oauth2/tokenP":
            return httpx2.Response(
                200,
                request=request,
                headers={"Content-Type": "application/json"},
                text=(_FIXTURE_ROOT / "token.json").read_text(encoding="utf-8"),
            )
        assert request.url.path == MINUTE_BARS_ENDPOINT
        query = parse_qs(request.url.query.decode())
        hour = query["FID_INPUT_HOUR_1"][0]
        self.requested_hours.append(hour)
        cursor = datetime(
            _TARGET_DATE.year,
            _TARGET_DATE.month,
            _TARGET_DATE.day,
            int(hour[:2]),
            int(hour[2:4]),
            tzinfo=_SEOUL,
        )
        rows: list[dict[str, str]] = []
        for _ in range(30):
            if cursor.date() == _TARGET_DATE and cursor < _OPENS_AT:
                cursor = datetime(
                    _PREVIOUS_DATE.year,
                    _PREVIOUS_DATE.month,
                    _PREVIOUS_DATE.day,
                    15,
                    30,
                    tzinfo=_SEOUL,
                )
            rows.append(_row(cursor.date(), cursor))
            cursor -= _MINUTE
        body = {
            "rt_cd": "0",
            "msg_cd": "MCA00000",
            "msg1": "정상처리 되었습니다.",
            "output1": {"hts_kor_isnm": "KODEX 200"},
            "output2": rows,
        }
        return httpx2.Response(
            200,
            request=request,
            headers={"Content-Type": "application/json"},
            text=json.dumps(body, ensure_ascii=False),
        )


def _adapter() -> tuple[KisMinuteBarAdapter, MinutePageHandler]:
    handler = MinutePageHandler()
    client = httpx2.AsyncClient(
        base_url="https://kis.example.test",
        transport=httpx2.MockTransport(handler),
        timeout=httpx2.Timeout(5.0),
        follow_redirects=True,
    )
    http_client = KisHttpClient(
        client,
        KisCredentials(SecretStr("fixture-app-key"), SecretStr("fixture-app-secret")),
        InMemoryKisRequestCoordinator(KisCoordinationConfig(minimum_interval_seconds=0)),
    )
    return KisMinuteBarAdapter(http_client), handler


def test_full_session_collection_covers_every_session_minute_once() -> None:
    async def run() -> None:
        adapter, handler = _adapter()
        try:
            bundle = await adapter.fetch_minute_bars(
                _TARGET,
                _TARGET_DATE,
                _WINDOW,
                datetime(2026, 8, 17, 5, 0, tzinfo=UTC),
            )
        finally:
            await adapter.close()

        bars = bundle.bars
        assert bundle.trading_date == _TARGET_DATE
        assert len(bars) == 391
        assert len({bar.bar_started_at for bar in bars}) == 391
        assert bars[0].bar_started_at == _OPENS_AT.astimezone(UTC)
        assert bars[-1].bar_started_at == _CLOSES_AT.astimezone(UTC)
        assert all(bar.trading_date == _TARGET_DATE for bar in bars)
        first = bars[0]
        assert first.open_price == Decimal(100000 + 540 - 5)
        assert first.high_price == Decimal(100000 + 540 + 10)
        assert first.low_price == Decimal(100000 + 540 - 10)
        assert first.close_price == Decimal(100000 + 540)
        assert first.volume == 100
        assert first.cumulative_trading_value == Decimal(1_000_000 + 540)
        assert first.source == "KIS"
        assert handler.requested_hours[0] == "153000"
        assert handler.requested_hours[-1] == "090000"
        assert len(bundle.pages) == len(handler.requested_hours)
        assert all(page.raw_response.payload_json for page in bundle.pages)

    anyio.run(run)


def test_intraday_collection_excludes_the_incomplete_minute() -> None:
    async def run() -> None:
        adapter, handler = _adapter()
        try:
            bundle = await adapter.fetch_minute_bars(
                _TARGET,
                _TARGET_DATE,
                _WINDOW,
                datetime(2026, 8, 14, 10, 0, 30, tzinfo=_SEOUL).astimezone(UTC),
            )
        finally:
            await adapter.close()

        bars = bundle.bars
        assert handler.requested_hours[0] == "100000"
        assert len(bars) == 60
        assert bars[0].bar_started_at == _OPENS_AT.astimezone(UTC)
        assert bars[-1].bar_started_at == datetime(2026, 8, 14, 9, 59, tzinfo=_SEOUL).astimezone(
            UTC
        )

    anyio.run(run)
