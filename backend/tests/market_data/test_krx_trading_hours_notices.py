import json
from datetime import UTC, date, datetime, time
from pathlib import Path
from urllib.parse import parse_qs
from zoneinfo import ZoneInfo

import anyio
import httpx2
import pytest

from auto_stock_trading.adapters.exchanges.krx_composite_calendar import (
    KrxCompositeCalendarSource,
)
from auto_stock_trading.adapters.exchanges.krx_market_calendar import KRX_OTP_ENDPOINT
from auto_stock_trading.adapters.exchanges.krx_trading_hours_contracts import (
    KrxNoticeContractError,
    KrxTradingHoursEvidence,
    krx_notice_target_date_hint,
    parse_krx_trading_hours_notice,
)
from auto_stock_trading.adapters.exchanges.krx_trading_hours_notices import (
    KRX_NOTICE_DATA_ENDPOINT,
    KrxTradingHoursHttpClient,
    KrxTradingHoursNoticeAdapter,
)
from auto_stock_trading.domain.market_data.calendar import (
    CalendarObservation,
    CalendarRawResponse,
    CalendarSessionKey,
    CalendarSessionRange,
    CalendarSource,
    OpenMarketSession,
    PendingVerification,
    SessionWindow,
    ShortenedMarketSession,
    calendar_session_key,
)

_FIXTURES = Path(__file__).parents[1] / "fixtures" / "krx"
_SEOUL = ZoneInfo("Asia/Seoul")
_CSAT_TITLE = "대학수학능력시험일(11.13) 증권시장 등 거래시간 임시 변경"


def test_notice_parser_extracts_csat_regular_session_change() -> None:
    # Given
    text = (_FIXTURES / "2025_csat_trading_hours.txt").read_text(encoding="utf-8")

    # When
    change = parse_krx_trading_hours_notice(_CSAT_TITLE, text)

    # Then
    assert change.trading_date == date(2025, 11, 13)
    assert change.opens_at == time(10)
    assert change.closes_at == time(16, 30)


def test_notice_parser_extracts_year_opening_regular_session_change() -> None:
    # Given
    title = "2025년 연말 시장운영 일정 및 2026년 연초 개장일(1.2) 매매거래시간 안내"
    text = (_FIXTURES / "2026_opening_trading_hours.txt").read_text(encoding="utf-8")

    # When
    change = parse_krx_trading_hours_notice(title, text)

    # Then
    assert change.trading_date == date(2026, 1, 2)
    assert change.opens_at == time(10)
    assert change.closes_at == time(15, 30)


def test_notice_target_hint_uses_the_publication_year_for_csat() -> None:
    # Given
    title = "대학수학능력시험일(11.14) 증권시장 등 거래시간 임시 변경"

    # When
    target = krx_notice_target_date_hint(title, date(2024, 10, 31))

    # Then
    assert target == date(2024, 11, 14)


def test_year_opening_parser_accepts_the_legacy_official_securities_layout() -> None:
    # Given
    title = "2024년 연말 시장운영 일정 및 2025년 연초 개장일(1.2) 매매거래시간 안내"
    text = (_FIXTURES / "2025_opening_legacy_extracted.txt").read_text(encoding="utf-8")

    # When
    change = parse_krx_trading_hours_notice(title, text)

    # Then
    assert change.trading_date == date(2025, 1, 2)
    assert change.opens_at == time(10)
    assert change.closes_at == time(15, 30)


def test_notice_parser_rejects_a_document_without_stock_and_etf_scope() -> None:
    # Given
    text = "대학수학능력시험일(2025.11.13) 파생상품시장 09:00~15:30 10:00~16:30"

    # When / Then
    with pytest.raises(KrxNoticeContractError, match="stock and ETF scope"):
        _ = parse_krx_trading_hours_notice(_CSAT_TITLE, text)


def test_notice_adapter_collects_official_pdf_as_a_shortened_session() -> None:
    # Given
    requests: list[httpx2.Request] = []
    fixture_text = (_FIXTURES / "2025_csat_trading_hours.txt").read_text(encoding="utf-8")

    def response_for(request: httpx2.Request) -> httpx2.Response:
        requests.append(request)
        if request.url.path == KRX_OTP_ENDPOINT:
            return httpx2.Response(200, request=request, text="fixture-otp")
        if request.url.path == KRX_NOTICE_DATA_ENDPOINT:
            form = parse_qs(request.content.decode())
            if "seq" not in form:
                return httpx2.Response(
                    200,
                    request=request,
                    json={
                        "output": [
                            {
                                "rn": "1",
                                "totCnt": "1",
                                "hpage_bbs_tp_cd": "0013",
                                "noti_no": "2025103001",
                                "title": _CSAT_TITLE,
                                "creat_ddtm": "2025/10/30",
                                "contn": "첨부참조",
                                "noti_dd": "2025/10/30",
                                "use_yn": "Y",
                                "opn_yn": "Y",
                                "inq_cnt": "459",
                            }
                        ]
                    },
                )
            return httpx2.Response(
                200,
                request=request,
                json={
                    "block1": [
                        {
                            "file_seq": "2",
                            "file_path": "/obk/dyn/noti/",
                            "save_file_nm": "202510300000012.pdf",
                            "file_nm": "2025 수능일 거래시간.pdf",
                        }
                    ]
                },
            )
        if request.url.path == "/attach/obk/dyn/noti/202510300000012.pdf":
            return httpx2.Response(200, request=request, content=b"fixture-pdf")
        return httpx2.Response(404, request=request)

    class FixturePdfExtractor:
        def extract_text(self, content: bytes) -> str:
            assert content == b"fixture-pdf"
            return fixture_text

    async def run() -> tuple[CalendarObservation, ...]:
        transport = httpx2.MockTransport(response_for)
        open_client = httpx2.AsyncClient(
            base_url="https://open.krx.co.kr",
            transport=transport,
        )
        attachment_client = httpx2.AsyncClient(
            base_url="https://inc.krx.co.kr/attach/",
            transport=transport,
        )
        adapter = KrxTradingHoursNoticeAdapter(
            KrxTradingHoursHttpClient(open_client, attachment_client),
            FixturePdfExtractor(),
        )
        try:
            return await adapter.fetch_overrides(
                CalendarSessionRange("KR", "XKRX", date(2025, 11, 13), date(2025, 11, 13))
            )
        finally:
            await adapter.close()

    # When
    observations = anyio.run(run)

    # Then
    assert len(observations) == 1
    observation = observations[0]
    assert isinstance(observation.session, ShortenedMarketSession)
    assert observation.session.window.opens_at.astimezone(_SEOUL).time() == time(10)
    assert observation.session.window.closes_at.astimezone(_SEOUL).time() == time(16, 30)
    evidence = KrxTradingHoursEvidence.model_validate_json(observation.raw_response.payload_json)
    assert evidence.notice.noti_no == "2025103001"
    assert evidence.pdf_base64 == "Zml4dHVyZS1wZGY="
    assert len([request for request in requests if request.url.path == KRX_OTP_ENDPOINT]) == 2


