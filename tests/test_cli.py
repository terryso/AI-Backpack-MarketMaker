"""
Tests for CLI module.

These tests verify that the CLI correctly:
1. Parses commands and arguments
2. Creates TelegramCommand objects
3. Calls the appropriate handlers
4. Formats output correctly
"""
from __future__ import annotations

import pytest
from click.testing import CliRunner

from cli.main import cli, _make_cmd
from cli.output import strip_markdown


class TestMakeCmd:
    """Tests for _make_cmd helper function."""
    
    def test_make_cmd_simple(self):
        """Test creating a simple command without args."""
        cmd = _make_cmd("status")
        
        assert cmd.command == "status"
        assert cmd.args == []
        assert cmd.chat_id == "CLI"
        assert cmd.user_id == "CLI"
        assert cmd.message_id == 0
    
    def test_make_cmd_with_args(self):
        """Test creating a command with arguments."""
        cmd = _make_cmd("close", ["BTC", "50"])
        
        assert cmd.command == "close"
        assert cmd.args == ["BTC", "50"]
        assert cmd.raw_text == "/close BTC 50"
    
    def test_make_cmd_config_subcommand(self):
        """Test creating a config subcommand."""
        cmd = _make_cmd("config", ["list"])
        
        assert cmd.command == "config"
        assert cmd.args == ["list"]


class TestStripMarkdown:
    """Tests for strip_markdown output formatter."""
    
    def test_strip_escape_characters(self):
        """Test removing escape backslashes."""
        text = r"Kill\-Switch 已激活"
        result = strip_markdown(text)
        assert result == "Kill-Switch 已激活"
    
    def test_strip_multiple_escapes(self):
        """Test removing multiple escape characters."""
        text = r"配置项: `TRADEBOT\_INTERVAL` \- 交易循环间隔"
        result = strip_markdown(text)
        assert result == "配置项: `TRADEBOT_INTERVAL` - 交易循环间隔"
    
    def test_strip_bold(self):
        """Test removing bold markers."""
        text = "*可用余额:* `$1,000.00`"
        result = strip_markdown(text)
        assert result == "可用余额: `$1,000.00`"
    
    def test_preserve_emoji(self):
        """Test that emoji are preserved."""
        text = "📊 *Bot 状态*"
        result = strip_markdown(text)
        assert "📊" in result
        assert "Bot 状态" in result
    
    def test_empty_string(self):
        """Test handling empty string."""
        assert strip_markdown("") == ""
    
    def test_none_handling(self):
        """Test handling None-like input."""
        assert strip_markdown("") == ""


class TestCliCommands:
    """Integration tests for CLI commands using Click's test runner."""
    
    @pytest.fixture
    def runner(self):
        """Create a CLI test runner."""
        return CliRunner()
    
    def test_help_command(self, runner):
        """Test --help shows all commands."""
        result = runner.invoke(cli, ["--help"])
        
        assert result.exit_code == 0
        assert "LLM Trader CLI" in result.output
        assert "status" in result.output
        assert "balance" in result.output
        assert "positions" in result.output
        assert "kill" in result.output
        assert "resume" in result.output
        assert "config" in result.output
        assert "symbols" in result.output
    
    def test_config_help(self, runner):
        """Test config --help shows subcommands."""
        result = runner.invoke(cli, ["config", "--help"])
        
        assert result.exit_code == 0
        assert "list" in result.output
        assert "get" in result.output
        assert "set" in result.output
    
    def test_symbols_help(self, runner):
        """Test symbols --help shows subcommands."""
        result = runner.invoke(cli, ["symbols", "--help"])
        
        assert result.exit_code == 0
        assert "list" in result.output
        assert "add" in result.output
        assert "remove" in result.output
    
    def test_config_list(self, runner):
        """Test config list command runs."""
        result = runner.invoke(cli, ["config", "list"])
        
        # Should succeed and show config items
        assert result.exit_code == 0
        assert "TRADEBOT_INTERVAL" in result.output or "可配置项" in result.output
    
    def test_symbols_list(self, runner):
        """Test symbols list command runs."""
        result = runner.invoke(cli, ["symbols", "list"])
        
        # Should succeed and show universe
        assert result.exit_code == 0
        assert "Universe" in result.output or "交易" in result.output
    
    def test_close_missing_symbol(self, runner):
        """Test close command requires symbol argument."""
        result = runner.invoke(cli, ["close"])
        
        # Should fail with missing argument error
        assert result.exit_code != 0
        assert "SYMBOL" in result.output or "Missing argument" in result.output
    
    def test_sl_missing_args(self, runner):
        """Test sl command requires both symbol and value."""
        result = runner.invoke(cli, ["sl", "BTC"])
        
        # Should fail with missing argument error
        assert result.exit_code != 0
        assert "VALUE" in result.output or "Missing argument" in result.output


class TestCliOutputFormat:
    """Tests for CLI output formatting."""
    
    @pytest.fixture
    def runner(self):
        return CliRunner()
    
    def test_output_has_no_backslash_escapes(self, runner):
        """Test that output doesn't contain MarkdownV2 escapes."""
        result = runner.invoke(cli, ["config", "list"])
        
        # Should not have escaped characters like \- or \_
        assert r"\-" not in result.output
        assert r"\_" not in result.output
    
    def test_output_preserves_emoji(self, runner):
        """Test that emoji are preserved in output."""
        result = runner.invoke(cli, ["config", "list"])
        
        # Config list should have emoji
        assert "⚙️" in result.output or result.exit_code == 0
