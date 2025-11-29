import unittest

from exchange.base import CloseResult, EntryResult
from exchange.hyperliquid import HyperliquidExchangeClient


class _StubHyperliquidTradingClient:
    """Minimal stub for HyperliquidTradingClient used in unit tests.

    It only needs to expose the methods invoked by HyperliquidExchangeClient.
    """

    def __init__(self, *, place_response, close_response):
        self._place_response = place_response
        self._close_response = close_response
        self.place_calls = []
        self.close_calls = []

    def place_entry_with_sl_tp(
        self,
        *,
        coin,
        side,
        size,
        entry_price,
        stop_loss_price,
        take_profit_price,
        leverage,
        liquidity,
    ):
        self.place_calls.append(
            {
                "coin": coin,
                "side": side,
                "size": size,
                "entry_price": entry_price,
                "stop_loss_price": stop_loss_price,
                "take_profit_price": take_profit_price,
                "leverage": leverage,
                "liquidity": liquidity,
            }
        )
        return self._place_response

    def close_position(self, *, coin, side, size=None, fallback_price=None):
        self.close_calls.append(
            {
                "coin": coin,
                "side": side,
                "size": size,
                "fallback_price": fallback_price,
            }
        )
        return self._close_response


class HyperliquidExchangeClientTests(unittest.TestCase):
    def test_place_entry_success_maps_oids_and_has_no_errors(self) -> None:
        raw_place = {
            "success": True,
            "entry_result": {
                "status": "ok",
                "response": {
                    "data": {
                        "statuses": [
                            {"status": "filled"},
                        ],
                    }
                },
            },
            "stop_loss_result": {"status": "ok"},
            "take_profit_result": {"status": "ok"},
            "entry_oid": "e-1",
            "stop_loss_oid": "sl-1",
            "take_profit_oid": "tp-1",
        }
        stub = _StubHyperliquidTradingClient(place_response=raw_place, close_response={})
        client = HyperliquidExchangeClient(trader=stub)

        result: EntryResult = client.place_entry(
            coin="BTC",
            side="long",
            size=1.0,
            entry_price=100.0,
            stop_loss_price=90.0,
            take_profit_price=110.0,
            leverage=1.0,
            liquidity="taker",
        )

        self.assertTrue(result.success)
        self.assertEqual(result.backend, "hyperliquid")
        self.assertEqual(result.errors, [])
        self.assertEqual(result.entry_oid, "e-1")
        self.assertEqual(result.sl_oid, "sl-1")
        self.assertEqual(result.tp_oid, "tp-1")
        self.assertIs(result.raw, raw_place)
        self.assertIn("entry_result", result.extra)
        self.assertIn("stop_loss_result", result.extra)
        self.assertIn("take_profit_result", result.extra)

        # Ensure we delegated to the underlying trader with expected arguments.
        self.assertEqual(len(stub.place_calls), 1)
        call = stub.place_calls[0]
        self.assertEqual(call["coin"], "BTC")
        self.assertEqual(call["side"], "long")
        self.assertEqual(call["size"], 1.0)
        self.assertEqual(call["entry_price"], 100.0)
        self.assertEqual(call["stop_loss_price"], 90.0)
        self.assertEqual(call["take_profit_price"], 110.0)
        self.assertEqual(call["leverage"], 1.0)
        self.assertEqual(call["liquidity"], "taker")

    def test_place_entry_failure_collects_errors_from_statuses(self) -> None:
        raw_place = {
            "success": False,
            "entry_result": {
                "status": "error",
                "response": {
                    "data": {
                        "statuses": [
                            {"error": "insufficient margin"},
                        ],
                    }
                },
            },
        }
        stub = _StubHyperliquidTradingClient(place_response=raw_place, close_response={})
        client = HyperliquidExchangeClient(trader=stub)

        result = client.place_entry(
            coin="BTC",
            side="long",
            size=1.0,
            entry_price=100.0,
            stop_loss_price=None,
            take_profit_price=None,
            leverage=1.0,
            liquidity="taker",
        )

        self.assertFalse(result.success)
        self.assertEqual(result.backend, "hyperliquid")
        self.assertTrue(result.errors)
        joined = " ".join(result.errors).lower()
        self.assertIn("insufficient margin", joined)

    def test_close_position_success_maps_close_oid_and_has_no_errors(self) -> None:
        raw_close = {
            "success": True,
            "close_result": {"status": "ok"},
            "close_oid": "c-1",
        }
        stub = _StubHyperliquidTradingClient(place_response={}, close_response=raw_close)
        client = HyperliquidExchangeClient(trader=stub)

        result: CloseResult = client.close_position(
            coin="BTC",
            side="long",
            size=0.5,
            fallback_price=120.0,
        )

        self.assertTrue(result.success)
        self.assertEqual(result.backend, "hyperliquid")
        self.assertEqual(result.errors, [])
        self.assertEqual(result.close_oid, "c-1")
        self.assertIs(result.raw, raw_close)
        self.assertIn("close_result", result.extra)

        self.assertEqual(len(stub.close_calls), 1)
        call = stub.close_calls[0]
        self.assertEqual(call["coin"], "BTC")
        self.assertEqual(call["side"], "long")
        self.assertEqual(call["size"], 0.5)
        self.assertEqual(call["fallback_price"], 120.0)

    def test_close_position_failure_collects_errors(self) -> None:
        raw_close = {
            "success": False,
            "close_result": {
                "status": "error",
                "response": {
                    "data": {
                        "statuses": [
                            {"error": "order rejected"},
                        ],
                    }
                },
            },
        }
        stub = _StubHyperliquidTradingClient(place_response={}, close_response=raw_close)
        client = HyperliquidExchangeClient(trader=stub)

        result = client.close_position(
            coin="BTC",
            side="short",
            size=None,
            fallback_price=None,
        )

        self.assertFalse(result.success)
        self.assertEqual(result.backend, "hyperliquid")
        self.assertTrue(result.errors)
        joined = " ".join(result.errors).lower()
        self.assertIn("order rejected", joined)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
