"""
LLM client for trading decisions.

This module handles all interactions with the LLM API including
prompt formatting, API calls, and response parsing.
"""
from __future__ import annotations

import logging
from typing import Any, Callable, Dict, List, Optional, Tuple

import requests

from config.settings import (
    LLM_API_KEY,
    LLM_API_BASE_URL,
    LLM_API_TYPE,
    LLM_MODEL_NAME,
    LLM_TEMPERATURE,
    LLM_MAX_TOKENS,
    LLM_THINKING_PARAM,
    TRADING_RULES_PROMPT,
    SYMBOL_TO_COIN,
)
from llm.parser import (
    recover_partial_decisions as _strategy_recover_partial_decisions,
    parse_llm_json_decisions as _strategy_parse_llm_json_decisions,
)


def _recover_partial_decisions(json_str: str) -> Optional[Tuple[Dict[str, Any], List[str]]]:
    """Attempt to salvage individual coin decisions from truncated JSON.

    This thin wrapper delegates to strategy_core.recover_partial_decisions so
    that the recovery algorithm lives in strategy_core while preserving this
    helper's name and signature for existing callers and tests.
    """
    coins = list(SYMBOL_TO_COIN.values())
    return _strategy_recover_partial_decisions(json_str, coins)


def _log_llm_decisions(decisions: Dict[str, Any]) -> None:
    """Log a compact, human-readable summary of LLM decisions for all coins."""
    try:
        parts: List[str] = []
        summary_parts: List[str] = []
        for coin, raw_decision in decisions.items():
            if not isinstance(raw_decision, dict):
                continue
            decision = raw_decision
            signal = str(decision.get("signal", "hold")).lower()
            side = str(decision.get("side", "")).lower()
            quantity = decision.get("quantity")
            tp = decision.get("profit_target")
            sl = decision.get("stop_loss")
            confidence = decision.get("confidence")

            justification = decision.get("justification")
            if justification:
                reason_snippet = " ".join(str(justification).split())
                if len(reason_snippet) > 200:
                    reason_snippet = reason_snippet[:197] + "..."
                summary_parts.append(f"{coin}: {reason_snippet}")

            if signal == "entry":
                parts.append(
                    f"{coin}: ENTRY {side or '-'} qty={quantity} tp={tp} sl={sl} conf={confidence}"
                )
            elif signal == "close":
                parts.append(f"{coin}: CLOSE {side or '-'}")
            else:
                parts.append(f"{coin}: HOLD")

        if summary_parts:
            logging.info("LLM decision summary:\n%s", "\n".join(summary_parts))

        if parts:
            logging.info("LLM decisions: %s", " | ".join(parts))
    except Exception:
        logging.exception("Failed to log LLM decisions")


def call_deepseek_api(
    prompt: str,
    log_ai_message_fn: Callable[[str, str, str, Optional[Dict[str, Any]]], None],
    notify_error_fn: Callable[..., None],
) -> Optional[Dict[str, Any]]:
    """Call OpenRouter API with DeepSeek Chat V3.1.
    
    Args:
        prompt: The user prompt to send to the LLM.
        log_ai_message_fn: Function to log AI messages (direction, role, content, metadata).
        notify_error_fn: Function to notify errors.
    
    Returns:
        Parsed decisions dictionary or None on failure.
    """
    api_key = LLM_API_KEY
    if not api_key:
        logging.error("No LLM API key configured; expected LLM_API_KEY or OPENROUTER_API_KEY in environment.")
        return None
    try:
        request_metadata: Dict[str, Any] = {
            "model": LLM_MODEL_NAME,
            "temperature": LLM_TEMPERATURE,
            "max_tokens": LLM_MAX_TOKENS,
        }
        if LLM_THINKING_PARAM is not None:
            request_metadata["thinking"] = LLM_THINKING_PARAM

        log_ai_message_fn(
            "sent",
            "system",
            TRADING_RULES_PROMPT,
            request_metadata,
        )
        log_ai_message_fn(
            "sent",
            "user",
            prompt,
            request_metadata,
        )

        request_payload: Dict[str, Any] = {
            "model": LLM_MODEL_NAME,
            "messages": [
                {
                    "role": "system",
                    "content": TRADING_RULES_PROMPT,
                },
                {
                    "role": "user",
                    "content": prompt,
                },
            ],
            "temperature": LLM_TEMPERATURE,
            "max_tokens": LLM_MAX_TOKENS,
        }
        if LLM_THINKING_PARAM is not None:
            request_payload["thinking"] = LLM_THINKING_PARAM

        headers: Dict[str, str] = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        api_type = (LLM_API_TYPE or "openrouter").lower()
        if api_type == "openrouter":
            headers["HTTP-Referer"] = "https://github.com/crypto-trading-bot"
            headers["X-Title"] = "DeepSeek Trading Bot"

        response = requests.post(
            url=LLM_API_BASE_URL,
            headers=headers,
            json=request_payload,
            timeout=90,
        )

        if response.status_code != 200:
            notify_error_fn(
                f"LLM API error: {response.status_code}",
                metadata={
                    "status_code": response.status_code,
                    "response_text": response.text,
                },
            )
            return None

        result = response.json()
        choices = result.get("choices")
        if not choices:
            notify_error_fn(
                "LLM API returned no choices",
                metadata={
                    "status_code": response.status_code,
                    "response_text": response.text[:500],
                },
            )
            return None

        primary_choice = choices[0]
        message = primary_choice.get("message") or {}
        content = message.get("content", "") or ""
        finish_reason = primary_choice.get("finish_reason")

        log_ai_message_fn(
            "received",
            "assistant",
            content,
            {
                "status_code": response.status_code,
                "response_id": result.get("id"),
                "usage": result.get("usage"),
                "finish_reason": finish_reason,
            }
        )

        decisions = _strategy_parse_llm_json_decisions(
            content,
            response_id=result.get("id"),
            status_code=response.status_code,
            finish_reason=finish_reason,
            notify_error=notify_error_fn,
            log_llm_decisions=_log_llm_decisions,
            recover_partial_decisions=_recover_partial_decisions,
        )
        return decisions
    except Exception as e:
        logging.exception("Error calling LLM API")
        notify_error_fn(
            f"Error calling LLM API: {e}",
            metadata={"context": "call_deepseek_api"},
            log_error=False,
        )
        return None
