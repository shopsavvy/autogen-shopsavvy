"""
Tests for autogen-shopsavvy.

The real shopsavvy SDK client runs end to end; only its network transport
is replaced by an httpx.MockTransport serving the documented Data API
response shapes (https://shopsavvy.com/data/documentation).
"""

import asyncio
import time
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from autogen_core import CancellationToken

from autogen_shopsavvy import PriceComparisonTool, ProductSearchTool

API_KEY = "ss_test_unit_tests"

PRODUCT = {
    "title": "Sony WH-1000XM5 Wireless Headphones",
    "brand": "Sony",
    "category": "Electronics > Headphones",
    "shopsavvy": "abc123",
    "barcode": "027242923232",
    "amazon": "B09XS7JWHH",
    "images": ["https://example.com/xm5.jpg"],
}


def _offer(offer_id, retailer, price, url):
    return {
        "id": offer_id,
        "retailer": retailer,
        "price": price,
        "currency": "USD",
        "availability": "in",
        "condition": "new",
        "URL": url,
        "timestamp": "2026-09-01T00:00:00Z",
    }


OFFERS = [
    _offer("o1", "Best Buy", 329.99, "https://www.bestbuy.com/xm5"),
    _offer("o2", "Amazon", 298.0, "https://www.amazon.com/dp/B09XS7JWHH"),
    {"id": "o3", "retailer": "eBay", "price": None, "URL": "https://www.ebay.com/itm/1"},
]

RESPONSES = {
    "/v1/products/search": {
        "success": True,
        "data": [PRODUCT],
        "pagination": {"total": 42, "limit": 5, "offset": 0, "returned": 1},
    },
    "/v1/products/offers": {"success": True, "data": [dict(PRODUCT, offers=OFFERS)]},
    "/v1/products/offers/history": {
        "success": True,
        "data": [
            dict(
                PRODUCT,
                offers=[
                    # Exact wire shape: newest point first; `availability` is
                    # omitted when unknown; `currency` is null on an archived
                    # point with no recorded currency.
                    dict(
                        OFFERS[1],
                        history=[
                            {"availability": "in", "price": 298.0, "currency": "USD", "timestamp": "2026-08-15T00:00:00Z"},
                            {"availability": "out", "price": 348.0, "currency": "USD", "timestamp": "2026-08-01T00:00:00Z"},
                            {"price": 349.99, "currency": None, "timestamp": "2026-07-20T00:00:00Z"},
                        ],
                    ),
                    dict(OFFERS[0], history=[]),
                ],
            )
        ],
        "meta": {"request_id": "req-7f3c9a", "credits_used": 2, "credits_remaining": 998, "rate_limit_remaining": 999},
    },
}


class Recorder:
    def __init__(self, delay=0.0):
        self.requests = []
        self.delay = delay

    def __call__(self, request):
        if self.delay:
            time.sleep(self.delay)
        self.requests.append(request)
        body = RESPONSES.get(request.url.path)
        if body is None:
            return httpx.Response(404, json={"success": False, "error": "no such route"})
        return httpx.Response(200, json=body)

    def params(self, index=-1):
        request = self.requests[index]
        return request.url.path, {k: v[0] for k, v in parse_qs(urlsplit(str(request.url)).query).items()}


def _wire(tool, recorder):
    sdk = tool._client
    sdk._client = httpx.Client(
        base_url=sdk.config.base_url,
        headers=dict(sdk._client.headers),
        transport=httpx.MockTransport(recorder),
    )
    return tool


@pytest.fixture
def recorder():
    return Recorder()


# ---------------------------------------------------------------------------
# Construction and schema
# ---------------------------------------------------------------------------

def test_tools_build_real_sdk_clients():
    search = ProductSearchTool(api_key=API_KEY)
    compare = PriceComparisonTool(api_key=API_KEY)

    assert search._client._client.headers["Authorization"] == f"Bearer {API_KEY}"
    assert compare._client.config.api_key == API_KEY


def test_invalid_api_key_is_rejected_by_sdk_config():
    with pytest.raises(ValueError):
        ProductSearchTool(api_key="not-a-shopsavvy-key")


def test_tool_schemas_expose_names_and_parameters():
    search_schema = ProductSearchTool(api_key=API_KEY).schema
    compare_schema = PriceComparisonTool(api_key=API_KEY).schema

    assert search_schema["name"] == "search_products"
    assert set(search_schema["parameters"]["properties"]) == {"query", "limit"}
    assert search_schema["parameters"]["required"] == ["query"]
    assert compare_schema["name"] == "compare_prices"
    assert "identifier" in compare_schema["parameters"]["required"]


# ---------------------------------------------------------------------------
# ProductSearchTool
# ---------------------------------------------------------------------------

