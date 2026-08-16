import re
from dataclasses import dataclass
from datetime import date, time
from enum import StrEnum
from typing import ClassVar, final, override

from pydantic import BaseModel, ConfigDict, Field


class _KrxNoticeContract(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(
        extra="forbid",
        frozen=True,
        populate_by_name=True,
    )


class KrxNoticeRow(_KrxNoticeContract):
    rn: int
    total_count: int = Field(alias="totCnt")
    hpage_bbs_tp_cd: str
    noti_no: str
    title: str
    creat_ddtm: str
    contn: str
    noti_dd: str
    use_yn: str
    opn_yn: str
    inq_cnt: int


class KrxNoticeListResponse(_KrxNoticeContract):
    output: tuple[KrxNoticeRow, ...] = ()


class KrxNoticeAttachment(_KrxNoticeContract):
    file_seq: int
    file_path: str
    save_file_nm: str
    file_nm: str


class KrxNoticeAttachmentResponse(_KrxNoticeContract):
    block1: tuple[KrxNoticeAttachment, ...] = ()


class KrxTradingHoursEvidence(_KrxNoticeContract):
    notice: KrxNoticeRow
    attachment: KrxNoticeAttachment
    pdf_base64: str


@final
@dataclass(frozen=True, slots=True)
class KrxTradingHoursChange:
    trading_date: date
    opens_at: time
    closes_at: time


@final
@dataclass(slots=True)
class KrxNoticeContractError(Exception):
    message: str

    @override
    def __str__(self) -> str:
        return self.message


class KrxNoticeKind(StrEnum):
    CSAT = "csat"
    YEAR_OPENING = "year_opening"


def classify_krx_trading_hours_notice(title: str) -> KrxNoticeKind | None:
    normalized = _without_whitespace(title)
    if (
        "대학수학능력시험일" in normalized
        and "증권시장" in normalized
        and "거래시간임시변경" in normalized
    ):
        return KrxNoticeKind.CSAT
    if (
        "연말시장운영" in normalized
        and "연초개장일" in normalized
        and "매매거래시간안내" in normalized
    ):
        return KrxNoticeKind.YEAR_OPENING
    if (
        "거래시간" in normalized
        and "임시" in normalized
        and ("증권시장" in normalized or "개장일" in normalized)
    ):
        message = f"unsupported temporary KRX stock trading-hours notice: {title}"
        raise KrxNoticeContractError(message)
    return None


def parse_krx_trading_hours_notice(
    title: str,
    document_text: str,
) -> KrxTradingHoursChange:
    kind = classify_krx_trading_hours_notice(title)
    if kind is None:
        message = "KRX notice title is not a supported trading-hours notice"
        raise KrxNoticeContractError(message)
    normalized = _without_whitespace(document_text)
    explicit_scope = "유가증권시장,코스닥시장" in normalized and (
        "주식,상장지수펀드" in normalized or "주식,상장지수펀드(ETF)" in normalized
    )
    legacy_opening_scope = kind is KrxNoticeKind.YEAR_OPENING and all(
        marker in normalized
        for marker in (
            "유가증권시장본부주식시장부",
            "코스닥시장본부코스닥시장부",
            "증시개장식에따른매매거래시간임시변경",
            "신주인수권증서",
            "주식워런트증권",
        )
    )
    if not explicit_scope and not legacy_opening_scope:
        message = "KRX trading-hours notice is missing the stock and ETF scope"
        raise KrxNoticeContractError(message)
    trading_date = _trading_date(kind, title, normalized)
    window = re.search(
        r"정규시장[^0-9]{0,40}09:00~15:30(\d{2}:\d{2})~(\d{2}:\d{2})",
        normalized,
    )
    if window is None:
        message = "KRX trading-hours notice is missing the approved regular-session baseline"
        raise KrxNoticeContractError(message)
    opens_at = _parse_time(window.group(1))
    closes_at = _parse_time(window.group(2))
    if opens_at == time(9) and closes_at == time(15, 30):
        message = "KRX trading-hours notice did not change the regular session"
        raise KrxNoticeContractError(message)
    return KrxTradingHoursChange(trading_date, opens_at, closes_at)


def krx_notice_target_date_hint(title: str, published_at: date) -> date:
    kind = classify_krx_trading_hours_notice(title)
    normalized = _without_whitespace(title)
    if kind is KrxNoticeKind.CSAT:
        match = re.search(r"대학수학능력시험일\((\d{1,2})\.(\d{1,2})\)", normalized)
        groups = (str(published_at.year), *match.groups()) if match is not None else None
    elif kind is KrxNoticeKind.YEAR_OPENING:
        match = re.search(r"(20\d{2})년연초개장일\((\d{1,2})\.(\d{1,2})", normalized)
        groups = match.groups() if match is not None else None
    else:
        groups = None
    if groups is None:
        message = "KRX trading-hours notice title is missing its target date hint"
        raise KrxNoticeContractError(message)
    return _date_from(groups)


def _trading_date(kind: KrxNoticeKind, title: str, document_text: str) -> date:
    if kind is KrxNoticeKind.CSAT:
        match = re.search(r"대학수학능력시험일\((20\d{2})\.(\d{1,2})\.(\d{1,2})\)", document_text)
    else:
        match = re.search(
            r"(20\d{2})년연초개장일\((\d{1,2})\.(\d{1,2})",
            _without_whitespace(title),
        )
    if match is None:
        message = "KRX trading-hours notice is missing its target trading date"
        raise KrxNoticeContractError(message)
    return _date_from(match.groups())


def _date_from(groups: tuple[str, ...]) -> date:
    try:
        return date(*(int(value) for value in groups))
    except ValueError as error:
        message = "KRX trading-hours notice contains an invalid target trading date"
        raise KrxNoticeContractError(message) from error


def _parse_time(value: str) -> time:
    hour, minute = (int(part) for part in value.split(":"))
    try:
        return time(hour, minute)
    except ValueError as error:
        message = "KRX trading-hours notice contains an invalid session time"
        raise KrxNoticeContractError(message) from error


def _without_whitespace(value: str) -> str:
    return re.sub(r"\s+", "", value)
