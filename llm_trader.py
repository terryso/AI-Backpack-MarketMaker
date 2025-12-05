#!/usr/bin/env python3
"""
LLM Trader CLI entry point.

Usage:
    python llm_trader.py <command> [args...]
    
Or make it executable:
    chmod +x llm_trader.py
    ./llm_trader.py <command> [args...]
"""
from cli.main import main

if __name__ == "__main__":
    main()
