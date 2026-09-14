"""Turn eBay Browse API payloads into neutral marketplace listings."""

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from euro2core.domain.enums import ObservationKind

MARKETPLACES: dict[str, str] = {
    "EBAY_ES": "es",
    "EBAY_DE": "de",
    "EBAY_FR": "fr",
    "EBAY_IT": "it",
    "EBAY_NL": "nl",
    "EBAY_AT": "at",
}


@dataclass(frozen=True)
class Listing:
    listing_id: str
    marketplace: str
    title: str
    price: Decimal
    currency: str
    kind: ObservationKind
    url: str
    observed_at: datetime
    end_date: datetime | None
    condition: str | None
    bid_count: int = 0


def listing_from_summary(
    summary: dict[str, Any], marketplace: str, observed_at: datetime | None = None
) -> Listing | None:
    """Map an ItemSummary (item_summary/search) to a Listing; None when there is no usable price."""
    options = set(summary.get("buyingOptions") or [])
    if "FIXED_PRICE" in options and summary.get("price"):
        price, kind = summary["price"], ObservationKind.ASKING
    elif "AUCTION" in options and summary.get("currentBidPrice"):
        price, kind = summary["currentBidPrice"], ObservationKind.AUCTION_OPEN
    else:
        return None
    if price.get("currency") != "EUR":
        return None
    return Listing(
        listing_id=summary["itemId"],
        marketplace=marketplace,
        title=summary.get("title", ""),
        price=Decimal(str(price["value"])),
        currency="EUR",
        kind=kind,
        url=summary.get("itemWebUrl", ""),
        observed_at=observed_at or datetime.now(UTC),
        end_date=_parse_date(summary.get("itemEndDate")),
        condition=summary.get("condition"),
        bid_count=int(summary.get("bidCount") or 0),
    )


def closed_auction_from_item(
    item: dict[str, Any], marketplace: str, observed_at: datetime | None = None
) -> Listing | None:
    """Map an ended auction (item/{id}) with bids to a realized sale; None if unsold or live."""
    end = _parse_date(item.get("itemEndDate"))
    now = observed_at or datetime.now(UTC)
    if end is None or end > now:
        return None
    bids = int(item.get("bidCount") or 0)
    price = item.get("currentBidPrice")
    if bids <= 0 or not price or price.get("currency") != "EUR":
        return None
    return Listing(
        listing_id=item["itemId"],
        marketplace=marketplace,
        title=item.get("title", ""),
        price=Decimal(str(price["value"])),
        currency="EUR",
        kind=ObservationKind.AUCTION_CLOSED,
        url=item.get("itemWebUrl", ""),
        observed_at=end,
        end_date=end,
        condition=item.get("condition"),
        bid_count=bids,
    )


def _parse_date(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))
