from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datetime import datetime


@dataclass(frozen=True, slots=True)
class ListedShareCount:
    symbol: str
    share_count: int
    source: str
    as_of: datetime
    received_at: datetime


@dataclass(frozen=True, slots=True)
class VersionedListedShareCount:
    symbol: str
    share_count: int
    source: str
    as_of: datetime
    received_at: datetime
    version: int
    valid_from: datetime
    superseded_at: datetime | None
