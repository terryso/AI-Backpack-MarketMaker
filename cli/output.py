"""
Output formatting utilities for CLI.

Converts Telegram MarkdownV2 formatted messages to terminal-friendly text.
"""
from __future__ import annotations

import re
import sys


def strip_markdown(text: str) -> str:
    """Convert Telegram MarkdownV2 text to plain terminal text.
    
    This function:
    - Removes escape backslashes (\\-, \\_, \\., etc.)
    - Converts *bold* to plain text
    - Converts `code` to plain text (keeps backticks for visibility)
    - Preserves emoji characters
    
    Args:
        text: MarkdownV2 formatted text from Telegram handlers.
        
    Returns:
        Plain text suitable for terminal output.
    """
    if not text:
        return ""
    
    # Remove escape backslashes for special characters
    # MarkdownV2 escapes: _ * [ ] ( ) ~ ` > # + - = | { } . !
    result = re.sub(r'\\([_*\[\]()~`>#+=|{}.!-])', r'\1', text)
    
    # Convert *bold* to plain text (remove asterisks)
    result = re.sub(r'\*([^*]+)\*', r'\1', result)
    
    # Keep backticks for code visibility but could remove if preferred
    # result = re.sub(r'`([^`]+)`', r'\1', result)
    
    return result


def print_result(message: str, success: bool = True) -> None:
    """Print command result to terminal.
    
    Args:
        message: MarkdownV2 formatted message from command handler.
        success: Whether the command succeeded (affects exit behavior).
    """
    plain_text = strip_markdown(message)
    print(plain_text)
    
    if not success:
        sys.exit(1)


def print_error(message: str) -> None:
    """Print error message to stderr and exit with code 1.
    
    Args:
        message: Error message to display.
    """
    print(f"错误: {message}", file=sys.stderr)
    sys.exit(1)
