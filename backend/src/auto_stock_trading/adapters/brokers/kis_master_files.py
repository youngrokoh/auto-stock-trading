import base64
import io
import json
import zipfile
from typing import TYPE_CHECKING, Final, final

import httpx2

from auto_stock_trading.domain.market_data.etf import EtfMasterBundle, EtfProfile
from auto_stock_trading.domain.market_data.models import BrokerOperation, RawBrokerResponse
from auto_stock_trading.domain.market_data.stocks import (
    StockListing,
    StockListingBundle,
    StockMasterBundle,
    StockProfile,
)

if TYPE_CHECKING:
    from datetime import datetime

KOSPI_MASTER_PATH: Final = "/common/master/kospi_code.mst.zip"
_ETF_GROUP: Final = "EF"
_STOCK_GROUP: Final = "ST"
_NOT_A_MEMBER: Final = "0"
_COMMON_SHARE_SUFFIX: Final = "0"
_SYMBOL_LENGTH: Final = 6
_RECORD_MIN_LENGTH: Final = 63
_UNIVERSE_MIN_LENGTH: Final = 80
_SOURCE: Final = "KIS_MASTER"
_HTTP_OK: Final = 200


class MasterFileTransportError(Exception):
    def __init__(self, path: str, status_code: int | None) -> None:
        detail = "no response" if status_code is None else f"HTTP {status_code}"
        super().__init__(f"KIS master file request failed at {path}: {detail}")


def parse_kospi_etf_profiles(content: bytes, received_at: datetime) -> tuple[EtfProfile, ...]:
    profiles: list[EtfProfile] = []
    for line in content.split(b"\n"):
        if len(line) < _RECORD_MIN_LENGTH:
            continue
        group = line[61:63].decode("cp949", errors="replace")
        if group != _ETF_GROUP:
            continue
        profiles.append(
            EtfProfile(
                symbol=line[0:9].decode("cp949", errors="replace").strip(),
                isin=line[9:21].decode("cp949", errors="replace"),
                name=line[21:61].decode("cp949", errors="replace").strip(),
                source=_SOURCE,
                received_at=received_at,
            )
        )
    return tuple(profiles)


def parse_kospi_universe_profiles(
    content: bytes,
    received_at: datetime,
) -> tuple[StockProfile, ...]:
    """KOSPI200 구성 보통주만 남긴다. 업종 코드 `0`은 미포함 종목이다."""
    profiles: list[StockProfile] = []
    for line in content.split(b"\n"):
        if len(line) < _UNIVERSE_MIN_LENGTH:
            continue
        if line[61:63].decode("cp949", errors="replace") != _STOCK_GROUP:
            continue
        sector_code = line[79:80].decode("cp949", errors="replace")
        if sector_code == _NOT_A_MEMBER:
            continue
        symbol = line[0:9].decode("cp949", errors="replace").strip()
        if len(symbol) != _SYMBOL_LENGTH or symbol[5] != _COMMON_SHARE_SUFFIX:
            continue
        profiles.append(
            StockProfile(
                symbol=symbol,
                isin=line[9:21].decode("cp949", errors="replace"),
                name=line[21:61].decode("cp949", errors="replace").strip(),
                sector_code=sector_code,
                source=_SOURCE,
                received_at=received_at,
            )
        )
    return tuple(profiles)


def parse_kospi_stock_listings(
    content: bytes,
    received_at: datetime,
) -> tuple[StockListing, ...]:
    """주권(`ST`) 전 행. 보통주와 우선주를 모두 남긴다(유니버스 계약 §주식종류 사실).

    KOSPI200 섹터 코드는 보지 않는다. 우선주에는 코드가 붙지 않으므로 걸러 버리면 짝을 잃는다.
    """
    listings: list[StockListing] = []
    for line in content.split(b"\n"):
        if len(line) < _RECORD_MIN_LENGTH:
            continue
        if line[61:63].decode("cp949", errors="replace") != _STOCK_GROUP:
            continue
        symbol = line[0:9].decode("cp949", errors="replace").strip()
        if len(symbol) != _SYMBOL_LENGTH:
            continue
        listings.append(
            StockListing(
                symbol=symbol,
                isin=line[9:21].decode("cp949", errors="replace"),
                name=line[21:61].decode("cp949", errors="replace").strip(),
                source=_SOURCE,
                received_at=received_at,
            )
        )
    return tuple(listings)


def create_master_http_client(base_url: str) -> httpx2.AsyncClient:
    return httpx2.AsyncClient(
        base_url=base_url,
        timeout=httpx2.Timeout(30.0),
        follow_redirects=True,
        headers={"User-Agent": "auto-stock-trading/0.1"},
    )


async def _download_master(client: httpx2.AsyncClient) -> bytes:
    try:
        response = await client.get(KOSPI_MASTER_PATH)
    except httpx2.HTTPError as error:
        raise MasterFileTransportError(KOSPI_MASTER_PATH, None) from error
    if response.status_code != _HTTP_OK:
        raise MasterFileTransportError(KOSPI_MASTER_PATH, response.status_code)
    archive = zipfile.ZipFile(io.BytesIO(response.content))
    return archive.read(archive.namelist()[0])


def _master_raw(
    content: bytes,
    operation: BrokerOperation,
    now: datetime,
) -> RawBrokerResponse:
    """원본 마스터 파일은 Base64 봉투로 보존한다. 같은 파일을 두 수집이 공유한다."""
    return RawBrokerResponse(
        operation=operation,
        endpoint=KOSPI_MASTER_PATH,
        request_fingerprint=f"{operation.value}:kospi",
        received_at=now,
        payload_json=json.dumps(
            {
                "encoding": "base64",
                "filename": "kospi_code.mst",
                "content": base64.b64encode(content).decode("ascii"),
            }
        ),
    )


@final
class KisEtfMasterAdapter:
    def __init__(self, client: httpx2.AsyncClient) -> None:
        self._client = client

    async def fetch_master(self, now: datetime) -> EtfMasterBundle:
        content = await _download_master(self._client)
        return EtfMasterBundle(
            profiles=parse_kospi_etf_profiles(content, now),
            raw=_master_raw(content, BrokerOperation.ETF_MASTER, now),
            collected_at=now,
        )

    async def close(self) -> None:
        await self._client.aclose()


@final
class KisStockMasterAdapter:
    """같은 마스터 파일에서 주권 레코드만 읽는다(종목 유니버스 계약)."""

    def __init__(self, client: httpx2.AsyncClient) -> None:
        self._client = client

    async def fetch_master(self, now: datetime) -> StockMasterBundle:
        content = await _download_master(self._client)
        return StockMasterBundle(
            profiles=parse_kospi_universe_profiles(content, now),
            raw=_master_raw(content, BrokerOperation.STOCK_MASTER, now),
            collected_at=now,
        )

    async def fetch_listings(self, now: datetime) -> StockListingBundle:
        """주권 전 행. 우선주도 남긴다(유니버스 계약 §주식종류 사실)."""
        content = await _download_master(self._client)
        return StockListingBundle(
            listings=parse_kospi_stock_listings(content, now),
            raw=_master_raw(content, BrokerOperation.STOCK_MASTER, now),
            collected_at=now,
        )

    async def close(self) -> None:
        await self._client.aclose()
