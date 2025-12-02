import logging
import unittest
from unittest.mock import MagicMock, patch

from config.settings import SYMBOLS, SYMBOL_TO_COIN
from config import (
    get_effective_symbol_universe,
    get_effective_coin_universe,
    set_symbol_universe,
    clear_symbol_universe_override,
)


class SymbolUniverseTests(unittest.TestCase):
    def tearDown(self) -> None:
        clear_symbol_universe_override()

    def test_default_universe_matches_settings(self) -> None:
        clear_symbol_universe_override()
        self.assertEqual(get_effective_symbol_universe(), list(SYMBOLS))

        expected_coins = []
        seen = set()
        for symbol in SYMBOLS:
            coin = SYMBOL_TO_COIN[symbol]
            if coin in seen:
                continue
            seen.add(coin)
            expected_coins.append(coin)
        self.assertEqual(get_effective_coin_universe(), expected_coins)

    def test_set_symbol_universe_filters_unknown_and_duplicates(self) -> None:
        symbols = ["ethusdt", "ETHUSDT", "UNKNOWNUSDT"]
        set_symbol_universe(symbols)
        universe = get_effective_symbol_universe()
        self.assertEqual(universe, ["ETHUSDT"])

        coins = get_effective_coin_universe()
        self.assertEqual(coins, [SYMBOL_TO_COIN["ETHUSDT"]])

    def test_clear_symbol_universe_override_restores_default(self) -> None:
        set_symbol_universe(["ETHUSDT"])
        self.assertNotEqual(get_effective_symbol_universe(), list(SYMBOLS))
        clear_symbol_universe_override()
        self.assertEqual(get_effective_symbol_universe(), list(SYMBOLS))

    def test_empty_override_results_in_empty_universe(self) -> None:
        """Setting an empty list should result in empty Universe (no trading).
        
        This is intentional safety behavior: an empty or all-invalid override
        should NOT silently fall back to the full default Universe, as that
        could unexpectedly expand trading scope on misconfiguration.
        """
        # Explicit empty list => empty Universe
        set_symbol_universe([])
        self.assertEqual(get_effective_symbol_universe(), [])
        self.assertEqual(get_effective_coin_universe(), [])

        # All-invalid symbols => also empty Universe (not default)
        set_symbol_universe(["INVALIDUSDT", "ALSOINVALID"])
        self.assertEqual(get_effective_symbol_universe(), [])
        self.assertEqual(get_effective_coin_universe(), [])

        # Use clear_symbol_universe_override() to explicitly restore default
        clear_symbol_universe_override()
        self.assertEqual(get_effective_symbol_universe(), list(SYMBOLS))


class UniverseIntegrationContractTests(unittest.TestCase):
    """Contract tests verifying Universe abstraction integration points.
    
    These tests ensure that modules using the Universe abstraction
    correctly respect the configured Universe subset.
    """

    def tearDown(self) -> None:
        clear_symbol_universe_override()

    def test_universe_override_affects_effective_universe(self) -> None:
        """Verify Universe override correctly limits the effective symbol set.
        
        This is a contract test ensuring that when Universe is overridden,
        any code using get_effective_symbol_universe() will only see the
        overridden subset, not the full default SYMBOLS list.
        """
        # Default should have multiple symbols
        default_symbols = get_effective_symbol_universe()
        self.assertGreater(len(default_symbols), 1, "Default should have multiple symbols")

        # Override to single symbol
        set_symbol_universe(["ETHUSDT"])
        
        # Now effective universe should only contain ETHUSDT
        overridden_symbols = get_effective_symbol_universe()
        self.assertEqual(overridden_symbols, ["ETHUSDT"])
        self.assertEqual(len(overridden_symbols), 1)

        # Coin universe should also be limited
        overridden_coins = get_effective_coin_universe()
        self.assertEqual(len(overridden_coins), 1)
        self.assertEqual(overridden_coins[0], SYMBOL_TO_COIN["ETHUSDT"])

    def test_orphaned_position_warning_logged(self) -> None:
        """Verify WARNING is logged when positions exist outside Universe."""
        from execution.executor import TradeExecutor

        # Create executor with a position for "DOGE" which won't be in Universe
        mock_positions = {"DOGE": {"entry_price": 0.1, "size": 100}}
        
        executor = TradeExecutor(
            positions=mock_positions,
            get_balance=lambda: 10000.0,
            set_balance=lambda x: None,
            get_current_time=MagicMock(),
            calculate_unrealized_pnl=lambda c, p: 0.0,
            estimate_exit_fee=lambda pos, price: 0.0,
            record_iteration_message=lambda msg: None,
            log_trade=lambda coin, action, data: None,
            log_ai_decision=lambda coin, signal, reason, conf: None,
            save_state=lambda: None,
            send_telegram_message=MagicMock(),
            escape_markdown=lambda s: s,
            fetch_market_data=lambda s: None,
            hyperliquid_trader=MagicMock(is_live=False),
            get_binance_futures_exchange=lambda: None,
            trading_backend="paper",
            binance_futures_live=False,
            backpack_futures_live=False,
        )

        # Set Universe to only include ETH (DOGE is orphaned)
        set_symbol_universe(["ETHUSDT"])

        with self.assertLogs(level=logging.WARNING) as log_context:
            executor.process_ai_decisions({"ETH": {"signal": "hold"}})
        
        # Verify warning about orphaned position was logged
        warning_messages = [r.message for r in log_context.records]
        self.assertTrue(
            any("DOGE" in msg and "outside current Universe" in msg for msg in warning_messages),
            f"Expected orphaned position warning for DOGE, got: {warning_messages}",
        )