def test_composite_source_replaces_the_base_session_with_notice_override() -> None:
    # Given
    query = CalendarSessionRange("KR", "XKRX", date(2026, 1, 2), date(2026, 1, 2))
    key = CalendarSessionKey("KR", "XKRX", date(2026, 1, 2), query.session_type)
    base_observation = _observation(
        OpenMarketSession(
            key,
            SessionWindow(
                datetime.combine(key.trading_date, time(9), _SEOUL).astimezone(UTC),
                datetime.combine(key.trading_date, time(15, 30), _SEOUL).astimezone(UTC),
            ),
        ),
        "annual",
    )
    override_observation = _observation(
        ShortenedMarketSession(
            key,
            SessionWindow(
                datetime.combine(key.trading_date, time(10), _SEOUL).astimezone(UTC),
                datetime.combine(key.trading_date, time(15, 30), _SEOUL).astimezone(UTC),
            ),
            "연초 개장일",
        ),
        "notice",
    )

    class BaseSource:
        closed: bool = False

        async def fetch_sessions(
            self,
            query: CalendarSessionRange,
        ) -> tuple[CalendarObservation, ...]:
            assert query == outer_query
            return (base_observation,)

        async def close(self) -> None:
            self.closed = True

    class NoticeSource:
        closed: bool = False

        async def fetch_overrides(
            self,
            query: CalendarSessionRange,
        ) -> tuple[CalendarObservation, ...]:
            assert query == outer_query
            return (override_observation,)

        async def close(self) -> None:
            self.closed = True

    outer_query = query
    base = BaseSource()
    notices = NoticeSource()
    composite = KrxCompositeCalendarSource(base, notices)

    async def run() -> tuple[CalendarObservation, ...]:
        try:
            return await composite.fetch_sessions(query)
        finally:
            await composite.close()

    # When
    observations = anyio.run(run)

    # Then
    assert observations == (override_observation,)
    assert calendar_session_key(observations[0].session) == key
    assert base.closed is True
    assert notices.closed is True


def test_notice_adapter_fails_closed_for_an_unknown_temporary_stock_notice() -> None:
    # Given
    title = "증권시장 거래시간 임시 변경 특별 안내"
    payload = json.dumps(
        {
            "output": [
                {
                    "rn": "1",
                    "totCnt": "1",
                    "hpage_bbs_tp_cd": "0013",
                    "noti_no": "2026010101",
                    "title": title,
                    "creat_ddtm": "2026/01/01",
                    "contn": "첨부참조",
                    "noti_dd": "2026/01/01",
                    "use_yn": "Y",
                    "opn_yn": "Y",
                    "inq_cnt": "1",
                }
            ]
        }
    )

    def response_for(request: httpx2.Request) -> httpx2.Response:
        if request.url.path == KRX_OTP_ENDPOINT:
            return httpx2.Response(200, request=request, text="fixture-otp")
        return httpx2.Response(200, request=request, text=payload)

    async def run() -> None:
        transport = httpx2.MockTransport(response_for)
        client = KrxTradingHoursHttpClient(
            httpx2.AsyncClient(base_url="https://open.krx.co.kr", transport=transport),
            httpx2.AsyncClient(base_url="https://inc.krx.co.kr/attach/", transport=transport),
        )
        adapter = KrxTradingHoursNoticeAdapter(client)
        try:
            _ = await adapter.fetch_overrides(
                CalendarSessionRange("KR", "XKRX", date(2026, 1, 1), date(2026, 1, 2))
            )
        finally:
            await adapter.close()

    # When / Then
    with pytest.raises(KrxNoticeContractError, match="unsupported temporary"):
        anyio.run(run)


def _observation(
    session: OpenMarketSession | ShortenedMarketSession,
    fingerprint: str,
) -> CalendarObservation:
    observed_at = datetime(2025, 12, 18, 6, tzinfo=UTC)
    return CalendarObservation(
        session=session,
        exchange_timezone="Asia/Seoul",
        source=CalendarSource("KRX", fingerprint, date(2025, 12, 18)),
        raw_response=CalendarRawResponse("fixture", fingerprint, observed_at, "{}"),
        verification=PendingVerification(),
    )
