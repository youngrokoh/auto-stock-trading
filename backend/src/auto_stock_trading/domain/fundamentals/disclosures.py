from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datetime import date, datetime

    from auto_stock_trading.domain.fundamentals.financial_statements import (
        FinancialRawResponse,
    )


class DisclosureType(StrEnum):
    PERIODIC = "A"
    MATERIAL_EVENT = "B"
    OWNERSHIP = "D"
    EXCHANGE = "I"


@dataclass(frozen=True, slots=True)
class Disclosure:
    symbol: str
    corp_code: str
    rcept_no: str
    report_nm: str
    filer_name: str
    receipt_date: date
    disclosure_type: DisclosureType
    received_at: datetime


@dataclass(frozen=True, slots=True)
class DisclosurePage:
    raw: FinancialRawResponse
    disclosures: tuple[Disclosure, ...]


@dataclass(frozen=True, slots=True)
class DisclosureBundle:
    symbol: str
    corp_code: str
    pages: tuple[DisclosurePage, ...]
    collected_at: datetime

    @property
    def disclosures(self) -> tuple[Disclosure, ...]:
        return tuple(entry for page in self.pages for entry in page.disclosures)
