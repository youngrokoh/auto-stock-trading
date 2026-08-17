import json
from datetime import UTC, date, datetime
from urllib.parse import parse_qs

import anyio
import httpx2
from pydantic import SecretStr

from auto_stock_trading.adapters.disclosures.opendart_disclosures import (
    DartDisclosureAdapter,
)
from auto_stock_trading.adapters.disclosures.opendart_http import (
    DART_LIST_ENDPOINT,
    DartHttpClient,
)
from auto_stock_trading.domain.fundamentals.disclosures import DisclosureType

_NOW = datetime(2026, 8, 17, 9, 0, tzinfo=UTC)


def _entry(rcept_no: str, report_nm: str, rcept_dt: str) -> dict[str, str]:
    return {
        "corp_cls": "Y",
        "corp_name": "삼성전자",
        "corp_code": "00126380",
        "stock_code": "005930",
        "report_nm": report_nm,
        "rcept_no": rcept_no,
        "flr_nm": "삼성전자",
        "rcept_dt": rcept_dt,
        "rm": "",
    }


def _page(entries: list[dict[str, str]], page_no: int, total_page: int) -> str:
    return json.dumps(
        {
            "status": "000",
            "message": "정상",
            "page_no": page_no,
            "page_count": 100,
            "total_count": len(entries) * total_page,
            "total_page": total_page,
            "list": entries,
        },
        ensure_ascii=False,
    )


_NO_DATA = json.dumps({"status": "013", "message": "조회된 데이타가 없습니다."}, ensure_ascii=False)

_PAGES: dict[tuple[str, str], str] = {
    ("A", "1"): _page([_entry("20260310002820", "사업보고서 (2025.12)", "20260310")], 1, 2),
    ("A", "2"): _page([_entry("20260814003699", "반기보고서 (2026.06)", "20260814")], 2, 2),
    ("B", "1"): _NO_DATA,
    ("D", "1"): _page(
        [_entry("20260811000285", "임원ㆍ주요주주특정증권등소유상황보고서", "20260811")], 1, 1
    ),
    ("I", "1"): _page(
        [_entry("20260710000111", "수시공시의무관련사항(공정공시)", "20260710")], 1, 1
    ),
}


class _Handler:
    def __init__(self) -> None:
        self.requests: list[httpx2.Request] = []

    def __call__(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append(request)
        query = parse_qs(request.url.query.decode())
        if request.url.path != DART_LIST_ENDPOINT or not query.get("crtfc_key"):
            return httpx2.Response(404, request=request)
        key = (query["pblntf_ty"][0], query["page_no"][0])
        return httpx2.Response(
            200,
            request=request,
            headers={"Content-Type": "application/json"},
            text=_PAGES[key],
        )


def _adapter() -> tuple[DartDisclosureAdapter, _Handler]:
    handler = _Handler()
    client = httpx2.AsyncClient(
        base_url="https://dart.example.test",
        transport=httpx2.MockTransport(handler),
        timeout=httpx2.Timeout(5.0),
    )
    return DartDisclosureAdapter(
        DartHttpClient(client, SecretStr("fixture-dart-key")),
        symbol="005930",
        corp_code="00126380",
    ), handler


def test_disclosures_are_collected_per_type_with_pagination_and_no_data_skips() -> None:
    async def run() -> None:
        adapter, handler = _adapter()
        try:
            bundle = await adapter.fetch_disclosures(date(2025, 8, 17), date(2026, 8, 17), _NOW)
        finally:
            await adapter.close()

        assert [(entry.rcept_no, entry.disclosure_type) for entry in bundle.disclosures] == [
            ("20260310002820", DisclosureType.PERIODIC),
            ("20260814003699", DisclosureType.PERIODIC),
            ("20260811000285", DisclosureType.OWNERSHIP),
            ("20260710000111", DisclosureType.EXCHANGE),
        ]
        first = bundle.disclosures[0]
        assert first.symbol == "005930"
        assert first.report_nm == "사업보고서 (2025.12)"
        assert first.filer_name == "삼성전자"
        assert first.receipt_date == date(2026, 3, 10)
        assert first.received_at == _NOW
        # 유형 4개 × 페이지: A는 2페이지, 나머지 1페이지씩 = 5회 호출
        assert len(handler.requests) == 5
        assert len(bundle.pages) == 5
        assert all("crtfc_key" not in page.raw.payload_json for page in bundle.pages)
        assert bundle.pages[0].raw.request_fingerprint == (
            "dart:disclosures:00126380:A:20250817:20260817:1"
        )

    anyio.run(run)
