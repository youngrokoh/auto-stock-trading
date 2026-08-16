import base64
from datetime import UTC, date, datetime, timedelta
from io import BytesIO
from typing import Protocol, final
from zoneinfo import ZoneInfo

import httpx2
from pydantic import ValidationError
from pypdf import PdfReader

from auto_stock_trading.adapters.exchanges.krx_market_calendar import (
    KRX_OTP_ENDPOINT,
    KrxTransportError,
)
from auto_stock_trading.adapters.exchanges.krx_trading_hours_contracts import (
    KrxNoticeAttachment,
    KrxNoticeAttachmentResponse,
    KrxNoticeContractError,
    KrxNoticeListResponse,
    KrxNoticeRow,
    KrxTradingHoursEvidence,
    classify_krx_trading_hours_notice,
    krx_notice_target_date_hint,
    parse_krx_trading_hours_notice,
)
from auto_stock_trading.domain.market_data.calendar import (
    CalendarObservation,
    CalendarRawResponse,
    CalendarSessionKey,
    CalendarSessionRange,
    CalendarSource,
    MarketSessionType,
    PendingVerification,
    SessionWindow,
    ShortenedMarketSession,
    calendar_session_key,
)

KRX_NOTICE_DATA_ENDPOINT = "/contents/OPN/99/OPN99000001.jspx"
_NOTICE_LIST_BLD = "OPN/05/05000000/opn05000000t1_01"
_NOTICE_ATTACHMENT_BLD = "OPN/05/05000000/opn05000000t1_03"
_NOTICE_PAGE = "/contents/OPN/05/05000000/OPN05000000T1.jsp"
_LOOKBACK_DAYS = 120
_HTTP_ERROR_STATUS = 400
_SEOUL = ZoneInfo("Asia/Seoul")


class PdfTextExtractor(Protocol):
    def extract_text(self, content: bytes) -> str: ...


@final
class PypdfTextExtractor:
    def extract_text(self, content: bytes) -> str:
        if not content.startswith(b"%PDF"):
            message = "KRX trading-hours attachment is not a PDF"
            raise KrxNoticeContractError(message)
        reader = PdfReader(BytesIO(content))
        text = "\n".join(page.extract_text() or "" for page in reader.pages)
        if not text.strip():
            message = "KRX trading-hours PDF did not contain extractable text"
            raise KrxNoticeContractError(message)
        return text


@final
class KrxTradingHoursHttpClient:
    def __init__(
        self,
        open_client: httpx2.AsyncClient,
        attachment_client: httpx2.AsyncClient,
    ) -> None:
        self._open_client = open_client
        self._attachment_client = attachment_client

    async def search_notices(self, start_date: date, end_date: date) -> tuple[KrxNoticeRow, ...]:
        payload = await self._fetch_json(
            _NOTICE_LIST_BLD,
            {
                "sch_tp": "title",
                "sch_word": "거래시간",
                "fromdate": start_date.strftime("%Y%m%d"),
                "todate": end_date.strftime("%Y%m%d"),
                "curPage": "1",
                "pageSize": "100",
                "pagePath": _NOTICE_PAGE,
            },
        )
        try:
            response = KrxNoticeListResponse.model_validate_json(payload)
        except ValidationError as error:
            message = "KRX trading-hours notice list did not match the expected contract"
            raise KrxNoticeContractError(message) from error
        if response.output and len(response.output) != response.output[0].total_count:
            message = "KRX trading-hours notice list pagination is incomplete"
            raise KrxNoticeContractError(message)
        return response.output

    async def fetch_attachments(self, notice_number: str) -> tuple[KrxNoticeAttachment, ...]:
        payload = await self._fetch_json(
            _NOTICE_ATTACHMENT_BLD,
            {"seq": notice_number, "pagePath": _NOTICE_PAGE},
        )
        try:
            response = KrxNoticeAttachmentResponse.model_validate_json(payload)
        except ValidationError as error:
            message = "KRX trading-hours attachment list did not match the expected contract"
            raise KrxNoticeContractError(message) from error
        return response.block1

    async def download(self, attachment: KrxNoticeAttachment) -> bytes:
        if not attachment.file_path.startswith("/"):
            message = "KRX trading-hours attachment path is invalid"
            raise KrxNoticeContractError(message)
        endpoint = f"{attachment.file_path.lstrip('/')}{attachment.save_file_nm}"
        request = self._attachment_client.build_request("GET", endpoint)
        response = await self._send(self._attachment_client, request)
        return response.content

    async def close(self) -> None:
        try:
            await self._open_client.aclose()
        finally:
            await self._attachment_client.aclose()

    async def _fetch_json(self, bld: str, data: dict[str, str]) -> str:
        otp_request = self._open_client.build_request(
            "GET",
            KRX_OTP_ENDPOINT,
            params={"name": "form", "bld": bld},
        )
        otp = await self._send(self._open_client, otp_request)
        code = otp.text.strip()
        if not code:
            message = "KRX trading-hours endpoint returned an empty OTP"
            raise KrxNoticeContractError(message)
        data_request = self._open_client.build_request(
            "POST",
            KRX_NOTICE_DATA_ENDPOINT,
            data={"code": code, **data},
            headers={"Referer": f"{self._open_client.base_url}{_NOTICE_PAGE}"},
        )
        response = await self._send(self._open_client, data_request)
        return response.text

    async def _send(
        self,
        client: httpx2.AsyncClient,
        request: httpx2.Request,
    ) -> httpx2.Response:
        try:
            response = await client.send(request)
        except httpx2.HTTPError as error:
            raise KrxTransportError(request.url.path, None) from error
        if response.status_code >= _HTTP_ERROR_STATUS:
            raise KrxTransportError(request.url.path, response.status_code)
        return response


