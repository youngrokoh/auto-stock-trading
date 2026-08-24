"""상장 주식종류 짝짓기(종목 유니버스 계약 §주식종류 사실). 순수 함수다.

우선주를 모르면 시가총액이 보통주분만 잡히고(실측 삼성전자는 실제의 90.8%) 주당 지표가 어느
클래스의 것인지 확정되지 않는다. 그래서 상장 주식종류를 사실로 만든다.

짝짓기는 단축코드 앞 5자리라는 KRX 관행에 기댄다. 실측(2026-08-23)으로 접두를 공유하는 종목군
95개 전부에서 보통주가 정확히 하나이고 짝 없는 우선주는 0개였지만, 원천이 보장하는 규칙이
아니므로 예외는 추측하지 않고 거부한다.
"""

from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from auto_stock_trading.domain.market_data.models import ShareClassKind

__all__ = [
    "ShareClass",
    "ShareClassGroup",
    "ShareClassKind",
    "ShareClassPairing",
    "pair_share_classes",
]

if TYPE_CHECKING:
    from collections.abc import Sequence

    from auto_stock_trading.domain.market_data.stocks import StockListing

_PREFIX_LENGTH: Final = 5
_COMMON_SHARE_SUFFIX: Final = "0"
_NO_COMMON: Final = "no common share for the prefix"
_MANY_COMMON: Final = "more than one common share for the prefix"


@dataclass(frozen=True, slots=True)
class ShareClass:
    symbol: str
    class_kind: ShareClassKind
    isin: str
    name: str


@dataclass(frozen=True, slots=True)
class ShareClassGroup:
    """한 회사의 상장 클래스. 첫 항목이 보통주다."""

    common_symbol: str
    classes: tuple[ShareClass, ...]

    @property
    def has_preferred(self) -> bool:
        return any(item.class_kind is ShareClassKind.PREFERRED for item in self.classes)

    @property
    def preferred_symbols(self) -> tuple[str, ...]:
        return tuple(
            item.symbol for item in self.classes if item.class_kind is ShareClassKind.PREFERRED
        )


@dataclass(frozen=True, slots=True)
class ShareClassPairing:
    groups: tuple[ShareClassGroup, ...]
    # (접두, 사유). 거부한 군은 저장하지 않고 보고한다.
    refused: tuple[tuple[str, str], ...]


def _kind(symbol: str) -> ShareClassKind:
    return (
        ShareClassKind.COMMON
        if symbol[_PREFIX_LENGTH] == _COMMON_SHARE_SUFFIX
        else ShareClassKind.PREFERRED
    )


def pair_share_classes(listings: Sequence[StockListing]) -> ShareClassPairing:
    """단축코드 앞 5자리로 보통주와 우선주를 묶는다. 예외 군은 통째로 거부한다."""
    by_prefix: dict[str, list[StockListing]] = {}
    for listing in listings:
        if len(listing.symbol) <= _PREFIX_LENGTH:
            continue
        by_prefix.setdefault(listing.symbol[:_PREFIX_LENGTH], []).append(listing)
    groups: list[ShareClassGroup] = []
    refused: list[tuple[str, str]] = []
    for prefix in sorted(by_prefix):
        items = by_prefix[prefix]
        commons = [item for item in items if _kind(item.symbol) is ShareClassKind.COMMON]
        if not commons:
            refused.append((prefix, _NO_COMMON))
            continue
        if len(commons) > 1:
            refused.append((prefix, _MANY_COMMON))
            continue
        common = commons[0]
        preferred = sorted(
            (item for item in items if _kind(item.symbol) is ShareClassKind.PREFERRED),
            key=lambda item: item.symbol,
        )
        groups.append(
            ShareClassGroup(
                common_symbol=common.symbol,
                classes=tuple(
                    ShareClass(
                        symbol=item.symbol,
                        class_kind=_kind(item.symbol),
                        isin=item.isin,
                        name=item.name,
                    )
                    for item in (common, *preferred)
                ),
            )
        )
    groups.sort(key=lambda group: group.common_symbol)
    return ShareClassPairing(groups=tuple(groups), refused=tuple(refused))
