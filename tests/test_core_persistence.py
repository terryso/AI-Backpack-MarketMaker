"""Tests for core/persistence.py module."""
import csv
import json
import tempfile
from pathlib import Path

import pandas as pd
import pytest

from core.persistence import (
    load_equity_history_from_csv,
    init_csv_files_for_paths,
    save_state_to_json,
    load_state_from_json,
    append_portfolio_state_row,
    append_trade_row,
)


class TestLoadEquityHistoryFromCsv:
    """Tests for load_equity_history_from_csv function."""

    def test_loads_equity_values(self, tmp_path):
        """Should load equity values from CSV."""
        csv_path = tmp_path / "state.csv"
        csv_path.write_text("timestamp,total_equity\n2024-01-01,1000\n2024-01-02,1010\n2024-01-03,1020\n")
        
        equity_history = []
        load_equity_history_from_csv(csv_path, equity_history)
        
        assert equity_history == [1000.0, 1010.0, 1020.0]

    def test_clears_existing_history(self, tmp_path):
        """Should clear existing history before loading."""
        csv_path = tmp_path / "state.csv"
        csv_path.write_text("timestamp,total_equity\n2024-01-01,1000\n")
        
        equity_history = [500.0, 600.0]
        load_equity_history_from_csv(csv_path, equity_history)
        
        assert equity_history == [1000.0]

    def test_handles_missing_file(self, tmp_path):
        """Should handle missing CSV file."""
        csv_path = tmp_path / "nonexistent.csv"
        equity_history = [100.0]
        
        load_equity_history_from_csv(csv_path, equity_history)
        
        assert equity_history == []

    def test_handles_missing_column(self, tmp_path):
        """Should handle CSV without total_equity column."""
        csv_path = tmp_path / "state.csv"
        csv_path.write_text("timestamp,balance\n2024-01-01,1000\n")
        
        equity_history = []
        load_equity_history_from_csv(csv_path, equity_history)
        
        assert equity_history == []

    def test_handles_invalid_values(self, tmp_path):
        """Should skip invalid equity values."""
        csv_path = tmp_path / "state.csv"
        csv_path.write_text("timestamp,total_equity\n2024-01-01,1000\n2024-01-02,invalid\n2024-01-03,1020\n")
        
        equity_history = []
        load_equity_history_from_csv(csv_path, equity_history)
        
        assert equity_history == [1000.0, 1020.0]


class TestInitCsvFilesForPaths:
    """Tests for init_csv_files_for_paths function."""

    def test_creates_state_csv(self, tmp_path):
        """Should create state CSV with headers."""
        state_csv = tmp_path / "state.csv"
        trades_csv = tmp_path / "trades.csv"
        decisions_csv = tmp_path / "decisions.csv"
        messages_csv = tmp_path / "messages.csv"
        messages_recent_csv = tmp_path / "messages_recent.csv"
        
        state_columns = ["timestamp", "balance", "equity"]
        
        init_csv_files_for_paths(
            state_csv, trades_csv, decisions_csv, messages_csv, messages_recent_csv,
            state_columns,
        )
        
        assert state_csv.exists()
        df = pd.read_csv(state_csv)
        assert list(df.columns) == state_columns

    def test_creates_trades_csv(self, tmp_path):
        """Should create trades CSV with headers."""
        state_csv = tmp_path / "state.csv"
        trades_csv = tmp_path / "trades.csv"
        decisions_csv = tmp_path / "decisions.csv"
        messages_csv = tmp_path / "messages.csv"
        messages_recent_csv = tmp_path / "messages_recent.csv"
        
        init_csv_files_for_paths(
            state_csv, trades_csv, decisions_csv, messages_csv, messages_recent_csv,
            ["timestamp"],
        )
        
        assert trades_csv.exists()
        df = pd.read_csv(trades_csv)
        assert "timestamp" in df.columns
        assert "coin" in df.columns
        assert "action" in df.columns

    def test_creates_decisions_csv(self, tmp_path):
        """Should create decisions CSV with headers."""
        state_csv = tmp_path / "state.csv"
        trades_csv = tmp_path / "trades.csv"
        decisions_csv = tmp_path / "decisions.csv"
        messages_csv = tmp_path / "messages.csv"
        messages_recent_csv = tmp_path / "messages_recent.csv"
        
        init_csv_files_for_paths(
            state_csv, trades_csv, decisions_csv, messages_csv, messages_recent_csv,
            ["timestamp"],
        )
        
        assert decisions_csv.exists()
        df = pd.read_csv(decisions_csv)
        assert "timestamp" in df.columns
        assert "signal" in df.columns

    def test_does_not_overwrite_existing(self, tmp_path):
        """Should not overwrite existing files with data."""
        trades_csv = tmp_path / "trades.csv"
        trades_csv.write_text("timestamp,coin,action,side,quantity,price,profit_target,stop_loss,leverage,confidence,pnl,balance_after,reason\n2024-01-01,BTC,entry,long,1,50000,52000,49000,10,0.8,0,10000,test\n")
        
        state_csv = tmp_path / "state.csv"
        decisions_csv = tmp_path / "decisions.csv"
        messages_csv = tmp_path / "messages.csv"
        messages_recent_csv = tmp_path / "messages_recent.csv"
        
        init_csv_files_for_paths(
            state_csv, trades_csv, decisions_csv, messages_csv, messages_recent_csv,
            ["timestamp"],
        )
        
        df = pd.read_csv(trades_csv)
        assert len(df) == 1


