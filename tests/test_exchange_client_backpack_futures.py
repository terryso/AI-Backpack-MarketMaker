import unittest

from exchange.base import CloseResult, EntryResult
from exchange.backpack import BackpackFuturesExchangeClient


# Example keys taken from Backpack official Python API guide.
_DUMMY_PUBLIC_KEY = "5+yQgwU0ZdJ/9s+GXfuPFfo7yQQpl9CgvQedJXne30o="
_DUMMY_SECRET_SEED = "TDSkv44jf/iD/QCKkyCdixO+p1sfLXxk+PZH7mW/ams="


def _make_client() -> BackpackFuturesExchangeClient:
    return BackpackFuturesExchangeClient(
        api_public_key=_DUMMY_PUBLIC_KEY,
        api_secret_seed=_DUMMY_SECRET_SEED,
        base_url="https://api.backpack.exchange",
        window_ms=5000,
    )


class BackpackFuturesExchangeClientTests(unittest.TestCase):
    def test_place_entry_success_maps_oid_and_has_no_errors(self) -> None:
        raw_order = {
            "orderType": "Market",
            "id": "e-1",
            "status": "Filled",
            "symbol": "BTC_USDC_PERP",
            "side": "Bid",
            "quantity": "0.001",
            "quoteQuantity": "27.4",
            "reduceOnly": False,
        }
        client = _make_client()
        client._post_order = lambda body, raw=raw_order: raw  # type: ignore[assignment]

        result: EntryResult = client.place_entry(
            coin="BTC",
            side="long",
            size=0.001,
            entry_price=None,
            stop_loss_price=None,
            take_profit_price=None,
            leverage=1.0,
            liquidity="taker",
        )

        self.assertTrue(result.success)
        self.assertEqual(result.backend, "backpack_futures")
        self.assertEqual(result.errors, [])
        self.assertEqual(result.entry_oid, "e-1")
        self.assertIs(result.raw, raw_order)
        self.assertIn("order", result.extra)
        self.assertEqual(result.extra.get("symbol"), "BTC_USDC_PERP")
        self.assertEqual(result.extra.get("side"), "Bid")

    def test_place_entry_failure_collects_errors_from_status_and_message(self) -> None:
        raw_order = {
            "status": "error",
            "message": "Invalid quantity",
        }
        client = _make_client()
        client._post_order = lambda body, raw=raw_order: raw  # type: ignore[assignment]

        result = client.place_entry(
            coin="ETH",
            side="short",
            size=0.5,
            entry_price=None,
            stop_loss_price=None,
            take_profit_price=None,
            leverage=2.0,
            liquidity="taker",
        )

        self.assertFalse(result.success)
        self.assertEqual(result.backend, "backpack_futures")
        self.assertTrue(result.errors)
        joined = " ".join(result.errors).lower()
        self.assertIn("invalid quantity", joined)

    def test_close_position_success_maps_close_oid_and_has_no_errors(self) -> None:
        raw_order = {
            "orderType": "Market",
            "id": "c-1",
            "status": "Filled",
            "symbol": "BTC_USDC_PERP",
            "side": "Ask",
            "quantity": "0.001",
            "quoteQuantity": "27.4",
            "reduceOnly": True,
        }
        client = _make_client()
        client._post_order = lambda body, raw=raw_order: raw  # type: ignore[assignment]

        result: CloseResult = client.close_position(
            coin="BTC",
            side="long",
            size=0.001,
            fallback_price=None,
        )

        self.assertTrue(result.success)
        self.assertEqual(result.backend, "backpack_futures")
        self.assertEqual(result.errors, [])
        self.assertEqual(result.close_oid, "c-1")
        self.assertIs(result.raw, raw_order)
        self.assertIn("order", result.extra)
        self.assertEqual(result.extra.get("symbol"), "BTC_USDC_PERP")

    def test_close_position_zero_size_short_circuits_without_errors(self) -> None:
        client = _make_client()

        result = client.close_position(
            coin="BTC",
            side="long",
            size=0.0,
            fallback_price=None,
        )

        self.assertTrue(result.success)
        self.assertEqual(result.backend, "backpack_futures")
        self.assertEqual(result.errors, [])
        self.assertIsNone(result.close_oid)
        self.assertIsNone(result.raw)
        self.assertEqual(result.extra.get("reason"), "no position size to close")

    def test_close_position_failure_collects_errors_from_status_and_message(self) -> None:
        raw_order = {
            "status": "rejected",
            "error": "insufficient margin",
        }
        client = _make_client()
        client._post_order = lambda body, raw=raw_order: raw  # type: ignore[assignment]

        result = client.close_position(
            coin="BTC",
            side="short",
            size=1.0,
            fallback_price=None,
        )

        self.assertFalse(result.success)
        self.assertEqual(result.backend, "backpack_futures")
        self.assertTrue(result.errors)
        joined = " ".join(result.errors).lower()
        self.assertIn("insufficient margin", joined)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