async def test_search_returns_products_and_total(recorder):
    tool = _wire(ProductSearchTool(api_key=API_KEY), recorder)

    result = await tool.run_json({"query": "sony headphones", "limit": 5}, CancellationToken())

    assert result.total == 42
    assert result.products == [
        {
            "title": PRODUCT["title"],
            "brand": "Sony",
            "category": "Electronics > Headphones",
            "barcode": "027242923232",
            "asin": "B09XS7JWHH",
            "shopsavvy_id": "abc123",
            "images": ["https://example.com/xm5.jpg"],
        }
    ]
    assert recorder.params() == ("/v1/products/search", {"q": "sony headphones", "limit": "5"})
    assert "Sony WH-1000XM5" in tool.return_value_as_string(result)


async def test_search_does_not_block_the_event_loop():
    recorder = Recorder(delay=0.3)
    tool = _wire(ProductSearchTool(api_key=API_KEY), recorder)
    ticks = 0

    async def ticker():
        nonlocal ticks
        while True:
            await asyncio.sleep(0.01)
            ticks += 1

    ticker_task = asyncio.create_task(ticker())
    await tool.run_json({"query": "x"}, CancellationToken())
    ticker_task.cancel()

    # With a blocking call the ticker cannot run at all during the 0.3s request.
    assert ticks >= 10


async def test_search_honours_cancellation():
    recorder = Recorder(delay=0.5)
    tool = _wire(ProductSearchTool(api_key=API_KEY), recorder)
    token = CancellationToken()

    task = asyncio.create_task(tool.run_json({"query": "x"}, token))
    await asyncio.sleep(0.05)
    token.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task


# ---------------------------------------------------------------------------
# PriceComparisonTool
# ---------------------------------------------------------------------------

async def test_compare_prices_sorted_cheapest_first(recorder):
    tool = _wire(PriceComparisonTool(api_key=API_KEY), recorder)

    result = await tool.run_json({"identifier": "B09XS7JWHH"}, CancellationToken())

    assert result.product_title == PRODUCT["title"]
    assert [o["retailer"] for o in result.offers] == ["Amazon", "Best Buy", "eBay"]
    assert result.offers[0] == {
        "retailer": "Amazon",
        "price": 298.0,
        "currency": "USD",
        "availability": "in",
        "url": "https://www.amazon.com/dp/B09XS7JWHH",
        "condition": "new",
    }
    assert result.history is None
    assert recorder.params() == ("/v1/products/offers", {"ids": "B09XS7JWHH"})


async def test_compare_prices_passes_retailer_filter(recorder):
    tool = _wire(PriceComparisonTool(api_key=API_KEY), recorder)

    await tool.run_json({"identifier": "B09XS7JWHH", "retailer": "amazon.com"}, CancellationToken())

    assert recorder.params() == ("/v1/products/offers", {"ids": "B09XS7JWHH", "retailer": "amazon.com"})


async def test_compare_prices_history_requires_both_dates(recorder):
    tool = _wire(PriceComparisonTool(api_key=API_KEY), recorder)

    with pytest.raises(ValueError, match="history_start and history_end"):
        await tool.run_json(
            {"identifier": "B09XS7JWHH", "include_history": True, "history_start": "2026-08-01"},
            CancellationToken(),
        )
    assert recorder.requests == []


async def test_compare_prices_with_history(recorder):
    tool = _wire(PriceComparisonTool(api_key=API_KEY), recorder)

    result = await tool.run_json(
        {
            "identifier": "B09XS7JWHH",
            "include_history": True,
            "history_start": "2026-08-01",
            "history_end": "2026-08-31",
        },
        CancellationToken(),
    )

    assert result.history == [
        {
            "retailer": "Amazon",
            "condition": "new",
            "timestamp": "2026-08-15T00:00:00Z",
            "price": 298.0,
            "currency": "USD",
            "availability": "in",
        },
        {
            "retailer": "Amazon",
            "condition": "new",
            "timestamp": "2026-08-01T00:00:00Z",
            "price": 348.0,
            "currency": "USD",
            "availability": "out",
        },
        {
            "retailer": "Amazon",
            "condition": "new",
            "timestamp": "2026-07-20T00:00:00Z",
            "price": 349.99,
            "currency": None,
            "availability": None,
        },
    ]
    # Current offers are still fetched first, then the history.
    assert [r.url.path for r in recorder.requests] == ["/v1/products/offers", "/v1/products/offers/history"]
    path, params = recorder.params()
    assert path == "/v1/products/offers/history"
    assert params == {"ids": "B09XS7JWHH", "start": "2026-08-01", "end": "2026-08-31"}
