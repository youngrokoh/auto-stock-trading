import base64
import io
import json
import zipfile
from typing import TYPE_CHECKING, Final, final

import httpx2

from auto_stock_trading.domain.market_data.etf import EtfMasterBundle, EtfProfile
from auto_stock_trading.domain.market_data.models import BrokerOperation, RawBrokerResponse

if TYPE_CHECKING:
    from datetime import datetime

KOSPI_MASTER_PATH: Final = "/common/master/kospi_code.mst.zip"
_ETF_GROUP: Final = "EF"
_RECORD_MIN_LENGTH: Final = 63
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


def create_master_http_client(base_url: str) -> httpx2.AsyncClient:
    return httpx2.AsyncClient(
        base_url=base_url,
        timeout=httpx2.Timeout(30.0),
        follow_redirects=True,
        headers={"User-Agent": "auto-stock-trading/0.1"},
    )


@final
class KisEtfMasterAdapter:
    def __init__(self, client: httpx2.AsyncClient) -> None:
        self._client = client

    async def fetch_master(self, now: datetime) -> EtfMasterBundle:
        try:
            response = await self._client.get(KOSPI_MASTER_PATH)
        except httpx2.HTTPError as error:
            raise MasterFileTransportError(KOSPI_MASTER_PATH, None) from error
        if response.status_code != _HTTP_OK:
            raise MasterFileTransportError(KOSPI_MASTER_PATH, response.status_code)
        archive = zipfile.ZipFile(io.BytesIO(response.content))
        content = archive.read(archive.namelist()[0])
        raw = RawBrokerResponse(
            operation=BrokerOperation.ETF_MASTER,
            endpoint=KOSPI_MASTER_PATH,
            request_fingerprint="etf_master:kospi",
            received_at=now,
            payload_json=json.dumps(
                {
                    "encoding": "base64",
                    "filename": "kospi_code.mst",
                    "content": base64.b64encode(content).decode("ascii"),
                }
            ),
        )
        return EtfMasterBundle(
            profiles=parse_kospi_etf_profiles(content, now),
            raw=raw,
            collected_at=now,
        )

    async def close(self) -> None:
        await self._client.aclose()
