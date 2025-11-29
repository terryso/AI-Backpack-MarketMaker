"""Text processing utilities.

This module provides common text manipulation functions used throughout
the trading bot, including ANSI code stripping and Markdown escaping.
"""
from __future__ import annotations

import re

# Compiled regex for ANSI escape sequences
ANSI_ESCAPE_RE = re.compile(r"\x1B\[[0-?]*[ -/]*[@-~]")


def strip_ansi_codes(text: str) -> str:
    """Remove ANSI color codes so Telegram receives plain text.
    
    Args:
        text: Input string potentially containing ANSI escape sequences.
        
    Returns:
        String with all ANSI escape sequences removed.
    """
    return ANSI_ESCAPE_RE.sub("", text)


def escape_markdown(text: str) -> str:
    """Escape characters that have special meaning in Telegram Markdown.
    
    Args:
        text: Input string to escape.
        
    Returns:
        String with Telegram Markdown special characters escaped.
    """
    if not text:
        return text
    specials = r"_*[]()~`>#+-=|{}.!\\"
    return "".join(f"\\{char}" if char in specials else char for char in text)