@final
class KrxTradingHoursNoticeAdapter:
    def __init__(
        self,
        client: KrxTradingHoursHttpClient,
        extractor: PdfTextExtractor | None = None,
    ) -> None:
        self._client = client
        self._extractor = extractor or PypdfTextExtractor()

    async def fetch_overrides(
        self,
        query: CalendarSessionRange,
    ) -> tuple[CalendarObservation, ...]:
        _require_supported_query(query)
        published_from = query.start_date - timedelta(days=_LOOKBACK_DAYS)
        notices = await self._client.search_notices(published_from, query.end_date)
        observations: dict[date, CalendarObservation] = {}
        for notice in notices:
            if classify_krx_trading_hours_notice(notice.title) is None:
                continue
            target_hint = krx_notice_target_date_hint(notice.title, _publication_date(notice))
            if not query.start_date <= target_hint <= query.end_date:
                continue
            observation = await self._observation(notice, query)
            if observation is None:
                continue
            trading_date = calendar_session_key(observation.session).trading_date
            if trading_date in observations:
                message = f"multiple KRX trading-hours notices target {trading_date}"
                raise KrxNoticeContractError(message)
            observations[trading_date] = observation
        return tuple(observations[item] for item in sorted(observations))

    async def close(self) -> None:
        await self._client.close()

    async def _observation(
        self,
        notice: KrxNoticeRow,
        query: CalendarSessionRange,
    ) -> CalendarObservation | None:
        attachments = await self._client.fetch_attachments(notice.noti_no)
        pdfs = tuple(item for item in attachments if item.save_file_nm.lower().endswith(".pdf"))
        if len(pdfs) != 1:
            message = f"KRX trading-hours notice {notice.noti_no} must have exactly one PDF"
            raise KrxNoticeContractError(message)
        attachment = pdfs[0]
        content = await self._client.download(attachment)
        change = parse_krx_trading_hours_notice(notice.title, self._extractor.extract_text(content))
        if not query.start_date <= change.trading_date <= query.end_date:
            return None
        received_at = datetime.now(UTC)
        evidence = KrxTradingHoursEvidence(
            notice=notice,
            attachment=attachment,
            pdf_base64=base64.b64encode(content).decode("ascii"),
        )
        raw = CalendarRawResponse(
            endpoint=f"/attach{attachment.file_path}{attachment.save_file_nm}",
            request_fingerprint=f"krx:trading-hours:{notice.noti_no}:{attachment.file_seq}",
            received_at=received_at,
            payload_json=evidence.model_dump_json(),
        )
        key = CalendarSessionKey(
            query.country,
            query.exchange,
            change.trading_date,
            query.session_type,
        )
        session = ShortenedMarketSession(
            key,
            SessionWindow(
                datetime.combine(change.trading_date, change.opens_at, _SEOUL).astimezone(UTC),
                datetime.combine(change.trading_date, change.closes_at, _SEOUL).astimezone(UTC),
            ),
            notice.title,
        )
        return CalendarObservation(
            session=session,
            exchange_timezone="Asia/Seoul",
            source=CalendarSource(
                "KRX",
                f"KRX press release {notice.noti_no}",
                date.fromisoformat(notice.noti_dd.replace("/", "-")),
            ),
            raw_response=raw,
            verification=PendingVerification(),
        )


def _require_supported_query(query: CalendarSessionRange) -> None:
    if query.country != "KR" or query.exchange != "XKRX":
        message = "KRX trading-hours notice adapter only supports KR/XKRX"
        raise ValueError(message)
    if query.session_type is not MarketSessionType.REGULAR:
        message = "KRX trading-hours notice adapter only supports regular sessions"
        raise ValueError(message)


def _publication_date(notice: KrxNoticeRow) -> date:
    try:
        return date.fromisoformat(notice.noti_dd.replace("/", "-"))
    except ValueError as error:
        message = f"KRX trading-hours notice {notice.noti_no} has an invalid publication date"
        raise KrxNoticeContractError(message) from error
