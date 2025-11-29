"""Message formatting for Telegram signals and notifications.

This module provides functions for building rich formatted messages
for entry and close signals sent to Telegram.
"""
from __future__ import annotations


def build_entry_signal_message(
    *,
    coin: str,
    side: str,
    leverage_display: str,
    entry_price: float,
    quantity: float,
    margin_required: float,
    risk_usd: float,
    profit_target_price: float,
    stop_loss_price: float,
    gross_at_target: float,
    gross_at_stop: float,
    rr_display: str,
    entry_fee: float,
    confidence: float,
    reason_text_for_signal: str,
    liquidity: str,
    timestamp: str,
) -> str:
    """Render the rich Telegram ENTRY signal message body.

    This helper creates a formatted message for entry signals that is
    suitable for sending to Telegram with Markdown parsing.
    
    Args:
        coin: The coin symbol (e.g., "BTC").
        side: Trade direction ("long" or "short").
        leverage_display: Formatted leverage string (e.g., "10x").
        entry_price: Entry price for the position.
        quantity: Position size in coin units.
        margin_required: Required margin in USD.
        risk_usd: Risk amount in USD.
        profit_target_price: Take profit price.
        stop_loss_price: Stop loss price.
        gross_at_target: Gross PnL at target price.
        gross_at_stop: Gross PnL at stop price.
        rr_display: Risk/reward ratio display string.
        entry_fee: Entry fee in USD.
        confidence: Confidence level (0-1).
        reason_text_for_signal: Escaped justification text.
        liquidity: Order type ("maker" or "taker").
        timestamp: Formatted timestamp string.
        
    Returns:
        Formatted Telegram message string.
    """
    confidence_pct = confidence * 100
    side_emoji = "🟢" if side.lower() == "long" else "🔴"

    signal_text = (
        f"{side_emoji} *ENTRY SIGNAL* {side_emoji}\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"*Asset:* `{coin}`\n"
        f"*Direction:* {side.upper()} {leverage_display}\n"
        f"*Entry Price:* `${entry_price:.4f}`\n"
        f"\n"
        f"📊 *Position Details*\n"
        f"• Size: `{quantity:.4f} {coin}`\n"
        f"• Margin: `${margin_required:.2f}`\n"
        f"• Risk: `${risk_usd:.2f}`\n"
        f"\n"
        f"🎯 *Targets & Stops*\n"
        f"• Target: `${profit_target_price:.4f}` ({'+' if gross_at_target >= 0 else ''}`${gross_at_target:.2f}`)\n"
        f"• Stop Loss: `${stop_loss_price:.4f}` (`${gross_at_stop:.2f}`)\n"
        f"• R/R Ratio: `{rr_display}`\n"
        f"\n"
        f"⚙️ *Execution*\n"
        f"• Liquidity: `{liquidity}`\n"
        f"• Confidence: `{confidence_pct:.0f}%`\n"
        f"• Entry Fee: `${entry_fee:.2f}`\n"
        f"\n"
        f"💭 *Reasoning*\n"
        f"_{reason_text_for_signal}_\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"🕐 {timestamp}"
    )
    return signal_text


def build_close_signal_message(
    *,
    coin: str,
    side: str,
    quantity: float,
    entry_price: float,
    current_price: float,
    pnl: float,
    total_fees: float,
    net_pnl: float,
    margin: float,
    balance: float,
    reason_text_for_signal: str,
    timestamp: str,
) -> str:
    """Render the rich Telegram CLOSE signal message body.

    This helper creates a formatted message for close signals that is
    suitable for sending to Telegram with Markdown parsing.
    
    Args:
        coin: The coin symbol (e.g., "BTC").
        side: Trade direction ("long" or "short").
        quantity: Position size in coin units.
        entry_price: Original entry price.
        current_price: Exit price.
        pnl: Gross PnL in USD.
        total_fees: Total fees paid in USD.
        net_pnl: Net PnL after fees in USD.
        margin: Position margin in USD.
        balance: New account balance after close.
        reason_text_for_signal: Escaped justification text.
        timestamp: Formatted timestamp string.
        
    Returns:
        Formatted Telegram message string.
    """
    if net_pnl > 0:
        result_emoji = "✅"
        result_label = "PROFIT"
    elif net_pnl < 0:
        result_emoji = "❌"
        result_label = "LOSS"
    else:
        result_emoji = "➖"
        result_label = "BREAKEVEN"

    price_change_pct = ((current_price - entry_price) / entry_price) * 100
    price_change_sign = "+" if price_change_pct >= 0 else ""

    roi_pct = (net_pnl / margin) * 100 if margin > 0 else 0
    roi_sign = "+" if roi_pct >= 0 else ""

    close_signal = (
        f"{result_emoji} *CLOSE SIGNAL - {result_label}* {result_emoji}\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"*Asset:* `{coin}`\n"
        f"*Direction:* {side.upper()}\n"
        f"*Size:* `{quantity:.4f} {coin}`\n"
        f"\n"
        f"💰 *P&L Summary*\n"
        f"• Entry: `${entry_price:.4f}`\n"
        f"• Exit: `${current_price:.4f}` ({price_change_sign}{price_change_pct:.2f}%)\n"
        f"• Gross P&L: `${pnl:.2f}`\n"
        f"• Fees Paid: `${total_fees:.2f}`\n"
        f"• *Net P&L:* `${net_pnl:.2f}`\n"
        f"• ROI: `{roi_sign}{roi_pct:.1f}%`\n"
        f"\n"
        f"📈 *Updated Balance*\n"
        f"• New Balance: `${balance:.2f}`\n"
        f"\n"
        f"💭 *Exit Reasoning*\n"
        f"_{reason_text_for_signal}_\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"🕐 {timestamp}"
    )
    return close_signal
