import unittest

from exchange_client import (
    CloseResult,
    EntryResult,
    BinanceFuturesExchangeClient,
)


class _StubBinanceExchange:
    def __init__(self, *, order_response):
        self._order_response = order_response
        self.set_leverage_calls = []
        self.create_order_calls = []

    def set_leverage(self, leverage, symbol):  # noqa: D401
        self.set_leverage_calls.append({"leverage": leverage, "symbol": symbol})

    def create_order(self, symbol, type, side, amount, params):  # noqa: D401, A002
        self.create_order_calls.append(
            {
                "symbol": symbol,
                "type": type,
                "side": side,
                "amount": amount,
                "params": params,
            }
        )
        return self._order_response


class BinanceFuturesExchangeClientTests(unittest.TestCase):
    def test_place_entry_success_maps_oid_and_has_no_errors(self) -> None:
        raw_order = {
            "status": "ok",
            "id": "e-1",
            "info": {"code": "0", "msg": ""},
        }
        stub = _StubBinanceExchange(order_response=raw_order)
        client = BinanceFuturesExchangeClient(exchange=stub)

        result: EntryResult = client.place_entry(
            coin="BTC",
            side="long",
            size=1.0,
            entry_price=100.0,
            stop_loss_price=90.0,
            take_profit_price=110.0,
            leverage=5.0,
            liquidity="taker",
            symbol="BTCUSDT",
        )

        self.assertTrue(result.success)
        self.assertEqual(result.backend, "binance_futures")
        self.assertEqual(result.errors, [])
        self.assertEqual(result.entry_oid, "e-1")
        self.assertIs(result.raw, raw_order)
        self.assertIn("order", result.extra)
        self.assertEqual(result.extra.get("symbol"), "BTCUSDT")

        self.assertEqual(len(stub.set_leverage_calls), 1)
        call = stub.set_leverage_calls[0]
        self.assertEqual(call["symbol"], "BTCUSDT")
        self.assertEqual(call["leverage"], 5)

    def test_place_entry_failure_collects_errors_from_status_and_info(self) -> None:
        raw_order = {
            "status": "rejected",
            "info": {"code": -2019, "msg": "Margin is insufficient."},
        }
        stub = _StubBinanceExchange(order_response=raw_order)
        client = BinanceFuturesExchangeClient(exchange=stub)

        result = client.place_entry(
            coin="ETH",
            side="short",
            size=0.5,
            entry_price=200.0,
            stop_loss_price=210.0,
            take_profit_price=190.0,
            leverage=3.0,
            liquidity="taker",
            symbol="ETHUSDT",
        )

        self.assertFalse(result.success)
        self.assertEqual(result.backend, "binance_futures")
        self.assertTrue(result.errors)
        joined = " ".join(result.errors).lower()
        self.assertIn("margin is insufficient", joined)

    def test_close_position_success_maps_close_oid_and_has_no_errors(self) -> None:
        raw_order = {
            "status": "ok",
            "id": "c-1",
        }
        stub = _StubBinanceExchange(order_response=raw_order)
        client = BinanceFuturesExchangeClient(exchange=stub)

        result: CloseResult = client.close_position(
            coin="BTC",
            side="long",
            size=0.5,
            fallback_price=120.0,
            symbol="BTCUSDT",
        )

        self.assertTrue(result.success)
        self.assertEqual(result.backend, "binance_futures")
        self.assertEqual(result.errors, [])
        self.assertEqual(result.close_oid, "c-1")
        self.assertIs(result.raw, raw_order)
        self.assertIn("order", result.extra)

    def test_close_position_failure_collects_errors(self) -> None:
        raw_order = {
            "status": "error",
            "info": {"code": -1021, "msg": "Timestamp for this request is outside of the recvWindow."},
        }
        stub = _StubBinanceExchange(order_response=raw_order)
        client = BinanceFuturesExchangeClient(exchange=stub)

        result = client.close_position(
            coin="BTC",
            side="short",
            size=1.0,
            fallback_price=None,
            symbol="BTCUSDT",
        )

        self.assertFalse(result.success)
        self.assertEqual(result.backend, "binance_futures")
        self.assertTrue(result.errors)
        joined = " ".join(result.errors).lower()
        self.assertIn("timestamp for this request is outside of the recvwindow", joined)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
