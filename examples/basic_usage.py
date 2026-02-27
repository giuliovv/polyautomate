"""Showcases how to collect price history suitable for simulations."""

from datetime import datetime, timedelta, timezone

from polyautomate.clients.trading import PolymarketTradingClient
from polyautomate.data.archive import MarketHistoryExporter
from polyautomate.data.catalog import MarketCatalog
from polyautomate.data.history import PriceHistoryService
from polyautomate.models import OrderRequest


def prepare_ticket_history(condition_id: str, token_id: str) -> None:
    """
    Fetch price history for a single ticket/outcome. This is typically the first step
    when building offline simulations or backtests.
    """
    service = PriceHistoryService()
    history = service.get_price_history(condition_id, token_id, interval="1m")
    print(history.to_dataframe().head())


def example_order(api_key: str, api_secret: str, api_passphrase: str, address: str, token_id: str) -> None:
    trader = PolymarketTradingClient(
        api_key=api_key,
        api_secret=api_secret,
        api_passphrase=api_passphrase,
        address=address,
    )
    expires = datetime.now(tz=timezone.utc) + timedelta(minutes=10)
    order = OrderRequest(
        token_id=token_id,
        side="buy",
        price="0.42",
        size="50",
        expiration=expires,
    )
    ack = trader.place_order(order, post_only=True)
    print("Submitted order", ack.order_id, ack.status)


if __name__ == "__main__":
    catalog = MarketCatalog()
    event = catalog.get_event("when-will-the-government-shutdown-end-545")
    market = event.markets[0]
    condition_id = market.condition_id
    token_id = market.clob_token_ids[0]

    print(f"Preparing history for market {market.question} / token {token_id}")
    prepare_ticket_history(condition_id, token_id)

    exporter = MarketHistoryExporter(output_dir="history")
    summary = exporter.export_search(query="shutdown", closed=False, interval="1m", limit=10)
    print(f"Archived {len(summary.successes)} price files under {exporter.output_dir}; failures: {summary.failed}")

    # Uncomment to place an order once you have credentials.
    # example_order("pm_api_key", "base64_api_secret", "api_passphrase", "0x_wallet_address", token_id)
