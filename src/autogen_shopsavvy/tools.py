"""ShopSavvy tools for Microsoft AutoGen agents."""

import asyncio
from typing import Any, Callable, Optional, TypeVar

from autogen_core import CancellationToken
from autogen_core.tools import BaseTool
from pydantic import BaseModel, Field
from shopsavvy import ShopSavvyConfig, ShopSavvyDataAPI

T = TypeVar("T")


async def _run_blocking(
    cancellation_token: CancellationToken, fn: Callable[..., T], *args: Any, **kwargs: Any
) -> T:
    """Run a blocking SDK call off the event loop, honouring the cancellation token.

    The ShopSavvy SDK is synchronous (httpx.Client). Calling it directly from
    an async tool's run() blocked the agent runtime's event loop for the whole
    HTTP round trip, stalling every other agent and tool running concurrently.
    """
    future = asyncio.ensure_future(asyncio.to_thread(fn, *args, **kwargs))
    cancellation_token.link_future(future)
    return await future


class ProductSearchInput(BaseModel):
    """Input for product search."""

    query: str = Field(
        description="Search query (product name, keyword, barcode, ASIN, URL, or model number)"
    )
    limit: int = Field(default=10, description="Maximum number of results to return")


class ProductSearchOutput(BaseModel):
    """Output from product search."""

    products: list[dict[str, Any]] = Field(description="List of matching products")
    total: int = Field(description="Total number of results available")


class ProductSearchTool(BaseTool[ProductSearchInput, ProductSearchOutput]):
    """Search for products by keyword, barcode, ASIN, URL, or model number.

    Returns product details including title, brand, category, images, and identifiers.
    """

    def __init__(self, api_key: str) -> None:
        super().__init__(
            args_type=ProductSearchInput,
            return_type=ProductSearchOutput,
            name="search_products",
            description=(
                "Search for products by keyword, barcode, ASIN, URL, or model number. "
                "Returns product details including title, brand, category, and identifiers."
            ),
        )
        self._client = ShopSavvyDataAPI(ShopSavvyConfig(api_key=api_key))

    async def run(
        self, args: ProductSearchInput, cancellation_token: CancellationToken
    ) -> ProductSearchOutput:
        result = await _run_blocking(
            cancellation_token, self._client.search_products, args.query, limit=args.limit
        )
        products = []
        for p in result.data:
            products.append(
                {
                    "title": p.title,
                    "brand": getattr(p, "brand", None),
                    "category": getattr(p, "category", None),
                    "barcode": getattr(p, "barcode", None),
                    "asin": getattr(p, "amazon", None),
                    "shopsavvy_id": p.shopsavvy,
                    "images": getattr(p, "images", None),
                }
            )
        return ProductSearchOutput(products=products, total=result.pagination.total)


class PriceComparisonInput(BaseModel):
    """Input for price comparison."""

    identifier: str = Field(
        description="Product identifier (barcode, ASIN, URL, model number, or ShopSavvy ID)"
    )
    retailer: Optional[str] = Field(
        default=None, description="Filter offers to a specific retailer"
    )
    include_history: bool = Field(
        default=False, description="Whether to include price history"
    )
    history_start: Optional[str] = Field(
        default=None, description="Price history start date (YYYY-MM-DD)"
    )
    history_end: Optional[str] = Field(
        default=None, description="Price history end date (YYYY-MM-DD)"
    )


class PriceComparisonOutput(BaseModel):
    """Output from price comparison."""

    product_title: Optional[str] = Field(description="Product title")
    offers: list[dict[str, Any]] = Field(description="Current offers from retailers")
    history: Optional[list[dict[str, Any]]] = Field(
        default=None, description="Price history entries"
    )


class PriceComparisonTool(BaseTool[PriceComparisonInput, PriceComparisonOutput]):
    """Get current offers and optionally price history for a product.

    Returns pricing from retailers sorted by price, with optional historical price data.
    """

    def __init__(self, api_key: str) -> None:
        super().__init__(
            args_type=PriceComparisonInput,
            return_type=PriceComparisonOutput,
            name="compare_prices",
            description=(
                "Get current offers from retailers for a product, optionally with price history. "
                "Accepts barcode, ASIN, URL, model number, or ShopSavvy ID."
            ),
        )
        self._client = ShopSavvyDataAPI(ShopSavvyConfig(api_key=api_key))

    async def run(
        self, args: PriceComparisonInput, cancellation_token: CancellationToken
    ) -> PriceComparisonOutput:
        if args.include_history and not (args.history_start and args.history_end):
            # Previously this silently returned history=None, which an agent
            # cannot distinguish from "no history exists".
            raise ValueError(
                "include_history requires both history_start and history_end (YYYY-MM-DD)"
            )

        result = await _run_blocking(
            cancellation_token,
            self._client.get_current_offers,
            args.identifier,
            retailer=args.retailer,
        )

        product_title = None
        offers = []

        if result.data:
            product = result.data[0]
            product_title = product.title
            # Cheapest first (offers without a price last), as the tool
            # description promises.
            sorted_offers = sorted(
                product.offers,
                key=lambda o: (o.price is None, o.price if o.price is not None else 0.0),
            )
            for o in sorted_offers:
                offers.append(
                    {
                        "retailer": getattr(o, "retailer", None),
                        "price": getattr(o, "price", None),
                        "currency": getattr(o, "currency", None),
                        "availability": getattr(o, "availability", None),
                        "url": getattr(o, "URL", None),
                        "condition": getattr(o, "condition", None),
                    }
                )

        history = None
        if args.include_history:
            history_result = await _run_blocking(
                cancellation_token,
                self._client.get_price_history,
                args.identifier,
                args.history_start,
                args.history_end,
                retailer=args.retailer,
            )
            history = []
            for entry in history_result.data:
                for h in getattr(entry, "price_history", []):
                    history.append(
                        {
                            "date": h.get("date") if isinstance(h, dict) else getattr(h, "date", None),
                            "price": h.get("price") if isinstance(h, dict) else getattr(h, "price", None),
                            "availability": h.get("availability") if isinstance(h, dict) else getattr(h, "availability", None),
                        }
                    )

        return PriceComparisonOutput(
            product_title=product_title,
            offers=offers,
            history=history,
        )
