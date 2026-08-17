import io
import zipfile
from pathlib import Path
from urllib.parse import parse_qs

import httpx2
from pydantic import SecretStr

from auto_stock_trading.adapters.disclosures.opendart_corporate_actions import (
    DartCorporateActionAdapter,
    DartDividendTarget,
)
from auto_stock_trading.adapters.disclosures.opendart_http import (
    DART_DOCUMENT_ENDPOINT,
    DART_LIST_ENDPOINT,
    DartHttpClient,
)

_FIXTURE_ROOT = Path(__file__).parents[1] / "fixtures" / "dart"
_DEFAULT_TARGET = DartDividendTarget(symbol="005930", corp_code="00126380")


class DartFixtureHandler:
    requests: list[httpx2.Request]
    _list_filename: str

    def __init__(self, list_filename: str) -> None:
        self.requests = []
        self._list_filename = list_filename

    def __call__(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append(request)
        query = parse_qs(request.url.query.decode())
        if not query.get("crtfc_key"):
            return httpx2.Response(400, request=request)
        if request.url.path == DART_LIST_ENDPOINT:
            return httpx2.Response(
                200,
                request=request,
                headers={"Content-Type": "application/json"},
                text=(_FIXTURE_ROOT / self._list_filename).read_text(encoding="utf-8"),
            )
        if request.url.path == DART_DOCUMENT_ENDPOINT:
            rcept_no = query.get("rcept_no", [""])[0]
            document = _FIXTURE_ROOT / f"{rcept_no}.html"
            if not document.exists():
                return httpx2.Response(404, request=request)
            return httpx2.Response(
                200,
                request=request,
                headers={"Content-Type": "application/zip"},
                content=_zip_document(rcept_no, document),
            )
        return httpx2.Response(404, request=request)


def _zip_document(rcept_no: str, document: Path) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            f"{rcept_no}.html",
            document.read_text(encoding="utf-8").encode("euc-kr"),
        )
    return buffer.getvalue()


def create_fixture_adapter(
    list_filename: str = "list_005930_page1.json",
    target: DartDividendTarget = _DEFAULT_TARGET,
) -> tuple[DartCorporateActionAdapter, DartFixtureHandler]:
    handler = DartFixtureHandler(list_filename)
    client = httpx2.AsyncClient(
        base_url="https://dart.example.test",
        transport=httpx2.MockTransport(handler),
        timeout=httpx2.Timeout(5.0),
    )
    return DartCorporateActionAdapter(
        DartHttpClient(client, SecretStr("fixture-dart-key")),
        target,
    ), handler