class TestSaveStateToJson:
    """Tests for save_state_to_json function."""

    def test_saves_payload(self, tmp_path):
        """Should save payload to JSON file."""
        json_path = tmp_path / "state.json"
        payload = {"balance": 10000, "positions": {"BTC": {"side": "long"}}}
        
        save_state_to_json(json_path, payload)
        
        with open(json_path) as f:
            loaded = json.load(f)
        assert loaded == payload

    def test_overwrites_existing(self, tmp_path):
        """Should overwrite existing file."""
        json_path = tmp_path / "state.json"
        json_path.write_text('{"old": "data"}')
        
        save_state_to_json(json_path, {"new": "data"})
        
        with open(json_path) as f:
            loaded = json.load(f)
        assert loaded == {"new": "data"}

    def test_atomic_write_preserves_original_on_error(self, tmp_path, monkeypatch):
        """Should keep original file intact if write fails."""
        json_path = tmp_path / "state.json"
        original = {"balance": 100, "positions": {"BTC": {"side": "long"}}}
        json_path.write_text(json.dumps(original))

        def failing_dump(*args, **kwargs):  # pragma: no cover - behaviour verified via state
            raise RuntimeError("json dump failed")

        monkeypatch.setattr("core.persistence.json.dump", failing_dump)

        save_state_to_json(json_path, {"balance": 200})

        with open(json_path) as f:
            loaded = json.load(f)

        assert loaded == original
        assert not json_path.with_suffix(".tmp").exists()


class TestLoadStateFromJson:
    """Tests for load_state_from_json function."""

    def test_loads_balance(self, tmp_path):
        """Should load balance from JSON."""
        json_path = tmp_path / "state.json"
        json_path.write_text('{"balance": 15000}')
        
        balance, positions, iteration = load_state_from_json(json_path, 10000, 0.0005)
        
        assert balance == 15000.0

    def test_uses_default_balance(self, tmp_path):
        """Should use start_capital if balance missing."""
        json_path = tmp_path / "state.json"
        json_path.write_text('{}')
        
        balance, positions, iteration = load_state_from_json(json_path, 10000, 0.0005)
        
        assert balance == 10000.0

    def test_loads_positions(self, tmp_path):
        """Should load and normalize positions."""
        json_path = tmp_path / "state.json"
        json_path.write_text(json.dumps({
            "balance": 10000,
            "positions": {
                "BTC": {
                    "side": "long",
                    "quantity": 0.1,
                    "entry_price": 50000,
                    "profit_target": 52000,
                    "stop_loss": 49000,
                    "leverage": 10,
                }
            }
        }))
        
        balance, positions, iteration = load_state_from_json(json_path, 10000, 0.0005)
        
        assert "BTC" in positions
        assert positions["BTC"]["side"] == "long"
        assert positions["BTC"]["quantity"] == 0.1
        assert positions["BTC"]["entry_price"] == 50000

    def test_loads_iteration_counter(self, tmp_path):
        """Should load iteration counter."""
        json_path = tmp_path / "state.json"
        json_path.write_text('{"iteration": 42}')
        
        balance, positions, iteration = load_state_from_json(json_path, 10000, 0.0005)
        
        assert iteration == 42

    def test_normalizes_fees(self, tmp_path):
        """Should normalize fee fields."""
        json_path = tmp_path / "state.json"
        json_path.write_text(json.dumps({
            "positions": {
                "BTC": {
                    "side": "long",
                    "quantity": 0.1,
                    "entry_price": 50000,
                    "entry_fee": 2.5,  # Old field name
                }
            }
        }))
        
        balance, positions, iteration = load_state_from_json(json_path, 10000, 0.0005)
        
        assert positions["BTC"]["fees_paid"] == 2.5


class TestAppendPortfolioStateRow:
    """Tests for append_portfolio_state_row function."""

    def test_appends_row(self, tmp_path):
        """Should append a row to the CSV."""
        csv_path = tmp_path / "state.csv"
        csv_path.write_text("timestamp,balance,equity,return,positions,details,margin,unrealized,btc\n")
        
        append_portfolio_state_row(
            csv_path,
            "2024-01-01T00:00:00",
            "10000.00",
            "10500.00",
            "5.00",
            1,
            "BTC:long:0.1@50000",
            "500.00",
            "0.00",
            "50000.00",
        )
        
        df = pd.read_csv(csv_path)
        assert len(df) == 1
        assert df.iloc[0]["timestamp"] == "2024-01-01T00:00:00"


class TestAppendTradeRow:
    """Tests for append_trade_row function."""

    def test_appends_row(self, tmp_path):
        """Should append a trade row to the CSV."""
        csv_path = tmp_path / "trades.csv"
        csv_path.write_text("timestamp,coin,action,side,quantity,price,profit_target,stop_loss,leverage,confidence,pnl,balance_after,reason\n")
        
        append_trade_row(
            csv_path,
            "2024-01-01T00:00:00",
            "BTC",
            "entry",
            "long",
            0.1,
            50000,
            52000,
            49000,
            10,
            0.85,
            0,
            10000,
            "Bullish signal",
        )
        
        df = pd.read_csv(csv_path)
        assert len(df) == 1
        assert df.iloc[0]["coin"] == "BTC"
        assert df.iloc[0]["action"] == "entry"
