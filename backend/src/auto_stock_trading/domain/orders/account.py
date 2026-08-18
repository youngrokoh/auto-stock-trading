import hashlib
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from datetime import date, datetime
    from decimal import Decimal

    from auto_stock_trading.domain.market_data.models import RawBrokerResponse

_ACCOUNT_REFERENCE_LENGTH: Final = 12


def account_reference(account_number: str, product_code: str) -> str:
    """계좌번호 원문 대신 저장·노출하는 단방향 참조."""
    digest = hashlib.sha256(f"{account_number}|{product_code}".encode()).hexdigest()
    return digest[:_ACCOUNT_REFERENCE_LENGTH]


@dataclass(frozen=True, slots=True)
class AccountPosition:
    symbol: str
    quantity: int
    orderable_quantity: int
    average_price: Decimal
    current_price: Decimal
    evaluation_amount: Decimal
    profit_loss: Decimal


@dataclass(frozen=True, slots=True)
class AccountSnapshot:
    source: str
    environment: str
    account_reference: str
    currency: str
    cash_balance: Decimal
    orderable_cash: Decimal
    position_value: Decimal
    nav: Decimal
    broker_net_asset: Decimal
    trading_date: date
    as_of: datetime
    received_at: datetime
    positions: tuple[AccountPosition, ...]


@dataclass(frozen=True, slots=True)
class AccountSnapshotObservation:
    snapshot: AccountSnapshot
    raw: RawBrokerResponse
