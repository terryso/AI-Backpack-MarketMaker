"""
Handler for /positions command to show detailed open positions.
"""
from __future__ import annotations

import logging
from typing import Any, Callable, Dict, List, Optional

from notifications.commands.base import (
    TelegramCommand,
    CommandResult,
    escape_markdown,
    trim_decimal,
)
from config.settings import IS_LIVE_BACKEND, LIVE_MAX_LEVERAGE
from core.metrics import calculate_unrealized_pnl_for_position


def parse_live_positions(raw_positions: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """Parse live positions from exchange snapshot into standardized format.
    
    This function converts raw position data from exchanges (e.g., Backpack Futures)
    into the standardized format expected by handle_positions_command.
    
    Args:
        raw_positions: List of raw position dicts from exchange API.
        
    Returns:
        Dict mapping coin symbol to position data with standardized keys:
        - side: "long" or "short"
        - quantity: Absolute position size
        - entry_price: Entry price
        - profit_target: Take profit price
        - stop_loss: Stop loss price
        - leverage: Position leverage
        - margin: Margin used
        - risk_usd: Risk in USD (0.0 if not available)
        - pnl: Realized + unrealized PnL
        - liquidation_price: Estimated liquidation price
    """
    positions: Dict[str, Dict[str, Any]] = {}
    
    for pos in raw_positions:
        if not isinstance(pos, dict):
            continue

        symbol = str(pos.get("symbol", "") or "").strip()
        if not symbol:
            continue

        # 兼容 Backpack 符号（如 BTC_USDC_PERP），提取前缀作为 coin
        upper_symbol = symbol.upper()
        if "_" in upper_symbol:
            coin = upper_symbol.split("_", 1)[0]
        else:
            coin = upper_symbol

        # 尝试从多种字段推导净持仓数量
        net_qty = 0.0
        for qty_field in ("netQuantity", "netExposureQuantity", "quantity", "size"):
            raw_val = pos.get(qty_field)
            if raw_val is None:
                continue
            try:
                net_qty = float(raw_val)
            except (TypeError, ValueError):
                continue
            if net_qty != 0.0:
                break

        if net_qty == 0.0:
            continue

        side = "long" if net_qty > 0 else "short"
        quantity = abs(net_qty)

        # 入场价 / TP / SL
        entry_price = _safe_float(pos.get("entryPrice"))
        tp = _safe_float(pos.get("takeProfitPrice"))
        sl = _safe_float(pos.get("stopLossPrice"))

        # notional
        notional = abs(_safe_float(pos.get("netExposureNotional")))
        if notional == 0.0 and entry_price > 0.0 and quantity > 0.0:
            notional = abs(quantity * entry_price)

        # imf: 初始保证金系数（代表该合约支持的最大杠杆的倒数，而不是实际杠杆）
        imf = _safe_float(pos.get("imf"))

        # 先尝试使用交易所返回的实际杠杆
        leverage = _safe_float(pos.get("leverage"))

        # 保证金
        margin = 0.0
        for margin_field in ("initialMargin", "marginUsed", "margin"):
            margin = _safe_float(pos.get(margin_field))
            if margin > 0.0:
                break

        # 如果没有显式保证金，但有 notional 和杠杆，则用 notional / leverage 推导
        if margin <= 0.0 and notional > 0.0 and leverage > 0.0:
            margin = abs(notional) / leverage

        # 若仍然没有保证金，在实盘后端下优先使用 LIVE_MAX_LEVERAGE 反推
        if margin <= 0.0 and notional > 0.0:
            if IS_LIVE_BACKEND and LIVE_MAX_LEVERAGE > 0.0:
                margin = abs(notional) / LIVE_MAX_LEVERAGE
            elif imf > 0.0:
                # 仅在无更好信息时，将 imf 作为兜底近似
                margin = abs(notional) * imf

        # 最终确定杠杆：若未能从交易所拿到，则用 notional / margin 反推
        if leverage <= 0.0 and margin > 0.0 and notional > 0.0:
            leverage = abs(notional) / margin
        if leverage <= 0.0 and imf > 0.0:
            leverage = 1.0 / imf
        if leverage <= 0.0:
            leverage = 1.0

        # 盈亏
        realized = _safe_float(pos.get("pnlRealized"))
        unrealized = _safe_float(pos.get("pnlUnrealized"))
        pnl = realized + unrealized

        # 强平价
        liq_price = _safe_float(pos.get("estLiquidationPrice"))

        positions[coin] = {
            "side": side,
            "quantity": quantity,
            "entry_price": entry_price,
            "profit_target": tp,
            "stop_loss": sl,
            "leverage": leverage,
            "margin": margin,
            "risk_usd": 0.0,
            "pnl": pnl,
            "liquidation_price": liq_price,
        }

    return positions


def _safe_float(value: Any, default: float = 0.0) -> float:
    """Safely convert a value to float."""
    if value is None:
        return default
    try:
        result = float(value)
        # NaN check
        if result != result:
            return default
        return result
    except (TypeError, ValueError):
        return default


def get_positions_from_snapshot(
    account_snapshot_fn: Optional[Callable[[], Optional[Dict[str, Any]]]] = None,
    positions_snapshot_fn: Optional[Callable[[], Dict[str, Dict[str, Any]]]] = None,
) -> Dict[str, Dict[str, Any]]:
    """Get positions from account snapshot or local portfolio.
    
    Prioritizes live exchange data when available, falls back to local portfolio.
    
    Args:
        account_snapshot_fn: Function to get live exchange account snapshot.
        positions_snapshot_fn: Function to get local portfolio positions.
        
    Returns:
        Dict mapping coin symbol to position data.
    """
    positions: Dict[str, Dict[str, Any]] = {}
    local_snapshot: Optional[Dict[str, Dict[str, Any]]] = None
    
    # 1) 优先尝试从实盘账户 snapshot 中提取持仓
    if account_snapshot_fn is not None:
        try:
            snapshot = account_snapshot_fn()
        except Exception as exc:
            logging.warning("Failed to get live account snapshot for positions: %s", exc)
            snapshot = None
        
        if isinstance(snapshot, dict):
            raw_positions = snapshot.get("positions")
            if isinstance(raw_positions, list):
                positions = parse_live_positions(raw_positions)

    # 1b) 若存在本地持仓视图，则用本地 TP/SL 补全实盘视图中的 TP/SL
    if positions and positions_snapshot_fn is not None:
        try:
            local_snapshot = positions_snapshot_fn()
        except Exception as exc:
            logging.error("Error calling positions_snapshot_fn for TP/SL overlay: %s", exc)
            local_snapshot = None
        if isinstance(local_snapshot, dict):
            for coin, live_pos in positions.items():
                local_pos = local_snapshot.get(coin)
                if not isinstance(local_pos, dict):
                    continue

                live_tp = _safe_float(live_pos.get("profit_target"))
                live_sl = _safe_float(live_pos.get("stop_loss"))
                local_tp = _safe_float(local_pos.get("profit_target"))
                local_sl = _safe_float(local_pos.get("stop_loss"))

                if live_tp <= 0.0 and local_tp > 0.0:
                    live_pos["profit_target"] = local_tp
                if live_sl <= 0.0 and local_sl > 0.0:
                    live_pos["stop_loss"] = local_sl
    
    # 2) 若实盘 snapshot 不可用或无有效持仓，则回退到本地 positions 视图
    if not positions and positions_snapshot_fn is not None:
        try:
            # 复用上面获取的 local_snapshot（若已存在），否则重新获取
            if local_snapshot is None:
                local_snapshot = positions_snapshot_fn()
        except Exception as exc:
            logging.error("Error calling positions_snapshot_fn: %s", exc)
            local_snapshot = None
        if isinstance(local_snapshot, dict):
            positions = local_snapshot
    
    return positions


def handle_positions_command(
    cmd: TelegramCommand,
    *,
    positions: Dict[str, Dict[str, Any]],
    get_current_price_fn: Optional[Callable[[str], Optional[float]]] = None,
) -> CommandResult:
    """Handle the /positions command to show detailed open positions.
    
    This command lists all open positions with key fields such as side,
    quantity, entry price, TP/SL and margin usage.
    """
    logging.info(
        "Telegram /positions command received: chat_id=%s, message_id=%d",
        cmd.chat_id,
        cmd.message_id,
    )

    if not positions:
        message = (
            "📂 当前持仓列表\n\n"
            "当前没有任何持仓。\n\n"
            "提示: 可使用 /status 或 /balance 查看账户概况。"
        )
        return CommandResult(
            success=True,
            message=escape_markdown(message),
            state_changed=False,
            action="POSITIONS_SNAPSHOT",
        )

    lines: list[str] = []
    lines.append("📂 当前持仓列表\n")
    lines.append(f"持仓数量: {len(positions)}\n")

    for coin in sorted(positions.keys()):
        pos = positions.get(coin) or {}

        side_raw = str(pos.get("side", "")).upper() or "UNKNOWN"
        try:
            quantity = float(pos.get("quantity", 0.0) or 0.0)
        except (TypeError, ValueError):
            quantity = 0.0
        try:
            entry_price = float(pos.get("entry_price", 0.0) or 0.0)
        except (TypeError, ValueError):
            entry_price = 0.0
        try:
            tp = float(pos.get("profit_target", 0.0) or 0.0)
        except (TypeError, ValueError):
            tp = 0.0
        try:
            sl = float(pos.get("stop_loss", 0.0) or 0.0)
        except (TypeError, ValueError):
            sl = 0.0
        leverage = pos.get("leverage", 1.0)
        try:
            margin = float(pos.get("margin", 0.0) or 0.0)
        except (TypeError, ValueError):
            margin = 0.0
        try:
            risk_usd = float(pos.get("risk_usd", 0.0) or 0.0)
        except (TypeError, ValueError):
            risk_usd = 0.0
        try:
            pnl = float(pos.get("pnl", 0.0) or 0.0)
        except (TypeError, ValueError):
            pnl = 0.0
        try:
            liq_price = float(pos.get("liquidation_price", 0.0) or 0.0)
        except (TypeError, ValueError):
            liq_price = 0.0

        coin_display = str(coin)
        side_display = side_raw

        qty_str = trim_decimal(quantity, max_decimals=4)
        entry_str = trim_decimal(entry_price, max_decimals=4)
        tp_str = trim_decimal(tp, max_decimals=4)
        sl_str = trim_decimal(sl, max_decimals=4)
        try:
            leverage_float = float(leverage)
        except (TypeError, ValueError):
            leverage_float = 0.0
        leverage_str = trim_decimal(leverage_float, max_decimals=2)

        current_price = 0.0
        if get_current_price_fn is not None:
            try:
                price_val = get_current_price_fn(str(coin))
            except Exception as exc:
                logging.warning("Failed to get current price for %s: %s", coin, exc)
                price_val = None
            try:
                if price_val is not None:
                    current_price = float(price_val)
            except (TypeError, ValueError):
                current_price = 0.0
        current_price_str = ""
        if current_price > 0.0:
            current_price_str = trim_decimal(current_price, max_decimals=4)

        unrealized_pnl = 0.0
        has_unrealized_source = current_price > 0.0 and quantity > 0.0 and entry_price > 0.0
        if has_unrealized_source:
            try:
                unrealized_pnl = calculate_unrealized_pnl_for_position(
                    {
                        "side": pos.get("side", side_raw),
                        "quantity": quantity,
                        "entry_price": entry_price,
                    },
                    current_price,
                )
            except Exception:
                unrealized_pnl = 0.0

        if current_price_str:
            lines.append(
                f"• {coin_display} {side_display} x{qty_str} @ ${entry_str} (现价 ${current_price_str})"
            )
        else:
            lines.append(
                f"• {coin_display} {side_display} x{qty_str} @ ${entry_str}"
            )
        if tp > 0.0 or sl > 0.0:
            lines.append(
                f"  TP ${tp_str} / SL ${sl_str} / 杠杆 {leverage_str}"
            )
        else:
            lines.append(
                f"  杠杆 {leverage_str}"
            )

        if margin > 0.0 or risk_usd > 0.0:
            lines.append(
                f"  保证金 ${margin:,.2f}"
            )

        if pnl != 0.0 or liq_price > 0.0:
            liq_str = trim_decimal(liq_price, max_decimals=4) if liq_price > 0.0 else ""
            liq_part = f" / 强平价 ${liq_str}" if liq_price > 0.0 else ""
            lines.append(
                f"  当前盈亏 {pnl:+,.2f}{liq_part}"
            )

        if has_unrealized_source:
            lines.append(
                f"  未平仓盈亏 {unrealized_pnl:+,.2f}"
            )

    message = "\n".join(lines)

    return CommandResult(
        success=True,
        message=escape_markdown(message),
        state_changed=False,
        action="POSITIONS_SNAPSHOT",
    )
