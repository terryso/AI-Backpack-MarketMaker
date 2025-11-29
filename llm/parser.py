"""LLM response parsing and recovery.

This module provides functions for parsing LLM responses and recovering
partial decisions from truncated or malformed JSON.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple


def recover_partial_decisions(
    json_str: str,
    coins: Iterable[str],
) -> Optional[Tuple[Dict[str, Any], List[str]]]:
    """Attempt to salvage individual coin decisions from truncated JSON.

    This function tries to extract valid JSON objects for each coin even
    when the overall response is malformed or truncated.
    
    Args:
        json_str: The potentially malformed JSON string.
        coins: List of coin names to look for in the response.
        
    Returns:
        Tuple of (recovered_decisions, missing_coins) or None if recovery failed.
    """
    coin_list = list(coins)
    recovered: Dict[str, Any] = {}
    missing: List[str] = []

    for coin in coin_list:
        marker = f'"{coin}"'
        marker_idx = json_str.find(marker)
        if marker_idx == -1:
            missing.append(coin)
            continue

        obj_start = json_str.find("{", marker_idx)
        if obj_start == -1:
            missing.append(coin)
            continue

        depth = 0
        in_string = False
        escaped = False
        end_idx: Optional[int] = None

        for idx in range(obj_start, len(json_str)):
            char = json_str[idx]
            if in_string:
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == '"':
                    in_string = False
                continue

            if char == '"':
                in_string = True
            elif char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    end_idx = idx
                    break

        if end_idx is None:
            missing.append(coin)
            continue

        block = json_str[obj_start : end_idx + 1]
        try:
            recovered[coin] = json.loads(block)
        except json.JSONDecodeError:
            missing.append(coin)

    if not recovered:
        return None

    missing = list(dict.fromkeys(missing))

    fallback_message = "Missing data from truncated AI response; defaulting to hold."
    for coin in coin_list:
        if coin not in recovered:
            recovered[coin] = {
                "signal": "hold",
                "justification": fallback_message,
                "confidence": 0.0,
            }

    return recovered, missing


def parse_llm_json_decisions(
    content: str,
    *,
    response_id: Optional[str],
    status_code: int,
    finish_reason: Optional[str],
    notify_error: Callable[..., Any],
    log_llm_decisions: Callable[[Dict[str, Any]], None],
    recover_partial_decisions: Callable[[str], Optional[Tuple[Dict[str, Any], List[str]]]],
) -> Optional[Dict[str, Any]]:
    """Extract and decode LLM JSON decisions with partial recovery.

    This function encapsulates the JSON extraction, decoding, partial
    recovery, and error notification logic for LLM responses.
    
    Args:
        content: The raw LLM response content.
        response_id: Optional response ID for logging.
        status_code: HTTP status code of the response.
        finish_reason: The finish reason from the LLM API.
        notify_error: Function to call for error notifications.
        log_llm_decisions: Function to log parsed decisions.
        recover_partial_decisions: Function to attempt partial recovery.
        
    Returns:
        Parsed decisions dictionary or None on failure.
    """
    start = content.find("{")
    end = content.rfind("}") + 1
    if start != -1 and end > start:
        json_str = content[start:end]
        try:
            decisions = json.loads(json_str)
            log_llm_decisions(decisions)
            return decisions
        except json.JSONDecodeError as decode_err:
            recovery = recover_partial_decisions(json_str)
            if recovery:
                decisions, missing_coins = recovery
                if missing_coins:
                    notification_message = (
                        "LLM response truncated; defaulted to hold for missing coins"
                    )
                else:
                    notification_message = (
                        "LLM response malformed; recovered all coin decisions"
                    )
                logging.warning(
                    "Recovered LLM response after JSON error (missing coins: %s)",
                    ", ".join(missing_coins) or "none",
                )
                notify_error(
                    notification_message,
                    metadata={
                        "response_id": response_id,
                        "status_code": status_code,
                        "missing_coins": missing_coins,
                        "finish_reason": finish_reason,
                        "raw_json_excerpt": json_str[:2000],
                        "decode_error": str(decode_err),
                    },
                    log_error=False,
                )
                log_llm_decisions(decisions)
                return decisions

            snippet = json_str[:2000]
            notify_error(
                f"LLM JSON decode failed: {decode_err}",
                metadata={
                    "response_id": response_id,
                    "status_code": status_code,
                    "finish_reason": finish_reason,
                    "raw_json_excerpt": snippet,
                },
            )
            return None

    # No JSON found - try to extract signals from text or return default holds
    logging.warning("No JSON found in LLM response; attempting text-based signal extraction...")
    
    # Try to extract any trading signals from plain text
    text_decisions = _extract_signals_from_text(content)
    if text_decisions:
        logging.info("Extracted %d signal(s) from text response", len(text_decisions))
        log_llm_decisions(text_decisions)
        return text_decisions
    
    # Log warning but don't send error notification for non-JSON responses
    logging.warning(
        "No JSON or extractable signals in LLM response (finish_reason=%s); skipping this iteration",
        finish_reason,
    )
    return None


def _extract_signals_from_text(content: str) -> Optional[Dict[str, Any]]:
    """Try to extract trading signals from plain text response.
    
    This handles cases where the LLM returns analysis text instead of JSON.
    Looks for patterns like "BTC: hold", "ETH: entry long", etc.
    """
    import re
    from config.settings import SYMBOL_TO_COIN
    
    coins = list(SYMBOL_TO_COIN.values())
    decisions: Dict[str, Any] = {}
    content_lower = content.lower()
    
    for coin in coins:
        coin_lower = coin.lower()
        
        # Look for explicit signal patterns
        # Pattern: "COIN: signal" or "COIN - signal" or "COIN signal"
        patterns = [
            rf'\b{coin_lower}\s*[:\-]\s*(hold|entry|close|long|short|buy|sell)\b',
            rf'\b{coin_lower}\s+(hold|entry|close|long|short|buy|sell)\b',
            rf'(hold|entry|close|long|short|buy|sell)\s+{coin_lower}\b',
        ]
        
        for pattern in patterns:
            match = re.search(pattern, content_lower)
            if match:
                signal_word = match.group(1) if match.lastindex else match.group(0)
                signal_word = signal_word.strip().lower()
                
                # Map signal words to standard signals
                if signal_word in ('hold',):
                    signal = 'hold'
                elif signal_word in ('entry', 'long', 'buy'):
                    signal = 'entry'
                    side = 'long'
                elif signal_word in ('short', 'sell'):
                    signal = 'entry'
                    side = 'short'
                elif signal_word in ('close',):
                    signal = 'close'
                else:
                    continue
                
                decision = {
                    "signal": signal,
                    "justification": f"Extracted from text response: {match.group(0)}",
                    "confidence": 0.5,  # Lower confidence for text-extracted signals
                }
                if signal == 'entry':
                    decision["side"] = side
                
                decisions[coin] = decision
                break
    
    return decisions if decisions else None
