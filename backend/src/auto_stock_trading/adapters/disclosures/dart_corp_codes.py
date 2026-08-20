"""DART 고유번호 전체 파일(`corpCode.xml`) 수집. 상장 종목코드가 있는 항목만 남긴다."""

import base64
import io
import json
import re
import zipfile
from typing import TYPE_CHECKING, Final, final

from auto_stock_trading.domain.market_data.corp_codes import DartCorpCode, DartCorpCodeBundle
from auto_stock_trading.domain.market_data.models import BrokerOperation, RawBrokerResponse

if TYPE_CHECKING:
    from datetime import datetime

    from auto_stock_trading.adapters.disclosures.opendart_http import DartHttpClient

DART_CORP_CODE_ENDPOINT: Final = "/api/corpCode.xml"
_SOURCE: Final = "DART"
_ENTRY: Final = re.compile(r"<list>(.*?)</list>", re.DOTALL)
_FIELD: Final = "<{name}>(.*?)</{name}>"
# 실측: 종목코드 3,984개 중 56개가 문자를 포함한다(예: 0126Z0). 숫자만 받으면 유니버스가 빠진다.
_STOCK_CODE: Final = re.compile(r"^[0-9A-Z]{6}$")
_ZIP_MAGIC: Final = b"PK"


class DartCorpCodeUnavailableError(Exception):
    """DART가 점검 등으로 전체 파일을 주지 않는 상태. 매핑을 추측해 만들지 않는다."""

    def __init__(self, detail: str) -> None:
        super().__init__(f"DART corp code file is unavailable: {detail}")


def _field(entry: str, name: str) -> str | None:
    match = re.search(_FIELD.format(name=name), entry, re.DOTALL)
    return None if match is None else match.group(1).strip()


def parse_corp_codes(content: bytes, received_at: datetime) -> tuple[DartCorpCode, ...]:
    """종목코드 6자리가 있는 항목만 남긴다. 같은 종목코드는 뒤 항목이 현재 사실이다."""
    text = content.decode("utf-8", errors="replace")
    by_symbol: dict[str, DartCorpCode] = {}
    for match in _ENTRY.finditer(text):
        entry = match.group(1)
        symbol = _field(entry, "stock_code")
        corp_code = _field(entry, "corp_code")
        corp_name = _field(entry, "corp_name")
        if symbol is None or corp_code is None or corp_name is None:
            continue
        if not _STOCK_CODE.match(symbol):
            continue
        by_symbol[symbol] = DartCorpCode(
            symbol=symbol,
            corp_code=corp_code,
            corp_name=corp_name,
            source=_SOURCE,
            received_at=received_at,
        )
    return tuple(by_symbol.values())


@final
class DartCorpCodeAdapter:
    def __init__(self, client: DartHttpClient) -> None:
        self._client = client

    async def fetch_corp_codes(self, now: datetime) -> DartCorpCodeBundle:
        payload = await self._client.fetch_bytes(DART_CORP_CODE_ENDPOINT, {})
        if payload[: len(_ZIP_MAGIC)] != _ZIP_MAGIC:
            # 점검 중에는 ZIP 대신 status 800 XML이 온다(실측).
            raise DartCorpCodeUnavailableError(
                payload.decode("utf-8", errors="replace")[:200],
            )
        archive = zipfile.ZipFile(io.BytesIO(payload))
        content = archive.read(archive.namelist()[0])
        raw = RawBrokerResponse(
            operation=BrokerOperation.CORP_CODES,
            endpoint=DART_CORP_CODE_ENDPOINT,
            request_fingerprint="corp_codes:all",
            received_at=now,
            payload_json=json.dumps(
                {
                    "encoding": "base64",
                    "filename": archive.namelist()[0],
                    "content": base64.b64encode(content).decode("ascii"),
                }
            ),
        )
        return DartCorpCodeBundle(
            codes=parse_corp_codes(content, now),
            raw=raw,
            collected_at=now,
        )

    async def close(self) -> None:
        await self._client.close()
